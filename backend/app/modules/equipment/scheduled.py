"""Equipment scheduled tasks — 巡检任务生成器与静态定时任务。"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core import time as app_time
from app.core.config import get_settings
from app.core.database import async_session_factory
from app.core.exceptions import AppException
from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.models import Equipment, WorkOrder
from app.modules.equipment.repository import inspection as inspection_repo
from app.modules.equipment.repository import work_order as work_order_repo
from app.modules.equipment.repository.inspection import get_due_schedules
from app.modules.equipment.service.inspection import (
    close_task,
    compute_next_cron,
    create_task,
    start_task,
)
from app.modules.equipment.service.maintenance_config import (
    get_claim_timeout_config,
)
from app.modules.equipment.service.work_order import close_work_order
from app.platform.identity.models import User
from app.platform.integrations.feishu.contact import get_department_leader
from app.platform.integrations.feishu.message import send_timeout_notification
from app.platform.scheduler import (
    ScheduleConfig,
    ScheduleStrategy,
    TaskDefinition,
    TaskGenerator,
)

logger = logging.getLogger(__name__)
settings = get_settings()


class InspectionScheduleGenerator(TaskGenerator):
    """Scan inspection_route_schedules and auto-create/start tasks."""

    name = "equipment.inspection_schedules"
    schedule = ScheduleConfig(
        strategy=ScheduleStrategy.INTERVAL, interval_seconds=180,
    )

    async def find_due(self, session):
        return await get_due_schedules(session)

    async def execute_one(self, session, item) -> None:
        now = app_time.now()
        route_id = getattr(item, 'route_id', 'unknown')

        if not item.assigned_to:
            logger.warning(
                "Schedule route=%s has no assigned_to, skip", route_id,
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
                item.assigned_to, route_id,
            )
            return

        ctx = EquipmentAccessContext(
            user=user,
            data_scope="self_only",
            department_user_ids=[user.id],
        )

        try:
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
                route_id, task.task_no,
            )
        except Exception:
            logger.exception(
                "Schedule execute failed: route=%s assigned_to=%s",
                route_id, item.assigned_to,
            )
            raise


# ═══════════════════════════════════════════════════════════════
# Auto-close stale tasks and work orders (daily at 00:07)
# ═══════════════════════════════════════════════════════════════

async def _auto_close_stale() -> None:
    """Daily cleanup: archive completed tasks and work orders older than 3 days."""
    cutoff = app_time.now() - timedelta(days=3)

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
                await session.rollback()
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
                await session.rollback()
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


# 派单超时提醒冷却：任务 60s 一扫，同一工单 60 分钟内不重发，
# 否则会每分钟轰炸设备群。进程内存级，重启后冷却清空（最多多提醒一轮）。
_REMIND_COOLDOWN_SECONDS = 60 * 60
# 键为 (工单, 提醒原因)：同一张工单的「未指派」与「已指派未开工」是两阶段提醒，
# 共用一条冷却记录会让第二阶段被吞掉。
_last_reminded_at: dict[tuple[uuid.UUID, str], float] = {}


async def scan_timeout_work_orders() -> None:
    """扫描派单超时的待处理工单，通知设备主管。

    两类超时：未指派维修人超时（自报单时间起算）与已指派超时未开工
    （自指派时间起算）。阈值按优先级取 claim_timeout_* 配置（界面称
    「派单超时配置」）。原驻平台层 feishu/sync.py，迁入设备模块
    并挂到统一调度引擎。
    """
    dept_id = settings.FEISHU_EQUIPMENT_DEPT_ID
    if not dept_id:
        return

    async with async_session_factory() as db:
        try:
            config = await get_claim_timeout_config(db)
            result = await db.execute(
                select(WorkOrder, Equipment.name)
                .join(Equipment, WorkOrder.equipment_id == Equipment.id)
                .where(
                    WorkOrder.status == "待处理",
                    WorkOrder.is_deleted == False,  # noqa: E712
                )
            )
            pending_rows = result.all()

            now = datetime.now(UTC)
            now_mono = time.monotonic()
            priority_map = {
                "紧急": "emergency", "高": "high",
                "中": "medium", "低": "low",
            }
            leader = await get_department_leader(dept_id)
            leader_name = (
                leader.get("name", "主管") if leader else "主管"
            )

            pending_ids: set[tuple[uuid.UUID, str]] = set()
            for order, equipment_name in pending_rows:
                attr = priority_map.get(order.priority, "medium")
                timeout_minutes = getattr(config, attr, 60)

                if order.assignee_id is None:
                    anchor = order.reported_at
                    reason, action = "超时未指派维修人", "请及时指派"
                else:
                    anchor = order.assigned_at or order.reported_at
                    reason, action = "已指派超时未开工", "请及时跟进催办"

                pending_ids.add((order.id, reason))
                elapsed = (now - anchor).total_seconds() / 60
                if elapsed <= timeout_minutes:
                    continue
                # 哨兵用 None：time.monotonic() 是开机时长而非进程启动时长，
                # 用 0.0 当「从未提醒」会让重启后不足 1 小时的首次提醒被误判为冷却中
                last_reminded = _last_reminded_at.get((order.id, reason))
                if (
                    last_reminded is not None
                    and now_mono - last_reminded < _REMIND_COOLDOWN_SECONDS
                ):
                    continue

                await send_timeout_notification(
                    order.work_order_no, equipment_name, leader_name,
                    reason=reason, action=action,
                )
                _last_reminded_at[(order.id, reason)] = now_mono
                logger.info(
                    "Dispatch timeout WO %s (%.0f min > %d min, %s)",
                    order.work_order_no, elapsed, timeout_minutes, reason,
                )

            # 清理已离开待处理状态的冷却记录，避免长期驻留
            for key in set(_last_reminded_at) - pending_ids:
                _last_reminded_at.pop(key, None)
        except Exception:
            logger.exception("Dispatch timeout scan error")
        finally:
            await db.rollback()


TIMEOUT_SCAN_TASK = TaskDefinition(
    name="equipment.scan_timeout_work_orders",
    schedule=ScheduleConfig(
        strategy=ScheduleStrategy.INTERVAL, interval_seconds=60,
    ),
    coro=scan_timeout_work_orders,
    module="equipment",
)
