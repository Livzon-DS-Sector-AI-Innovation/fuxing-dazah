"""五金库定时任务（M3：紧急领用 24h 补单提醒；feishu 审批结果轮询兜底）。

TaskDefinition 模式照 warehouse/scheduled.py；main.py lifespan 注册。
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

_HARDWARE_TASKS = (URGENT_PATCH_CHECK_TASK, HARDWARE_APPROVAL_POLL_TASK)


def register_hardware_tasks(registry) -> None:
    """main.py lifespan 一行注册（safety 批量注册同款）。"""
    for task in _HARDWARE_TASKS:
        registry.register_task(task)
