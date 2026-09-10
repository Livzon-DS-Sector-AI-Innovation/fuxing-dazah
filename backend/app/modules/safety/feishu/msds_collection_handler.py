"""MSDS — 「供应商资料」Bitable 事件处理器（采集入口）。

供应商/安全员在「供应商资料」表中上传原始 MSDS 文档（附件），
平台自动：同步 → 下载附件 → AI 提取 28 字段【数组】（按化学品拆分）→ 落库。

数据流：
  供应商资料表 created/changed → 同步 msds_collection_records（pending）
    → 有附件则 asyncio.create_task 触发 MsdsService.run_parse
    → parse_result 落库（parsed/failed）
  写回 MSDS 表记录在 Ticket 03（_create_registry_entries）。

防重：Redis 60s 去重窗口；附件变更时重置 pending 重新解析。

事件类型（2026-09-08 修正）：bitable.record.*_v1 飞书从不推送（3000+ 条真实
事件实测 0 次），已迁移文档级 drive.file.bitable_record_changed_v1
（文档订阅由 msds_bitable_handler.ensure_msds_bitable_subscribed 完成）。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select

from app.core.database import async_session_factory
from app.core.redis import redis_client
from app.modules.safety.bitable_config.store import ConnectionView, store
from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.feishu.event_client import on_event
from app.modules.safety.models import MsdsCollectionRecord

logger = logging.getLogger(__name__)


def _msds_collection_conn() -> ConnectionView | None:
    """MSDS 采集入口连接视图（store：DB 活行 → registry 默认）。"""
    return store.get_connection("msds", "collection")


def _get_collection_app_token() -> str:
    conn = _msds_collection_conn()
    return conn.app_token if conn and conn.status != "disabled" else ""


def _get_collection_table_id() -> str:
    conn = _msds_collection_conn()
    return conn.table_id if conn and conn.status != "disabled" else ""


# ── 值提取 ──


def _extract_date(raw: Any) -> date | None:
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


def _extract_attachment_meta(raw: Any) -> list | None:
    if not raw or not isinstance(raw, list):
        return None
    metas = []
    for item in raw:
        if isinstance(item, dict):
            metas.append({
                "name": item.get("name", ""),
                "file_token": item.get("file_token", ""),
                "size": item.get("size"),
                "type": item.get("type"),
                "url": item.get("url", ""),
                "tmp_url": item.get("tmp_url", ""),
            })
    return metas or None


def _extract_person(raw: Any) -> list | None:
    if not raw or not isinstance(raw, list):
        return None
    persons = []
    for item in raw:
        if isinstance(item, dict):
            persons.append({
                "open_id": item.get("id", ""),
                "name": item.get("name", ""),
                "email": item.get("email", ""),
            })
    return persons or None


def _first_file_token(attachment: Any) -> str:
    if not attachment or not isinstance(attachment, list):
        return ""
    first = attachment[0]
    return first.get("file_token", "") if isinstance(first, dict) else ""


# ── PG 同步 ──


async def _sync_collection_to_pg(
    feishu_record_id: str,
    record: dict,
    *,
    force_pending: bool = False,
) -> uuid.UUID | None:
    """同步供应商资料记录到 PostgreSQL，返回采集记录 id。"""
    try:
        from app.modules.safety.feishu.bitable_handler import acquire_record_lock

        async with async_session_factory() as session:
            # DB 级并发互斥：显式事务 + 事务级咨询锁（2026-09-08 补齐，见 acquire_record_lock）
            async with session.begin():
                await acquire_record_lock(session, feishu_record_id)
                existing = await session.scalar(
                    select(MsdsCollectionRecord).where(
                        MsdsCollectionRecord.feishu_record_id == feishu_record_id,
                        MsdsCollectionRecord.is_deleted == False,  # noqa: E712
                    )
                )
                attachment = _extract_attachment_meta(record.get("供应商资料"))
                new_token = _first_file_token(attachment)

                if existing:
                    # 附件变更 → 重置 pending 重新解析
                    if force_pending or (
                        new_token and _first_file_token(existing.attachment) != new_token
                    ):
                        existing.parse_status = "pending"
                        existing.parse_error = None
                    existing.source_date = _extract_date(record.get("日期")) or existing.source_date
                    existing.person_data = _extract_person(record.get("人员")) or existing.person_data
                    if attachment:
                        existing.attachment = attachment
                    return existing.id

                obj = MsdsCollectionRecord(
                    feishu_record_id=feishu_record_id,
                    source_date=_extract_date(record.get("日期")),
                    attachment=attachment,
                    person_data=_extract_person(record.get("人员")),
                    parse_status="pending",
                )
                session.add(obj)
                await session.flush()
                logger.info("MSDS 采集同步: %s → db_id=%s", feishu_record_id, obj.id)
                return obj.id
    except Exception:
        logger.exception("MSDS 采集 PG 同步失败: %s", feishu_record_id)
        return None


async def _run_parse_task(pg_collection_id) -> None:
    """后台任务：独立 session 执行完整管线（解析 + 自动写回 MSDS 表，不阻塞事件回调）。"""
    try:
        async with async_session_factory() as session:
            from app.modules.safety.service.msds import MsdsService

            service = MsdsService(session)
            rec = await service.process_collection(pg_collection_id)
            if rec:
                logger.info(
                    "MSDS 采集处理完成: collection=%s status=%s entries=%d registry=%d",
                    pg_collection_id, rec.parse_status,
                    len(rec.parse_result) if rec.parse_result else 0,
                    len(rec.msds_table_record_ids) if rec.msds_table_record_ids else 0,
                )
            else:
                logger.warning("MSDS 采集对象不存在: collection=%s", pg_collection_id)
    except Exception:
        logger.exception("MSDS 采集后台任务异常: collection=%s", pg_collection_id)


def _schedule_parse(pg_collection_id) -> None:
    """调度解析任务（事件循环运行时创建后台任务）。"""
    try:
        asyncio.get_running_loop().create_task(_run_parse_task(pg_collection_id))
    except RuntimeError:
        logger.warning("无运行中的事件循环，解析任务不调度: collection=%s", pg_collection_id)


# ── 事件处理 ──


async def _handle_record(event_data: dict) -> None:
    feishu_record_id = event_data.get("record_id", "")
    if not feishu_record_id:
        return

    collection_table_id = _get_collection_table_id()
    app_token = _get_collection_app_token()
    if not collection_table_id or not app_token:
        logger.warning("MSDS 采集表未配置, 跳过: record=%s", feishu_record_id)
        return

    # Redis 60s 去重窗口
    dedup_key = f"msds_collect_event_{feishu_record_id}"
    try:
        acquired = await redis_client.set(dedup_key, "1", ex=60, nx=True)
        if not acquired:
            return
    except Exception:
        logger.debug("Redis 不可用, 跳过去重: %s", feishu_record_id)

    try:
        client = SafetyBitableClient(app_token=app_token, table_id=collection_table_id)
        record = await client.get_record(record_id=feishu_record_id)
        if not isinstance(record, dict):
            return

        pg_id = await _sync_collection_to_pg(feishu_record_id, record)
        if not pg_id:
            return

        attachments = record.get("供应商资料")
        has_attachment = bool(
            attachments and isinstance(attachments, list) and len(attachments) > 0
        )
        if has_attachment:
            _schedule_parse(pg_id)
        else:
            logger.info("MSDS 采集无附件, 保持 pending: %s", feishu_record_id)
    except Exception:
        logger.exception("MSDS 采集事件处理失败: %s", feishu_record_id)


async def _handle_deleted(event_data: dict) -> None:
    feishu_record_id = event_data.get("record_id", "")
    if not feishu_record_id:
        return
    try:
        async with async_session_factory() as session:
            existing = await session.scalar(
                select(MsdsCollectionRecord).where(
                    MsdsCollectionRecord.feishu_record_id == feishu_record_id,
                    MsdsCollectionRecord.is_deleted == False,  # noqa: E712
                )
            )
            if existing:
                existing.is_deleted = True
                await session.commit()
                logger.info("MSDS 采集软删除: %s", feishu_record_id)
    except Exception:
        logger.exception("MSDS 采集软删除失败: %s", feishu_record_id)


# ── 事件注册 ──


@on_event("drive.file.bitable_record_changed_v1")
async def _on_collection_drive_changed(event: dict) -> None:
    """文档级记录变更事件：按 app_token + table_id 过滤后逐条分派。

    action_list 每项仅含 record_id/action，_handle_* 内部回源 get_record，
    此处只构造最小 event_data。created/changed 原语义同走 _handle_record。
    """
    if event.get("file_token", "") != _get_collection_app_token():
        return
    table_id = event.get("table_id", "")
    if table_id != _get_collection_table_id():
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
            else:  # record_added / record_edited
                await _handle_record(event_data)
        except Exception:
            logger.exception(
                "MSDS 采集 drive 事件处理失败: record_id=%s action=%s", record_id, action
            )
