"""Inspection route schedule generator — DB-driven dynamic task scanner."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.modules.equipment.repository.inspection import get_due_schedules
from app.modules.equipment.service.inspection import (
    compute_next_cron,
    create_task,
    start_task,
)
from app.platform.scheduler import ScheduleConfig, ScheduleStrategy, TaskGenerator

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))


class InspectionScheduleGenerator(TaskGenerator):
    """Scan inspection_route_schedules and auto-create/start tasks."""

    name = "equipment.inspection_schedules"
    schedule = ScheduleConfig(
        strategy=ScheduleStrategy.INTERVAL, interval_seconds=30,
    )

    async def find_due(self, session):
        return await get_due_schedules(session)

    async def execute_one(self, session, item) -> None:
        now = datetime.now(_CST)

        task = await create_task(session, {
            "plan_type": "线路巡检",
            "route_id": str(item.route_id),
            "assigned_to": (
                str(item.assigned_to)
                if item.assigned_to else None
            ),
            "planned_time": now,
        })

        await start_task(session, task.id)

        item.last_triggered_at = now
        item.next_trigger_at = compute_next_cron(
            item.cron_expression, now,
        )

        logger.info(
            "Schedule triggered: route=%s task=%s",
            item.route_id, task.task_no,
        )
