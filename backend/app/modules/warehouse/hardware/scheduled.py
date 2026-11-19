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

# 补办催办两档（tag, 提前量）：发料后剩 12h / 剩 2h（2026-11-19 拍板）
REMINDER_STAGES: tuple[tuple[str, timedelta], ...] = (
    ("t12", timedelta(hours=12)),
    ("t2", timedelta(hours=2)),
)


async def run_urgent_patch_check(db: AsyncSession, *, now: datetime | None = None) -> dict[str, int]:
    """紧急领用补办跟进（30 分钟一轮，全幂等）：

    ① T-12h/T-2h 催办申请人（patch_reminders 标签防重发，2026-11-19 拍板
       跟进节奏）；
    ② 逾期标记 overdue_unpatched（状态即幂等闸，同原逻辑）；
    ③ 逾期每日一次通报仓管通知目标直至补办（last_overdue_notified_at
       跨日才重发；仅通报不拦截——暂停与否仓储部线下决定）。
    """
    from app.modules.warehouse.hardware.models import HardwareRequisition
    from app.modules.warehouse.hardware.urgent_flow import send_patch_reminder
    from app.modules.warehouse.push_center.events import fire_push_event

    now = now or datetime.now(CN_TZ)

    # ① 提前催办：未逾期未补办的紧急单
    remind_rows = list(
        (
            await db.execute(
                select(HardwareRequisition).where(
                    HardwareRequisition.req_type == "urgent",
                    HardwareRequisition.status == "issued",
                    HardwareRequisition.urgent_patch_deadline.isnot(None),
                    HardwareRequisition.urgent_patch_deadline > now,
                    HardwareRequisition.patched_at.is_(None),
                    HardwareRequisition.is_deleted.is_(False),
                )
            )
        ).scalars().all()
    )
    reminded = 0
    for req in remind_rows:
        tags = list(req.patch_reminders or [])
        for tag, lead in REMINDER_STAGES:
            if tag in tags:
                continue
            if now >= req.urgent_patch_deadline - lead:
                await send_patch_reminder(req, deadline=req.urgent_patch_deadline, now=now)
                # 缺 open_id/发送失败同样记标签：防每轮重试刷屏（通报面在③兜底）
                tags.append(tag)
                reminded += 1
        if len(tags) != len(req.patch_reminders or []):
            req.patch_reminders = tags
    if reminded:
        await db.flush()

    # ② 逾期标记（issued → overdue_unpatched，一次性）
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

    # ③ 逾期每日通报：当日未通报过的 overdue_unpatched 单（含本轮新标记）
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    from sqlalchemy import or_

    to_report = list(
        (
            await db.execute(
                select(HardwareRequisition).where(
                    HardwareRequisition.req_type == "urgent",
                    HardwareRequisition.status == "overdue_unpatched",
                    HardwareRequisition.patched_at.is_(None),
                    HardwareRequisition.is_deleted.is_(False),
                    or_(
                        HardwareRequisition.last_overdue_notified_at.is_(None),
                        HardwareRequisition.last_overdue_notified_at < today_start,
                    ),
                )
            )
        ).scalars().all()
    )
    escalated = 0
    if to_report:
        try:
            await fire_push_event(
                db,
                "hardware_urgent_overdue",
                {
                    "count": len(to_report),
                    "items": [
                        {"req_no": r.req_no, "dept": r.dept_name, "applicant": r.applicant}
                        for r in to_report[:10]
                    ],
                },
            )
            for req in to_report:
                req.last_overdue_notified_at = now
            escalated = len(to_report)
            await db.flush()
        except Exception:  # noqa: BLE001
            logger.exception("紧急逾期通报推送失败（不影响标记主流程）")
    return {
        "reminded": reminded,
        "checked": len(overdue),
        "marked": marked,
        "escalated": escalated,
    }


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


async def _run_scheduled_approval_reconcile() -> None:
    """领/退料审批实例对账兜底：事件丢失补摄取 + pending 单状态对齐（幂等）。

    主通道是 approval.instance.* WS 事件（approval_ingest），本任务每小时扫
    近 2 小时实例防长连接断线漏单；HARDWARE_APPROVAL_CODE 未配置时自空转。
    """
    from app.modules.warehouse.hardware.approval_ingest import reconcile_recent_instances

    async with async_session_factory() as session:
        stats = await reconcile_recent_instances(session)
        await session.commit()
    if stats.get("enabled"):
        logger.info("五金领/退料审批对账: %s", stats)


HARDWARE_APPROVAL_RECONCILE_TASK = TaskDefinition(
    name="warehouse.hardware_approval_reconcile",
    schedule=ScheduleConfig(strategy=ScheduleStrategy.INTERVAL, interval_seconds=3600),
    coro=_run_scheduled_approval_reconcile,
    timeout_seconds=600,
    module="warehouse",
)


# 镜像任务节拍：dirty 三值快刷 5 分钟一轮；每 6 轮（≈30 分钟）插一次全量对账
_MIRROR_FULL_RECONCILE_EVERY = 6
_mirror_tick = 0


async def _run_scheduled_mirror_reconcile() -> None:
    """物资目录镜像同步（5 分钟）：清 dirty 三值队列；每 6 轮全量对账兜底。

    平台→Bitable 单向；软删/停用行的镜像清理由全量对账承担（无即时删钩子）。
    HARDWARE_MIRROR_BASE_TOKEN/TABLE_ID 清空或仓储凭证缺失时自空转。
    """
    global _mirror_tick
    from app.modules.warehouse.hardware import mirror_sync

    _mirror_tick += 1
    full = _mirror_tick % _MIRROR_FULL_RECONCILE_EVERY == 0
    stats: dict[str, int] = {}
    async with async_session_factory() as session:
        dirty = mirror_sync.take_dirty_ids()
        if dirty:
            refreshed = await mirror_sync.refresh_stock_values(session, sorted(dirty))
            if refreshed:
                logger.info("五金镜像三值已刷: %d 行", refreshed)
        if full:
            stats = await mirror_sync.reconcile_mirror(session)
            await session.commit()
    if stats.get("created") or stats.get("updated") or stats.get("deleted"):
        logger.info("五金物资目录镜像对账: %s", stats)


HARDWARE_MIRROR_RECONCILE_TASK = TaskDefinition(
    name="warehouse.hardware_mirror_reconcile",
    schedule=ScheduleConfig(strategy=ScheduleStrategy.INTERVAL, interval_seconds=300),
    coro=_run_scheduled_mirror_reconcile,
    timeout_seconds=600,
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

async def _run_scheduled_usage_sync() -> None:
    """每日 06:00 月度用量管控表回填（当月+上月，月初自然定格上月）。

    月需求量=物资清单基线，实际用量=领用出库流水聚合；行 upsert 幂等，
    处置状态/备注人工列不触碰。HARDWARE_USAGE_TABLE_ID 未配置自空转。
    """
    from app.modules.warehouse.hardware.usage_control import run_usage_sync

    await run_usage_sync()


HARDWARE_USAGE_SYNC_TASK = TaskDefinition(
    name="warehouse.hardware_usage_sync",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.FIXED_TIME,
        time_of_day="06:00",
        timezone="Asia/Shanghai",
    ),
    coro=_run_scheduled_usage_sync,
    timeout_seconds=600,
    module="warehouse",
)


_HARDWARE_TASKS = (
    URGENT_PATCH_CHECK_TASK,
    HARDWARE_APPROVAL_POLL_TASK,
    HARDWARE_APPROVAL_RECONCILE_TASK,
    HARDWARE_MIRROR_RECONCILE_TASK,
    HARDWARE_MONTHLY_PLAN_TASK,
    HARDWARE_STALE_SCAN_TASK,
    HARDWARE_ENV_REMIND_TASK,
    HARDWARE_USAGE_SYNC_TASK,
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
