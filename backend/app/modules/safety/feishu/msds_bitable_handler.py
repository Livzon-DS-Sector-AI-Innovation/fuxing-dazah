"""MSDS — 「MSDS」表 Bitable 事件处理器（台账镜像）。

MSDS 表（标准化收录台账）新增/变更/删除 → 镜像到 msds_documents。
平台写回创建的记录（create_record）也会触发本 handler 同步（幂等）。

字段映射：MSDS 表 29 列 → msds_documents 列（label_elements 仅平台存档，MSDS 表无该字段）。

事件类型（2026-09-08 修正）：bitable.record.*_v1 飞书从不推送（3000+ 条真实
事件实测 0 次），已迁移文档级 drive.file.bitable_record_changed_v1（本文件
ensure_msds_bitable_subscribed 完成文档订阅，单 base 订阅覆盖采集表 + 台账表）。
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select, update

from app.core.database import async_session_factory
from app.modules.safety.bitable_config.store import ConnectionView, store
from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.feishu.event_client import on_event
from app.modules.safety.models import MsdsDocument

logger = logging.getLogger(__name__)


def _msds_conn() -> ConnectionView | None:
    """MSDS 收录台账连接视图（store：DB 活行 → registry 默认）。"""
    return store.get_connection("msds", "registry")


def _get_msds_app_token() -> str:
    conn = _msds_conn()
    return conn.app_token if conn and conn.status != "disabled" else ""


def _get_msds_table_id() -> str:
    conn = _msds_conn()
    return conn.table_id if conn and conn.status != "disabled" else ""


# Bitable 中文字段名 → msds_documents 列
BITABLE_TO_MODEL: dict[str, str] = {
    "物质名称": "name",
    "CAS号": "cas_no",
    "分子式": "molecular_formula",
    "UN编号": "un_no",
    "日期": "source_date",
    "危险性说明": "hazard_statement",
    "外观与现状": "appearance",
    "溶解性": "solubility",
    "熔点": "melting_point",
    "沸点": "boiling_point",
    "闪点": "flash_point",
    "相对密度": "relative_density",
    "爆炸上限": "explosion_upper_limit",
    "爆炸下限": "explosion_lower_limit",
    "自燃温度": "autoignition_temperature",
    "分解温度": "decomposition_temperature",
    "PC-TWA": "pc_twa",
    "PC-STEL": "pc_stel",
    "MAC": "mac",
    "健康危害": "health_hazard",
    "环境危害": "environmental_hazard",
    "急救措施": "first_aid",
    "消防措施": "fire_fighting",
    "泄漏应急处理": "leakage_response",
    "废弃处置": "waste_disposal",
    "接触控制与个体防护": "exposure_controls",
    "操作处置与储存注意事项": "handling_storage",
    "稳定性和反应性": "stability_reactivity",
    "MSDS附件": "msds_attachment",
}


# ── 值提取 ──


def _text(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None


def _date_from_raw(raw: Any) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw.strip()[:10])
        except (ValueError, TypeError):
            return None
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(raw / 1000, tz=UTC).date()
        except (OSError, ValueError):
            return None
    return None


def _attachments(raw: Any) -> list | None:
    if not raw or not isinstance(raw, list):
        return None
    metas = []
    for item in raw:
        if isinstance(item, dict):
            metas.append({
                "name": item.get("name", ""),
                "file_token": item.get("file_token", ""),
                "url": item.get("url", ""),
                "tmp_url": item.get("tmp_url", ""),
            })
    return metas or None


def _map_fields(values: dict) -> dict[str, Any]:
    """MSDS 表字段 → msds_documents 列值。"""
    mapped: dict[str, Any] = {}
    for bitable_field, model_col in BITABLE_TO_MODEL.items():
        raw = values.get(bitable_field)
        if model_col == "source_date":
            mapped[model_col] = _date_from_raw(raw)
        elif model_col == "msds_attachment":
            mapped[model_col] = _attachments(raw)
        else:
            mapped[model_col] = _text(raw)
    return {k: v for k, v in mapped.items() if v is not None}


# ── 事件处理 ──


async def _handle_created(event_data: dict) -> None:
    record_id = event_data.get("record_id", "")
    if not record_id:
        return
    logger.info("MSDS 表记录创建: record_id=%s", record_id)
    try:
        async with async_session_factory() as session:
            existing = await session.scalar(
                select(MsdsDocument).where(
                    MsdsDocument.feishu_record_id == record_id,
                    MsdsDocument.is_deleted == False,  # noqa: E712
                )
            )
            if existing:
                logger.info("MSDS 镜像已存在，跳过: %s", record_id)
                return

        app_token = _get_msds_app_token()
        table_id = _get_msds_table_id()
        if not app_token or not table_id:
            logger.warning("MSDS 表未配置，跳过镜像: %s", record_id)
            return

        client = SafetyBitableClient(app_token=app_token, table_id=table_id)
        record = await client.get_record(record_id=record_id)
        mapped = _map_fields(record if isinstance(record, dict) else {})
        mapped["feishu_record_id"] = record_id

        async with async_session_factory() as session:
            from app.modules.safety.feishu.bitable_handler import acquire_record_lock

            # DB 级并发互斥：显式事务 + 事务级咨询锁（2026-09-08 补齐，见 acquire_record_lock）
            async with session.begin():
                await acquire_record_lock(session, record_id)
                # 锁后复查：并发创建已被另一事件完成时跳过
                existing = await session.scalar(
                    select(MsdsDocument).where(
                        MsdsDocument.feishu_record_id == record_id,
                        MsdsDocument.is_deleted == False,  # noqa: E712
                    )
                )
                if existing:
                    obj = existing
                else:
                    obj = MsdsDocument(**mapped)
                    session.add(obj)
                    await session.flush()
            logger.info("MSDS 镜像同步: record_id=%s db_id=%s", record_id, obj.id)

        # 同步知识库索引（幂等；失败仅记日志）
        try:
            from app.modules.safety.knowledge.msds_indexer import (
                sync_msds_document_to_knowledge,
            )

            await sync_msds_document_to_knowledge(obj.id)
        except Exception:
            logger.exception("MSDS 镜像→知识索引同步失败: record_id=%s", record_id)
    except Exception:
        logger.exception("MSDS 镜像创建失败: %s", record_id)


async def _handle_changed(event_data: dict) -> None:
    record_id = event_data.get("record_id", "")
    if not record_id:
        return
    logger.info("MSDS 表记录变更: record_id=%s", record_id)
    try:
        app_token = _get_msds_app_token()
        table_id = _get_msds_table_id()
        if not app_token or not table_id:
            return

        client = SafetyBitableClient(app_token=app_token, table_id=table_id)
        record = await client.get_record(record_id=record_id)
        mapped = _map_fields(record if isinstance(record, dict) else {})
        if not mapped:
            return

        async with async_session_factory() as session:
            from app.modules.safety.feishu.bitable_handler import acquire_record_lock

            # DB 级并发互斥：显式事务 + 事务级咨询锁（2026-09-08 补齐，见 acquire_record_lock）
            async with session.begin():
                await acquire_record_lock(session, record_id)
                existing = await session.scalar(
                    select(MsdsDocument).where(
                        MsdsDocument.feishu_record_id == record_id,
                        MsdsDocument.is_deleted == False,  # noqa: E712
                    )
                )
                if existing:
                    for col, val in mapped.items():
                        setattr(existing, col, val)
                    logger.info("MSDS 镜像更新: record_id=%s fields=%s", record_id, list(mapped.keys()))
                    doc_id = existing.id
                else:
                    mapped["feishu_record_id"] = record_id
                    session.add(MsdsDocument(**mapped))
                    logger.info("MSDS 镜像新增(变更触发): record_id=%s", record_id)
                    doc_id = None  # 新增由 created 事件/写回管线负责索引

        # 同步知识库索引（幂等；失败仅记日志）
        if doc_id:
            try:
                from app.modules.safety.knowledge.msds_indexer import (
                    sync_msds_document_to_knowledge,
                )

                await sync_msds_document_to_knowledge(doc_id)
            except Exception:
                logger.exception("MSDS 镜像→知识索引同步失败: record_id=%s", record_id)
    except Exception:
        logger.exception("MSDS 镜像变更失败: %s", record_id)


async def _handle_deleted(event_data: dict) -> None:
    record_id = event_data.get("record_id", "")
    if not record_id:
        return
    try:
        async with async_session_factory() as session:
            await session.execute(
                update(MsdsDocument)
                .where(
                    MsdsDocument.feishu_record_id == record_id,
                    MsdsDocument.is_deleted == False,  # noqa: E712
                )
                .values(is_deleted=True)
            )
            await session.commit()
            logger.info("MSDS 镜像软删除: %s", record_id)

        # 同步移除知识库索引（幂等；失败仅记日志）
        try:
            from app.modules.safety.knowledge.msds_indexer import (
                remove_msds_from_knowledge,
            )

            async with async_session_factory() as session:
                doc = await session.scalar(
                    select(MsdsDocument).where(
                        MsdsDocument.feishu_record_id == record_id,
                    )
                )
                if doc:
                    await remove_msds_from_knowledge(doc.id, session=session)
                    await session.commit()
        except Exception:
            logger.exception("MSDS 删除→知识索引移除失败: record_id=%s", record_id)
    except Exception:
        logger.exception("MSDS 镜像软删除失败: %s", record_id)


# ── 事件注册 ──


@on_event("drive.file.bitable_record_changed_v1")
async def _on_msds_drive_changed(event: dict) -> None:
    """文档级记录变更事件：按 app_token + table_id 过滤后逐条分派。

    action_list 每项仅含 record_id/action，_handle_* 内部回源 get_record，
    此处只构造最小 event_data。
    """
    if event.get("file_token", "") != _get_msds_app_token():
        return
    table_id = event.get("table_id", "")
    if table_id != _get_msds_table_id():
        return

    action_list = event.get("action_list") or []
    if not action_list:  # 兼容无 action_list 的旧 flat 格式
        record_id = event.get("record_id", "")
        if not record_id:
            return
        action_list = [
            {"record_id": record_id, "action": event.get("action", "record_edited")}
        ]

    for item in action_list:
        record_id = item.get("record_id", "")
        action = item.get("action", "")
        if not record_id:
            continue
        event_data = {"record_id": record_id, "table_id": table_id}
        try:
            if action == "record_deleted":
                await _handle_deleted(event_data)
            elif action == "record_added":
                await _handle_created(event_data)
            else:  # record_edited 及未知动作
                await _handle_changed(event_data)
        except Exception:
            logger.exception(
                "MSDS 台账 drive 事件处理失败: record_id=%s action=%s", record_id, action
            )


async def ensure_msds_bitable_subscribed() -> bool:
    """订阅 MSDS Base 文档事件（drive.file.bitable_record_changed_v1 前置）。

    飞书要求：接收文档级 Bitable 事件前，须先调用 /drive/v1/files/:file_token/subscribe。
    订阅持久存在于飞书侧，每次启动重试无害。单 base 订阅同时覆盖采集表与台账表。
    订阅成功与否不影响 handler 注册；失败时由重启/配置变更重试兜底。
    """
    import httpx

    # registry/ collection 任一连接可用即订阅（同 base，两表共用）
    file_token = _get_msds_app_token()
    if not file_token:
        coll_conn = store.get_connection("msds", "collection")
        if coll_conn and coll_conn.status != "disabled":
            file_token = coll_conn.app_token
    if not file_token:
        logger.info("MSDS Bitable app_token 未配置，跳过文档事件订阅")
        return False

    import os

    app_id = os.getenv("SAFETY_FEISHU_APP_ID", "")
    app_secret = os.getenv("SAFETY_FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        logger.warning("飞书应用凭证未配置，跳过 MSDS 文档事件订阅")
        return False

    try:
        async with httpx.AsyncClient(timeout=15) as http:
            auth_resp = await http.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
            )
            auth_data = auth_resp.json()
            if auth_data.get("code") != 0:
                logger.error(
                    "获取 tenant_access_token 失败: code=%s msg=%s",
                    auth_data.get("code"), auth_data.get("msg"),
                )
                return False
            token = auth_data["tenant_access_token"]

            resp = await http.post(
                f"https://open.feishu.cn/open-apis/drive/v1/files/{file_token}/subscribe",
                headers={"Authorization": f"Bearer {token}"},
                params={"file_type": "bitable"},
            )
            data = resp.json()
            if data.get("code") == 0:
                logger.info("MSDS Bitable 文档事件订阅成功: file_token=%s", file_token)
                return True
            logger.error(
                "MSDS Bitable 文档事件订阅失败: code=%s msg=%s file_token=%s",
                data.get("code"), data.get("msg"), file_token,
            )
            return False
    except Exception:
        logger.exception("MSDS Bitable 文档事件订阅异常: file_token=%s", file_token)
        return False
