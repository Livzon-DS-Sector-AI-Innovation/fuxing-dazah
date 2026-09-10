"""关键风险作业 Bitable 事件处理器。

监听「每日关键风险操作预报备（审批）」变更事件，实时同步到 KeyRiskOperationReport。
和特殊作业 handler 一致，仅依赖 @on_event + WebSocket，无需 Drive 订阅 API。
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.feishu.event_client import on_event
from app.modules.safety.service.key_risk_operation_report import (
    APPLY_STATUS_DELETED,
    KeyRiskOperationReportService,
    bitable_app_token,
    bitable_table_id,
)

logger = logging.getLogger(__name__)


@on_event("drive.file.bitable_record_changed_v1")
async def handle_key_risk_op_record_changed(event: dict) -> None:
    """处理关键风险作业 Bitable 记录变更事件（仅同步数据，不触发审批/通知）。"""
    header = event.get("header", {})
    event_type = header.get("event_type", "")

    event_data = event.get("event", {})
    file_token = event_data.get("file_token", "")
    table_id = event_data.get("table_id", "")

    # 过滤：仅处理目标 Bitable
    if (
        file_token != bitable_app_token()
        or table_id != bitable_table_id()
    ):
        return

    record_id = event_data.get("record_id", "")
    if not record_id:
        return

    logger.info("关键风险作业 Bitable 事件: type=%s record_id=%s", event_type, record_id)

    try:
        if "deleted" in event_type:
            await _handle_delete(record_id)
        else:
            await _handle_upsert(record_id)
    except Exception:
        logger.exception("处理关键风险作业 Bitable 事件失败: record_id=%s", record_id)


async def _handle_upsert(record_id: str) -> None:
    """从 Bitable 读取记录并 upsert 到 KeyRiskOperationReport。"""
    from app.core.database import async_session_factory
    from app.modules.safety.models import KeyRiskOperationReport

    client = SafetyBitableClient(
        app_token=bitable_app_token(), table_id=bitable_table_id()
    )
    fields = await client.get_record(record_id)
    if not fields:
        logger.warning("Bitable 记录读取为空: record_id=%s", record_id)
        return

    # 「已删除」状态 → 软删除
    from app.modules.safety.service.key_risk_operation_report import _name_of

    if _name_of(fields.get("申请状态")) == APPLY_STATUS_DELETED:
        await _handle_delete(record_id)
        return

    mapped = KeyRiskOperationReportService.map_bitable_fields(fields)
    mapped["feishu_record_id"] = record_id
    if not mapped.get("report_no"):
        mapped["report_no"] = f"BT-{record_id[-12:]}"

    async with async_session_factory() as session:
        from app.modules.safety.feishu.bitable_handler import acquire_record_lock

        # DB 级并发互斥：显式事务 + 事务级咨询锁（2026-09-08 补齐，见 acquire_record_lock）
        async with session.begin():
            await acquire_record_lock(session, record_id)
            stmt = select(KeyRiskOperationReport).where(
                KeyRiskOperationReport.feishu_record_id == record_id,
                KeyRiskOperationReport.source == "bitable",
                KeyRiskOperationReport.is_deleted == False,  # noqa: E712
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                for k, v in mapped.items():
                    if v is not None and k not in ("report_no", "source"):
                        setattr(existing, k, v)
            else:
                existing = KeyRiskOperationReport(**mapped)
                session.add(existing)

        logger.info("关键风险作业记录已同步: record_id=%s", record_id)


async def _handle_delete(record_id: str) -> None:
    """软删除对应的 KeyRiskOperationReport 记录。"""
    from sqlalchemy import update

    from app.core.database import async_session_factory
    from app.modules.safety.models import KeyRiskOperationReport

    async with async_session_factory() as session:
        await session.execute(
            update(KeyRiskOperationReport)
            .where(KeyRiskOperationReport.feishu_record_id == record_id,
                   KeyRiskOperationReport.source == "bitable",
                   KeyRiskOperationReport.is_deleted == False)  # noqa: E712
            .values(is_deleted=True)
        )
        await session.commit()
        logger.info("关键风险作业记录已软删除: record_id=%s", record_id)


async def ensure_key_risk_op_bitable_subscribed() -> bool:
    """订阅关键风险作业多维表格云文档事件（飞书要求先订阅才能收到 Bitable 事件）。

    实时同步前置条件：WebSocket 长连接只会推送「已订阅文档」的变更事件，
    未订阅的文档（app_token）不会推送 drive.file.bitable_record_changed_v1。
    """
    try:
        import httpx

        from app.modules.safety.feishu.client import get_safety_tenant_token

        token = await get_safety_tenant_token()
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                f"https://open.feishu.cn/open-apis/drive/v1/files/{bitable_app_token()}/subscribe",
                headers={"Authorization": f"Bearer {token}"},
                params={"file_type": "bitable"},
            )
            data = resp.json()
            if data.get("code") == 0:
                logger.info(
                    "关键风险作业 Bitable 文档事件订阅成功: file_token=%s",
                    bitable_app_token(),
                )
                return True
            logger.error(
                "关键风险作业 Bitable 文档事件订阅失败: code=%s msg=%s",
                data.get("code"), data.get("msg"),
            )
            return False
    except Exception:
        logger.exception("关键风险作业 Bitable 文档事件订阅异常")
        return False
