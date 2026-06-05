"""Background tasks: contact sync and timeout scanning."""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.modules.equipment.models.work_order import WorkOrder
from app.platform.integrations.feishu.contact import (
    get_department_leader,
    get_department_members,
)
from app.platform.integrations.feishu.message import send_timeout_notification

logger = logging.getLogger(__name__)
settings = get_settings()

stop_sync_flag = asyncio.Event()
stop_timeout_flag = asyncio.Event()


async def refresh_contact_cache() -> None:
    """全量刷新设备部通讯录缓存"""
    dept_id = settings.FEISHU_EQUIPMENT_DEPT_ID
    if not dept_id:
        logger.warning("FEISHU_EQUIPMENT_DEPT_ID not configured, skip sync")
        return

    try:
        await get_department_members(dept_id)
        await get_department_leader(dept_id)
        logger.info("Contact cache refreshed for dept %s", dept_id)
    except Exception:
        logger.exception("Failed to refresh contact cache")


async def contact_sync_loop() -> None:
    """每天凌晨刷新通讯录（每86400秒循环）"""
    while not stop_sync_flag.is_set():
        try:
            await asyncio.sleep(86400)
            if stop_sync_flag.is_set():
                break
            await refresh_contact_cache()
        except Exception:
            logger.exception("Contact sync error")


async def scan_timeout_work_orders() -> None:
    """扫描超时未接单的工单"""
    dept_id = settings.FEISHU_EQUIPMENT_DEPT_ID
    if not dept_id:
        return

    async with async_session_factory() as db:
        try:
            from app.modules.equipment.service.maintenance_config import (
                get_claim_timeout_config,
            )

            config = await get_claim_timeout_config(db)

            result = await db.execute(
                select(WorkOrder).where(
                    WorkOrder.status == "待处理",
                    WorkOrder.is_deleted == False,  # noqa: E712
                )
            )
            pending_orders = result.scalars().all()

            now = datetime.now(UTC)
            priority_map = {
                "紧急": "emergency",
                "高": "high",
                "中": "medium",
                "低": "low",
            }
            for order in pending_orders:
                attr = priority_map.get(order.priority, "medium")
                timeout_minutes = getattr(config, attr, 60)
                elapsed = (now - order.reported_at).total_seconds() / 60
                if elapsed > timeout_minutes:
                    leader = await get_department_leader(dept_id)
                    leader_name = leader.get("name", "主管") if leader else "主管"
                    await send_timeout_notification(
                        order.work_order_no,
                        "设备",
                        leader_name,
                    )
                    logger.info(
                        "Timeout work order %s notified (elapsed: %.0f min, timeout: %d min)",
                        order.work_order_no, elapsed, timeout_minutes,
                    )
        except Exception:
            logger.exception("Timeout scan error")
        finally:
            await db.rollback()


async def timeout_scan_loop() -> None:
    """每60秒扫描超时工单"""
    while not stop_timeout_flag.is_set():
        try:
            await scan_timeout_work_orders()
        except Exception:
            logger.exception("Timeout scan error")
        # 等待60秒，但可以被停止信号中断
        try:
            await asyncio.wait_for(stop_timeout_flag.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass
