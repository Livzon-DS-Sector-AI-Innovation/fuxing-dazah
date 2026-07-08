"""Inspection route schedule generator — DB-driven dynamic task scanner."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.database import async_session_factory
from app.core.exceptions import AppException
from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.repository import inspection as inspection_repo
from app.modules.equipment.repository import work_order as work_order_repo
from app.modules.equipment.repository.inspection import get_due_schedules
from app.modules.equipment.service.inspection import (
    close_task,
    compute_next_cron,
    create_task,
    start_task,
)
from app.modules.equipment.service.work_order import close_work_order
from app.platform.identity.models import User
from app.platform.scheduler import (
    ScheduleConfig,
    ScheduleStrategy,
    TaskDefinition,
    TaskGenerator,
)

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))


class InspectionScheduleGenerator(TaskGenerator):
    """Scan inspection_route_schedules and auto-create/start tasks."""

    name = "equipment.inspection_schedules"
    schedule = ScheduleConfig(
        strategy=ScheduleStrategy.INTERVAL, interval_seconds=180,
    )

    async def find_due(self, session):
        return await get_due_schedules(session)

    async def execute_one(self, session, item) -> None:
        now = datetime.now(_CST)

        if not item.assigned_to:
            logger.warning(
                "Schedule route=%s has no assigned_to, skip", item.route_id,
            )
            return

        user_result = await session.execute(
            select(User).where(
                User.id == item.assigned_to,
                User.is_deleted == False,  # noqa: E712
            )
        )
        user = user_result.scalar_one_or_none()
        if user is None:
            logger.error(
                "Assigned user %s not found for schedule route=%s, skip",
                item.assigned_to, item.route_id,
            )
            return

        ctx = EquipmentAccessContext(
            user=user,
            data_scope="self_only",
            department_user_ids=[user.id],
        )

        task = await create_task(session, {
            "plan_type": "线路巡检",
            "route_id": str(item.route_id),
            "assigned_to": str(item.assigned_to),
            "planned_time": now,
        }, ctx)

        await start_task(session, task.id, ctx)

        item.last_triggered_at = now
        item.next_trigger_at = compute_next_cron(
            item.cron_expression, now,
        )

        logger.info(
            "Schedule triggered: route=%s task=%s",
            item.route_id, task.task_no,
        )


# ═══════════════════════════════════════════════════════════════
# Auto-close stale tasks and work orders (daily at 00:07)
# ═══════════════════════════════════════════════════════════════

async def _auto_close_stale() -> None:
    """Daily cleanup: archive completed tasks and work orders older than 3 days."""
    cutoff = datetime.now(_CST) - timedelta(days=3)

    async with async_session_factory() as session:
        # ── Inspection tasks ──
        stale_tasks = await inspection_repo.get_stale_completed_tasks(
            session, cutoff,
        )
        closed_tasks = 0
        skipped_tasks = 0
        for task in stale_tasks:
            try:
                await close_task(
                    session, task.id,
                    remark="系统自动归档（已完成超过3天）",
                    ctx=None,
                )
                closed_tasks += 1
            except AppException:
                skipped_tasks += 1
                logger.debug(
                    "Skip auto-close task %s: pending WOs or invalid state",
                    task.task_no,
                )
            except Exception:
                skipped_tasks += 1
                logger.exception(
                    "Failed to auto-close task %s", task.task_no,
                )

        # ── Work orders ──
        stale_wos = await work_order_repo.get_stale_completed_work_orders(
            session, cutoff,
        )
        closed_wos = 0
        skipped_wos = 0
        for wo in stale_wos:
            try:
                await close_work_order(session, wo.id, ctx=None)
                closed_wos += 1
            except AppException:
                skipped_wos += 1
                logger.debug(
                    "Skip auto-close WO %s: invalid state", wo.work_order_no,
                )
            except Exception:
                skipped_wos += 1
                logger.exception(
                    "Failed to auto-close WO %s", wo.work_order_no,
                )

        await session.commit()

    if closed_tasks or closed_wos or skipped_tasks or skipped_wos:
        logger.info(
            "Daily auto-close: tasks=%d/%d, WOs=%d/%d (closed/skipped)",
            closed_tasks, closed_tasks + skipped_tasks,
            closed_wos, closed_wos + skipped_wos,
        )


AUTO_CLOSE_TASK = TaskDefinition(
    name="equipment.auto_close_stale",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.CRON,
        expression="7 0 * * *",
        timezone="Asia/Shanghai",
    ),
    coro=_auto_close_stale,
    module="equipment",
)
