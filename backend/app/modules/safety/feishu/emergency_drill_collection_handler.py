"""应急演练 — 「演练计划收录」Bitable 事件处理器。

安全员在「演练计划收录」表中上传演练计划附件（Word/PDF），
平台自动：下载→解析→AI提取字段→写入「演练计划统计」表→回写解析状态。

数据流：
  收录表 created_v1 → 下载附件 → SafetyDocumentParser 提取文本
    → EmergencyDrillService.parse_drill_plan_fields() AI 解析
    → SafetyBitableClient.create_record() 写入统计表
    → 回写收录表「解析状态」=已解析 + 同步 PostgreSQL
"""

import json
import logging
import pathlib
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select

from app.core.database import async_session_factory
from app.modules.safety.bitable_config.store import ConnectionView, store
from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.feishu.event_client import on_event
from app.modules.safety.models import DrillCollectionRecord

logger = logging.getLogger(__name__)


def _drill_main_conn() -> ConnectionView | None:
    """演练统计表（main）连接视图（store：DB 活行 → registry 默认）。"""
    return store.get_connection("emergency_drill", "main")


def _get_app_token() -> str:
    conn = _drill_main_conn()
    return conn.app_token if conn and conn.status != "disabled" else ""


def _get_statistics_table_id() -> str:
    conn = _drill_main_conn()
    return conn.table_id if conn and conn.status != "disabled" else ""


def _get_collection_table_id() -> str:
    conn = store.get_connection("emergency_drill", "collection")
    return conn.table_id if conn and conn.status != "disabled" else ""


UPLOAD_DIR = pathlib.Path("uploads/safety/drill/collection")


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


def _extract_person(raw: Any) -> dict | None:
    if not raw or not isinstance(raw, list):
        return None
    first = raw[0]
    if isinstance(first, dict):
        return {
            "open_id": first.get("id", ""),
            "name": first.get("name", ""),
            "email": first.get("email", ""),
        }
    return None


def _extract_department(raw: Any) -> str | None:
    """多选字段 → 逗号分隔文本"""
    if raw is None:
        return None
    if isinstance(raw, list):
        names = [item.get("name", "") if isinstance(item, dict) else str(item) for item in raw]
        return ", ".join(filter(None, names)) or None
    return str(raw) if raw else None


def _extract_attachment_meta(raw: Any) -> list | None:
    if not raw or not isinstance(raw, list):
        return None
    metas = []
    for item in raw:
        if isinstance(item, dict):
            metas.append({
                "name": item.get("name", ""),
                "file_token": item.get("file_token", ""),
            })
    return metas or None


# ── 文档解析 ──


def _parse_document_to_text(file_path: pathlib.Path, file_name: str) -> str:
    """将演练计划文档解析为纯文本。"""
    try:
        from app.modules.safety.knowledge.document_parser import SafetyDocumentParser
        text = SafetyDocumentParser.extract_text(str(file_path))
        if text and len(text.strip()) > 20:
            logger.info("Document parsed: %s → %d chars", file_name, len(text))
            return text
    except Exception:
        logger.warning("SafetyDocumentParser failed", exc_info=True)

    try:
        from app.platform.integrations.ai.document_parser import DocumentParser
        parser = DocumentParser()
        text = parser.parse(file_path)
        if text and len(text.strip()) > 20:
            logger.info("Document parsed via fallback: %s → %d chars", file_name, len(text))
            return text
    except Exception:
        logger.exception("All document parsers failed")

    return ""


# ── PG 同步 ──


async def _sync_collection_to_pg(
    feishu_record_id: str,
    record: dict,
    parse_status: str = "pending",
    parse_result: dict | None = None,
    stats_record_id: str | None = None,
) -> None:
    """同步收录记录到 PostgreSQL。"""
    try:
        from app.modules.safety.feishu.bitable_handler import acquire_record_lock

        async with async_session_factory() as session:
            # DB 级并发互斥：显式事务 + 事务级咨询锁（2026-09-08 补齐，见 acquire_record_lock）
            async with session.begin():
                await acquire_record_lock(session, feishu_record_id)
                existing = await session.scalar(
                    select(DrillCollectionRecord).where(
                        DrillCollectionRecord.feishu_record_id == feishu_record_id,
                        DrillCollectionRecord.is_deleted == False,  # noqa: E712
                    )
                )
                if existing:
                    existing.parse_status = parse_status
                    if parse_result is not None:
                        existing.parse_result = parse_result
                    if stats_record_id is not None:
                        existing.stats_record_id = stats_record_id
                else:
                    obj = DrillCollectionRecord(
                        feishu_record_id=feishu_record_id,
                        upload_date=_extract_date(record.get("日期")),
                        attachment=_extract_attachment_meta(record.get("演练计划附件")),
                        person_data=_extract_person(record.get("人员")),
                        department=_extract_department(record.get("部门")),
                        parse_status=parse_status,
                        parse_result=parse_result,
                        stats_record_id=stats_record_id,
                    )
                    session.add(obj)
            logger.info("Collection PG synced: %s status=%s", feishu_record_id, parse_status)
    except Exception:
        logger.exception("Collection PG sync failed: %s", feishu_record_id)


# ── Bitable 回写 ──


async def _update_collection_status(
    feishu_record_id: str,
    parse_status: str,
    parse_result: dict | None = None,
) -> None:
    """回写收录表「解析状态」字段。"""
    collection_table_id = _get_collection_table_id()
    app_token = _get_app_token()
    if not collection_table_id or not app_token:
        return
    try:
        client = SafetyBitableClient(app_token=app_token, table_id=collection_table_id)
        fields: dict[str, Any] = {}
        # 尝试回写「解析状态」字段（如果收录表有该字段）
        fields["解析状态"] = parse_status
        if parse_result:
            fields["解析结果"] = json.dumps(parse_result, ensure_ascii=False)[:3000]
        await client.update_record(record_id=feishu_record_id, fields=fields)
        logger.info("Collection status updated: %s → %s", feishu_record_id, parse_status)
    except Exception:
        logger.warning("Collection status update failed (field may not exist): %s", feishu_record_id)


# ── 事件处理 ──


async def _handle_collection_created(event_data: dict) -> None:
    feishu_record_id = event_data.get("record_id", "")
    if not feishu_record_id:
        return

    collection_table_id = _get_collection_table_id()
    if not collection_table_id:
        logger.warning("Collection table ID not configured")
        return

    logger.info("Collection record created: feishu_record_id=%s", feishu_record_id)

    try:
        # ── ① 获取收录记录 ──
        client = SafetyBitableClient(app_token=_get_app_token(), table_id=collection_table_id)
        record = await client.get_record(record_id=feishu_record_id)
        if not isinstance(record, dict):
            return

        # ── 先同步到 PG（状态=pending）──
        await _sync_collection_to_pg(feishu_record_id, record, parse_status="pending")

        # ── ② 提取附件并下载 ──
        attachments = record.get("演练计划附件")
        if not attachments or not isinstance(attachments, list) or len(attachments) == 0:
            logger.info("No attachment in collection record: %s", feishu_record_id)
            await _sync_collection_to_pg(feishu_record_id, record, parse_status="failed")
            return

        first_att = attachments[0]
        if not isinstance(first_att, dict):
            await _sync_collection_to_pg(feishu_record_id, record, parse_status="failed")
            return

        file_name = first_att.get("name", "drill_plan")
        file_token = first_att.get("file_token", "")
        download_url = first_att.get("url", "") or first_att.get("tmp_url", "")

        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = file_name.replace("/", "_").replace("\\", "_")
        local_path = UPLOAD_DIR / f"{feishu_record_id}_{safe_name}"

        data: bytes | None = None
        if download_url:
            try:
                data = await client.download_attachment_from_url(download_url)
            except Exception:
                pass
        if not data and file_token:
            try:
                data = await client.download_attachment(file_token)
            except Exception:
                pass

        if not data:
            logger.error("Failed to download collection attachment: %s", feishu_record_id)
            await _sync_collection_to_pg(feishu_record_id, record, parse_status="failed")
            return

        with open(local_path, "wb") as f:
            f.write(data)
        logger.info("Attachment downloaded: %s (%d bytes)", local_path, len(data))

        # ── ③ 解析文档文本 ──
        document_text = _parse_document_to_text(local_path, file_name)
        if not document_text:
            await _sync_collection_to_pg(feishu_record_id, record, parse_status="failed")
            return

        # ── ④ AI 提取字段 ──
        from app.modules.safety.service.emergency_drill import EmergencyDrillService

        parsed_fields = await EmergencyDrillService.parse_drill_plan_fields(document_text)
        if not parsed_fields:
            await _sync_collection_to_pg(feishu_record_id, record, parse_status="failed")
            return

        # ── ⑤ 写入统计表 ──
        stats_client = SafetyBitableClient(
            app_token=_get_app_token(), table_id=_get_statistics_table_id()
        )
        result = await stats_client.create_record(fields=parsed_fields)
        if result:
            new_record_id = result.get("record_id", "")
            logger.info(
                "Created statistics record: collection=%s → stats=%s fields=%s",
                feishu_record_id, new_record_id, list(parsed_fields.keys()),
            )
        else:
            logger.error("Failed to create statistics record: %s", feishu_record_id)
            await _sync_collection_to_pg(feishu_record_id, record, parse_status="failed")
            return

        # ── ⑥ 回写状态 + PG 更新 ──
        await _update_collection_status(feishu_record_id, "已解析", parsed_fields)
        await _sync_collection_to_pg(
            feishu_record_id, record,
            parse_status="parsed",
            parse_result=parsed_fields,
            stats_record_id=result.get("record_id", ""),
        )

    except Exception:
        logger.exception("Collection handler failed: feishu_record_id=%s", feishu_record_id)


# ── 事件注册 ──


@on_event("drive.file.bitable_record_changed_v1")
async def _on_collection_drive_changed(event: dict) -> None:
    """文档级记录变更事件：仅处理新增（保持原 created_v1 语义）。

    bitable.record.created_v1 飞书从不推送（3000+ 条真实事件实测 0 次），
    2026-09-08 迁移至文档级事件；record_edited/record_deleted 忽略——
    收录表行是"提交一次解析一次"，编辑不重新解析（防重复消费附件）。
    """
    if event.get("file_token", "") != _get_app_token():
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
            {"record_id": record_id, "action": event.get("action", "record_added")}
        ]

    for item in action_list:
        record_id = item.get("record_id", "")
        if not record_id or item.get("action", "") != "record_added":
            continue
        event_data = {"record_id": record_id, "table_id": table_id}
        try:
            await _handle_collection_created(event_data)
        except Exception:
            logger.exception(
                "演练收录 drive 事件处理失败: record_id=%s", record_id
            )
