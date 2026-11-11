"""五金库定时任务（M3：紧急补单检查+审批轮询；M5：25 日月度计划/季度呆滞/温湿度提醒）。

TaskDefinition 模式照 warehouse/scheduled.py；main.py lifespan 注册。
- 月度计划 25 日 09:00（CRON——FIXED_TIME 仅每日，月度须 CRON）
- 呆滞季度扫描 1/4/7/10 月 1 日 09:00（CRON）
- 温湿度提醒每日 17:00（FIXED_TIME，当天未填才推）
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.database import async_session_factory
from app.platform.scheduler.registry import ScheduleConfig, ScheduleStrategy, TaskDefinition
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")


async def run_urgent_patch_check(db: AsyncSession, *, now: datetime | None = None) -> dict[str, int]:
    """紧急领用 24h 未补单检查：超期标 overdue_unpatched + 推提醒（幂等）。

    状态机（设计 §4.2）：urgent 发料后 24h 内补审批（approve 闭合
    patched_at）；逾期 → overdue_unpatched + 提醒推送（已逾期的不再重复推，
    状态即幂等闸）。
    """
    from app.modules.warehouse.hardware.models import HardwareRequisition
    from app.modules.warehouse.push_center.events import fire_push_event

    now = now or datetime.now(CN_TZ)
    overdue = list(
        (
            await db.execute(
                select(HardwareRequisition).where(
                    HardwareRequisition.req_type == "urgent",
                    HardwareRequisition.status == "issued",
                    HardwareRequisition.urgent_patch_deadline.isnot(None),
                    HardwareRequisition.urgent_patch_deadline < now,
                    HardwareRequisition.is_deleted.is_(False),
                )
            )
        ).scalars().all()
    )
    marked = 0
    for req in overdue:
        req.status = "overdue_unpatched"
        marked += 1
    if marked:
        await db.flush()
        try:
            await fire_push_event(
                db,
                "hardware_urgent_overdue",
                {
                    "count": marked,
                    "items": [
                        {"req_no": r.req_no, "dept": r.dept_name, "applicant": r.applicant}
                        for r in overdue[:10]
                    ],
                },
            )
        except Exception:  # noqa: BLE001
            logger.exception("紧急超期提醒推送失败（不影响标记主流程）")
    return {"checked": len(overdue), "marked": marked}


async def _run_scheduled_urgent_patch_check() -> None:
    """定时包装：独立会话自管提交（30 分钟一轮，覆盖 24h 窗口绰绰有余）。"""
    async with async_session_factory() as session:
        summary = await run_urgent_patch_check(session)
        await session.commit()
    if summary["marked"]:
        logger.warning("五金紧急补单超期已标记: %s", summary)


URGENT_PATCH_CHECK_TASK = TaskDefinition(
    name="warehouse.hardware_urgent_patch_check",
    schedule=ScheduleConfig(strategy=ScheduleStrategy.INTERVAL, interval_seconds=1800),
    coro=_run_scheduled_urgent_patch_check,
    timeout_seconds=300,
    module="warehouse",
)


async def _run_scheduled_approval_poll() -> None:
    """feishu 审批结果轮询兜底（15 分钟一轮；未配置通道时空转）。"""
    from app.modules.warehouse.hardware.approval_channel import poll_pending_approvals

    async with async_session_factory() as session:
        stats = await poll_pending_approvals(session)
        await session.commit()
    if stats.get("approved") or stats.get("rejected"):
        logger.info("五金领料审批轮询同步: %s", stats)


HARDWARE_APPROVAL_POLL_TASK = TaskDefinition(
    name="warehouse.hardware_approval_poll",
    schedule=ScheduleConfig(strategy=ScheduleStrategy.INTERVAL, interval_seconds=900),
    coro=_run_scheduled_approval_poll,
    timeout_seconds=300,
    module="warehouse",
)


async def _run_scheduled_monthly_plan() -> None:
    """每月 25 日 09:00 生成次月计划草案（P7 公式+AI 注释；同月幂等）。

    superagent hardware_plan_draft 执行器（M6）复用同一 service——
    SUPERAGENT_ENABLED=false 时本任务为主通道，功能不受损。
    """
    from app.modules.warehouse.hardware import planning as pl

    async with async_session_factory() as session:
        plan = await pl.generate_monthly_plan(session, pl.next_month())
        await session.commit()
    logger.info("五金月度计划草案已生成: %s", plan.plan_month)


HARDWARE_MONTHLY_PLAN_TASK = TaskDefinition(
    name="warehouse.hardware_monthly_plan",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.CRON,
        expression="0 9 25 * *",
        timezone="Asia/Shanghai",
    ),
    coro=_run_scheduled_monthly_plan,
    timeout_seconds=600,
    module="warehouse",
)


async def _run_scheduled_stale_scan() -> None:
    """每季首月 1 日 09:00 呆滞扫描（连续 91 天无 outbound 且有库存）→ 清单卡推送。"""
    from app.modules.warehouse.hardware import planning as pl
    from app.modules.warehouse.push_center.events import fire_push_event

    async with async_session_factory() as session:
        stale = await pl.scan_stale_materials(session)
        if stale:
            try:
                await fire_push_event(
                    session,
                    "hardware_stale_list",
                    {"count": len(stale), "items": stale[:20]},
                )
                await session.commit()
            except Exception:  # noqa: BLE001
                logger.exception("呆滞清单卡推送失败（不影响扫描）")
    if stale:
        logger.info("五金呆滞扫描: %d 项（清单卡已推送）", len(stale))


HARDWARE_STALE_SCAN_TASK = TaskDefinition(
    name="warehouse.hardware_stale_scan",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.CRON,
        expression="0 9 1 1,4,7,10 *",
        timezone="Asia/Shanghai",
    ),
    coro=_run_scheduled_stale_scan,
    timeout_seconds=600,
    module="warehouse",
)


async def _run_scheduled_env_remind() -> None:
    """每日 17:00 温湿度日检提醒（当天未填才推，幂等）。"""
    from app.modules.warehouse.hardware import planning as pl
    from app.modules.warehouse.hardware.models import HardwareEnvLog
    from app.modules.warehouse.push_center.events import fire_push_event

    today = datetime.now(CN_TZ).date()
    async with async_session_factory() as session:
        filled = await session.scalar(
            select(HardwareEnvLog.id).where(
                HardwareEnvLog.log_date == today,
                HardwareEnvLog.is_deleted.is_(False),
            )
        )
        if filled is None:
            try:
                await fire_push_event(
                    session,
                    "hardware_env_remind",
                    {"date": today.isoformat()},
                )
                await session.commit()
            except Exception:  # noqa: BLE001
                logger.exception("温湿度提醒推送失败")


HARDWARE_ENV_REMIND_TASK = TaskDefinition(
    name="warehouse.hardware_env_remind",
    # 2026-11-06 菜单改造：温湿度日检页面下线（/warehouse/hardware/daily 301），
    # 提醒卡片无落地页，任务随之停用；历史填报数据保留，恢复页面时改回 True 即可。
    enabled=False,
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.FIXED_TIME,
        time_of_day="17:00",
        timezone="Asia/Shanghai",
    ),
    coro=_run_scheduled_env_remind,
    timeout_seconds=120,
    module="warehouse",
)

_HARDWARE_TASKS = (
    URGENT_PATCH_CHECK_TASK,
    HARDWARE_APPROVAL_POLL_TASK,
    HARDWARE_MONTHLY_PLAN_TASK,
    HARDWARE_STALE_SCAN_TASK,
    HARDWARE_ENV_REMIND_TASK,
)


def register_hardware_tasks(registry) -> None:
    """main.py lifespan 一行注册（safety 批量注册同款）。

    M6 起一并挂 superagent 桥（kind/executor 注册幂等；SUPERAGENT_ENABLED
    总开关与 per-source enabled 沿用底座闸，默认 false）。
    """
    from app.modules.warehouse.hardware.superagent.bridge import (
        register_hardware_superagent,
    )

    register_hardware_superagent()
    for task in _HARDWARE_TASKS:
        registry.register_task(task)
