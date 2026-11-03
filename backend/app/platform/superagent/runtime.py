"""底座运行时接线 —— 调度引擎 TaskGenerator 注册 + bootstrap。

复用 SchedulerEngine 机制（统一监督/超时），不新起裸 asyncio 循环。
表未就绪（迁移未执行）时 bootstrap 拒绝注册生成器——底座代码合入
不等于启用，SUPERAGENT_ENABLED 默认 false。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from app.core.config import get_settings
from app.platform.scheduler import (
    ScheduleConfig,
    SchedulerRegistry,
    ScheduleStrategy,
    TaskGenerator,
)
from app.platform.superagent.effects import (
    claim_component,
    execute_claimed_effect,
    find_active_conversations,
    find_due_effect_ids,
    send_conversation_head,
)
from app.platform.superagent.ingest import ingest_source_once
from app.platform.superagent.models import AgentSource
from app.platform.superagent.sources import register_builtin_sources

logger = logging.getLogger(__name__)


class SourcePollGenerator(TaskGenerator):
    """事件层轮询生成器：每 tick 对全部启用源各跑一轮 poll→落库→推读位。"""

    name = "superagent.source_poll"
    settings_toggle_key = "SUPERAGENT_ENABLED"
    timeout_seconds = 60

    def __init__(self, interval_seconds: int = 30) -> None:
        self.schedule = ScheduleConfig(
            strategy=ScheduleStrategy.INTERVAL,
            interval_seconds=max(10, interval_seconds),
            timezone="Asia/Shanghai",
        )

    async def find_due(self, session: Any) -> list[Any]:
        rows = (
            await session.execute(
                select(AgentSource.id).where(AgentSource.enabled.is_(True))
            )
        ).scalars().all()
        return list(rows)

    async def execute_one(self, session: Any, source_id: Any) -> None:
        source_row = await session.get(AgentSource, source_id)
        if source_row is None or not source_row.enabled:
            return
        summary = await ingest_source_once(session, source_row)
        if "error" in summary:
            logger.warning("superagent 源 %s 摄取异常: %s", source_row.name, summary["error"])
        elif summary.get("stored") or summary.get("duplicate"):
            logger.info(
                "superagent 源 %s 一轮完成: %s", source_row.name, summary,
            )


class EffectsPoller(TaskGenerator):
    """effects 消费生成器：到期即取、逐项独立事务（自有 session，行锁即认领）。"""

    name = "superagent.effects_poll"
    settings_toggle_key = "SUPERAGENT_ENABLED"
    timeout_seconds = 120

    def __init__(self, interval_seconds: int = 2) -> None:
        self.schedule = ScheduleConfig(
            strategy=ScheduleStrategy.INTERVAL,
            interval_seconds=max(1, interval_seconds),
            timezone="Asia/Shanghai",
        )

    async def find_due(self, session: Any) -> list[Any]:
        return await find_due_effect_ids(session, limit=20)

    async def execute_one(self, session: Any, effect_id: Any) -> None:
        from app.core.database import async_session_factory

        # 自有 session：执行耗时外部调用期间持行锁认领，与引擎外层事务解耦
        async with async_session_factory() as own:
            try:
                outcome = await execute_claimed_effect(own, effect_id)
                await own.commit()
            except Exception:
                await own.rollback()
                logger.exception("effect 执行异常: id=%s", effect_id)
                return
        if outcome in ("parked",):
            logger.error("effect parked: id=%s（见 agent_effects.last_error）", effect_id)


class OutboxPoller(TaskGenerator):
    """outbox 消费生成器：逐会话推进队头（同会话严格保序，跨会话互不阻塞）。"""

    name = "superagent.outbox_poll"
    settings_toggle_key = "SUPERAGENT_ENABLED"
    timeout_seconds = 120

    def __init__(self, interval_seconds: int = 2) -> None:
        self.schedule = ScheduleConfig(
            strategy=ScheduleStrategy.INTERVAL,
            interval_seconds=max(1, interval_seconds),
            timezone="Asia/Shanghai",
        )

    async def find_due(self, session: Any) -> list[Any]:
        return await find_active_conversations(session, limit=20)

    async def execute_one(self, session: Any, conversation: str) -> None:
        from app.core.database import async_session_factory

        async with async_session_factory() as own:
            try:
                outcome = await send_conversation_head(own, conversation)
                await own.commit()
            except Exception:
                await own.rollback()
                logger.exception("outbox 会话发送异常: conv=%s", conversation)
                return
        if outcome == "dropped":
            logger.error("outbox 消息 dropped: conv=%s（见 dropped_reason）", conversation)


class TaskRunner(TaskGenerator):
    """任务运行生成器：有未读输入的 open 任务 → 领取（行锁）→ 执行器 → 落 Report。"""

    name = "superagent.task_runner"
    settings_toggle_key = "SUPERAGENT_ENABLED"
    timeout_seconds = 180

    def __init__(self, interval_seconds: int = 2) -> None:
        self.schedule = ScheduleConfig(
            strategy=ScheduleStrategy.INTERVAL,
            interval_seconds=max(1, interval_seconds),
            timezone="Asia/Shanghai",
        )

    async def find_due(self, session: Any) -> list[Any]:
        from app.platform.superagent.executors import find_runnable_task_ids

        return await find_runnable_task_ids(session, limit=10)

    async def execute_one(self, session: Any, task_id: Any) -> None:
        from app.core.database import async_session_factory
        from app.platform.superagent.executors import run_task_once

        async with async_session_factory() as own:
            try:
                outcome = await run_task_once(own, task_id)
                await own.commit()
            except Exception:
                await own.rollback()
                logger.exception("任务运行异常: id=%s", task_id)
                return
        if outcome == "no_executor":
            logger.error("任务 %s 无可用执行器（见 agent_tasks.executor）", task_id)


class WatchdogGenerator(TaskGenerator):
    """实质进展巡检：三条阈值规则 → dm_admin effect（先存后发，自举不裸奔）。"""

    name = "superagent.watchdog"
    settings_toggle_key = "SUPERAGENT_ENABLED"
    timeout_seconds = 120

    def __init__(self, interval_seconds: int = 300) -> None:
        self.schedule = ScheduleConfig(
            strategy=ScheduleStrategy.INTERVAL,
            interval_seconds=max(30, interval_seconds),
            timezone="Asia/Shanghai",
        )

    async def find_due(self, session: Any) -> list[Any]:
        # 巡检一轮一件工作；由 execute_one 自查节流（interval 已由调度控制）
        return [1]

    async def execute_one(self, session: Any, item: Any) -> None:
        from app.core.database import async_session_factory
        from app.platform.superagent.watchdog import run_watchdog_round

        async with async_session_factory() as own:
            try:
                await run_watchdog_round(own)
                await own.commit()
            except Exception:
                await own.rollback()
                logger.exception("Watchdog 轮异常")


async def superagent_tables_ready() -> bool:
    """底座表就绪检查（迁移 A 未执行时优雅降级：不注册生成器，不阻塞启动）。"""
    from app.core.database import async_session_factory

    try:
        async with async_session_factory() as session:
            await session.execute(select(AgentSource.id).limit(1))
        return True
    except Exception:
        logger.exception("superagent 表就绪检查失败（迁移未执行？）")
        return False


async def bootstrap_superagent(scheduler_registry: SchedulerRegistry) -> bool:
    """main.py lifespan 接线：注册内置插件 + 表就绪时注册生成器 + 健康认领。"""
    register_builtin_sources()
    if not await superagent_tables_ready():
        logger.warning(
            "Super-agent 底座表未就绪，本进程不注册底座生成器（执行迁移后重启生效）"
        )
        return False

    settings = get_settings()
    scheduler_registry.register_generator(
        SourcePollGenerator(
            interval_seconds=settings.SUPERAGENT_SOURCE_POLL_INTERVAL_SECONDS,
        )
    )
    scheduler_registry.register_generator(
        EffectsPoller(
            interval_seconds=settings.SUPERAGENT_EFFECTS_POLL_INTERVAL_SECONDS,
        )
    )
    scheduler_registry.register_generator(
        OutboxPoller(
            interval_seconds=settings.SUPERAGENT_EFFECTS_POLL_INTERVAL_SECONDS,
        )
    )
    scheduler_registry.register_generator(
        TaskRunner(interval_seconds=settings.SUPERAGENT_EFFECTS_POLL_INTERVAL_SECONDS),
    )
    scheduler_registry.register_generator(
        WatchdogGenerator(interval_seconds=settings.SUPERAGENT_WATCHDOG_INTERVAL_SECONDS),
    )

    # 健康条目认领（一组件一行；被他人活跃认领仅告警不阻塞——SKIP LOCKED 保证工作互斥）
    from app.core.database import async_session_factory
    from app.platform.superagent.effects import OWNER_ID

    try:
        async with async_session_factory() as session:
            for component in (
                "source_poll", "effects", "outbox", "watchdog",
            ):
                await claim_component(session, f"superagent:{component}")
            await session.commit()
    except Exception:
        logger.exception("Super-agent 健康认领失败（不阻塞启动）")

    logger.info(
        "Super-agent 底座已接线（source_poll=%ss / effects+outbox=%ss，owner=%s）",
        settings.SUPERAGENT_SOURCE_POLL_INTERVAL_SECONDS,
        settings.SUPERAGENT_EFFECTS_POLL_INTERVAL_SECONDS,
        OWNER_ID,
    )
    return True
