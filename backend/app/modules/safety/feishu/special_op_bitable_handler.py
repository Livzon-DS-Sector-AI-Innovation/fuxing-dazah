"""特殊作业日报 Bitable 事件处理器。

监听「全厂特殊作业一览表」变更事件，实时同步到 SpecialOperationReport。
和演练 handler 一致，仅依赖 @on_event + WebSocket，无需 Drive 订阅 API。
连接配置从配置中心 store 读取（原代码硬编码 app_token/table_id）。
"""

from __future__ import annotations

import logging

from app.modules.safety.bitable_config.store import ConnectionView, store
from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.feishu.event_client import on_event

logger = logging.getLogger(__name__)


def _special_op_conn() -> ConnectionView | None:
    """特殊作业日报连接配置（配置中心 store 读取；未启用/缺失返回 None）。"""
    return store.get_connection("special_op", "daily")


def _special_op_app_token() -> str:
    conn = _special_op_conn()
    return conn.app_token if conn and conn.enabled else ""


def _special_op_table_id() -> str:
    conn = _special_op_conn()
    return conn.table_id if conn and conn.enabled else ""


@on_event("drive.file.bitable_record_changed_v1")
async def handle_special_ops_record_changed(event: dict) -> None:
    """处理特殊作业 Bitable 记录变更事件（v2 action_list 格式，兼容 flat 兜底）。

    仅同步数据（upsert/delete），不触发日报生成。
    日报生成由定时任务（08:00/19:00）和手动触发负责。

    飞书 v2 payload（dispatch 已剥离信封，handler 直接收到内层数据）：
    {
        "file_token": "<app_token>", "table_id": "tblxxx",
        "action_list": [
            {"action": "record_added|record_edited|record_deleted", "record_id": "recxxx", ...}
        ]
    }
    """
    file_token = event.get("file_token", "")
    table_id = event.get("table_id", "")

    # 过滤：仅处理目标 Bitable（防串表）
    if (
        file_token != _special_op_app_token()
        or table_id != _special_op_table_id()
    ):
        logger.debug("忽略非目标表事件: file_token=%s table_id=%s", file_token, table_id)
        return

    # ── v2 action_list 格式 ──
    action_list = event.get("action_list") or []
    if action_list:
        for item in action_list:
            record_id = item.get("record_id", "")
            action = item.get("action", "")
            if not record_id:
                logger.warning("特殊作业 action_list 项缺少 record_id: action=%s", action)
                continue
            logger.info("特殊作业 Bitable 事件: action=%s record_id=%s", action, record_id)
            try:
                if action == "record_deleted":
                    await _handle_delete(record_id)
                else:
                    await _handle_upsert(record_id)
            except Exception:
                logger.exception("处理特殊作业 Bitable 事件失败: record_id=%s", record_id)
        return

    # ── 兼容旧 flat 格式 ──
    record_id = event.get("record_id", "")
    if not record_id:
        return
    action = event.get("action", "")
    logger.info("特殊作业 Bitable 事件(flat): action=%s record_id=%s", action, record_id)
    try:
        if action == "record_deleted":
            await _handle_delete(record_id)
        else:
            await _handle_upsert(record_id)
    except Exception:
        logger.exception("处理特殊作业 Bitable 事件失败: record_id=%s", record_id)


async def _handle_upsert(record_id: str) -> None:
    """从 Bitable 读取记录并 upsert 到 SpecialOperationReport。"""
    from app.core.database import async_session_factory
    from app.modules.safety.service.special_operation_daily_report import (
        RiskAssessmentEngine,
        SpecialOperationDailyReportService,
    )

    client = SafetyBitableClient(
        app_token=_special_op_app_token(), table_id=_special_op_table_id()
    )
    fields = await client.get_record(record_id)
    if not fields:
        logger.warning("Bitable 记录读取为空: record_id=%s", record_id)
        return

    mapped = SpecialOperationDailyReportService.map_bitable_fields(fields)
    mapped["feishu_record_id"] = record_id
    mapped["report_no"] = f"BT-{record_id[-12:]}"  # 确保唯一
    engine = RiskAssessmentEngine()

    async with async_session_factory() as session:
        from sqlalchemy import select

        from app.modules.safety.feishu.bitable_handler import acquire_record_lock
        from app.modules.safety.models import SpecialOperationReport

        # DB 级并发互斥：显式事务 + 事务级咨询锁（2026-09-08 补齐，见 acquire_record_lock）
        async with session.begin():
            await acquire_record_lock(session, record_id)
            stmt = select(SpecialOperationReport).where(
                SpecialOperationReport.feishu_record_id == record_id,
                SpecialOperationReport.source == "bitable",
                SpecialOperationReport.is_deleted == False,  # noqa: E712
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                for k, v in mapped.items():
                    if v is not None and k not in ("report_no", "status"):
                        setattr(existing, k, v)
            else:
                existing = SpecialOperationReport(**mapped)
                session.add(existing)

            assessment = engine.assess(existing)
            existing.daily_risk_level = assessment.risk_level
            existing.daily_risk_reason = "; ".join(assessment.matched_rules) if assessment.matched_rules else None
            existing.inferred_operation_types = assessment.inferred_types if assessment.inferred_types else None
            existing.is_excluded = assessment.is_excluded
            existing.exclusion_reason = assessment.exclusion_reason

        logger.info("特殊作业记录已同步: record_id=%s", record_id)


async def _handle_delete(record_id: str) -> None:
    """软删除对应的 SpecialOperationReport 记录。"""
    from sqlalchemy import update

    from app.core.database import async_session_factory
    from app.modules.safety.models import SpecialOperationReport

    async with async_session_factory() as session:
        await session.execute(
            update(SpecialOperationReport)
            .where(SpecialOperationReport.feishu_record_id == record_id,
                   SpecialOperationReport.source == "bitable")
            .values(is_deleted=True)
        )
        await session.commit()
        logger.info("特殊作业记录已软删除: record_id=%s", record_id)


async def ensure_special_op_bitable_subscribed() -> bool:
    """订阅特殊作业多维表格云文档事件（飞书要求先订阅才能收到 Bitable 事件）。

    实时同步前置条件：WebSocket 长连接只会推送「已订阅文档」的变更事件，
    未订阅的文档（app_token）不会推送 drive.file.bitable_record_changed_v1。
    """
    try:
        import httpx

        from app.modules.safety.feishu.client import get_safety_tenant_token

        token = await get_safety_tenant_token()
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                f"https://open.feishu.cn/open-apis/drive/v1/files/{_special_op_app_token()}/subscribe",
                headers={"Authorization": f"Bearer {token}"},
                params={"file_type": "bitable"},
            )
            data = resp.json()
            if data.get("code") == 0:
                logger.info(
                    "特殊作业 Bitable 文档事件订阅成功: file_token=%s",
                    _special_op_app_token(),
                )
                return True
            logger.error(
                "特殊作业 Bitable 文档事件订阅失败: code=%s msg=%s",
                data.get("code"), data.get("msg"),
            )
            return False
    except Exception:
        logger.exception("特殊作业 Bitable 文档事件订阅异常")
        return False
