"""演练评估表（AI）生成编排。

整条链：演练记录表附件 → 解析文本 → ai_drill_eval 插件（AI 出结构化内容）
→ 渲染 docx → 版本化落库（doc_type="eval"）→ 回写 Bitable「演练评估表（AI）」附件
→ 回填主表字段（演练问题/整改时间/整改责任人/确认人/状态，人工已填不覆盖）。

设计文档：.scratch/drill-ai-eval/backend-design.md
"""

from __future__ import annotations

import json
import logging
import pathlib
import tempfile
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety import attachment_store
from app.modules.safety.ai_drill_eval import (
    DrillEvalInput,
    DrillEvalOutput,
    DrillEvalPlugin,
)
from app.modules.safety.models import EmergencyDrillDocument, EmergencyDrillRecord

logger = logging.getLogger(__name__)

_DOC_TYPE_EVAL = "eval"
_SYNC_IGNORE_TTL = 120  # 覆盖「上传附件 + 回填字段」两次写与事件延迟窗口


# ── 纯工具 ──


def parse_date_text(text: str | None) -> date | None:
    """解析 AI/记录表中常见日期文本 → date（不改变原值语义）。

    支持：YYYY.MM.DD / YYYY-MM-DD / YYYY年MM月DD日 / YYYY/MM/DD。
    """
    if not text:
        return None
    s = str(text).strip().replace("年", "-").replace("月", "-").replace("日", "").replace(".", "-").replace("/", "-")
    parts = [p for p in s.split("-") if p.strip()]
    if len(parts) < 3:
        return None
    try:
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None


def build_issues_text(issues: list[Any]) -> str:
    """问题清单 → 「1. xx\n2. xx」编号文本（与主表既有格式一致）。"""
    lines = []
    for i, item in enumerate(issues, start=1):
        issue = getattr(item, "issue", "") or ""
        if issue.strip():
            lines.append(f"{i}. {issue.strip()}")
    return "\n".join(lines)


def earliest_deadline(output: DrillEvalOutput) -> date | None:
    """问题清单中最早的可解析完成期限。"""
    dates = [d for d in (parse_date_text(item.deadline) for item in output.issues) if d]
    return min(dates) if dates else None


def extract_attachment_text(file_path: str) -> str:
    """物化附件并解析纯文本（SafetyDocumentParser 降级 DocumentParser）。"""
    from app.modules.safety.vision.utils import resolve_local_path

    materialized = attachment_store.materialize(
        file_path, suffix=pathlib.Path(file_path).suffix,
    )
    if materialized is None:
        logger.warning("Record form file not found: %s", file_path)
        return ""
    temp_materialized = resolve_local_path(file_path) is None
    try:
        document_text = ""
        try:
            from app.modules.safety.knowledge.document_parser import (
                SafetyDocumentParser,
            )
            document_text = SafetyDocumentParser.extract_text(str(materialized))
        except Exception:
            logger.warning("SafetyDocumentParser failed for record form", exc_info=True)
        if not document_text or len(document_text.strip()) < 20:
            try:
                from app.platform.integrations.ai.document_parser import (
                    DocumentParser,
                )
                document_text = DocumentParser().parse(materialized)
            except Exception:
                pass
        return document_text or ""
    finally:
        if temp_materialized:
            attachment_store.cleanup_temp(materialized)


# ── 内部辅助 ──


async def _next_eval_version(session: AsyncSession, record_id: uuid.UUID) -> int:
    """eval 文档版本号（与 drill_plan 版本独立递增）。"""
    q = select(func.max(EmergencyDrillDocument.version)).where(
        EmergencyDrillDocument.resource_id == record_id,
        EmergencyDrillDocument.doc_type == _DOC_TYPE_EVAL,
        ~EmergencyDrillDocument.is_deleted,
    )
    current = (await session.execute(q)).scalar()
    return (current or 0) + 1


def _record_file_token(record: EmergencyDrillRecord) -> str | None:
    """从镜像的记录表附件 JSON 中取 file_token（手动触发时无事件上下文的兜底）。"""
    if record.drill_record_file:
        first = record.drill_record_file[0]
        if isinstance(first, dict):
            return first.get("file_token")
    return None


async def _collect_plan_context(session: AsyncSession, record: EmergencyDrillRecord) -> str:
    """组装演练方案上下文（评估的对照基准）：AI 方案结构化内容 + 定稿附件解析文本。

    - AI 方案（doc_type="drill_plan" 最新版）存在时，其 docx 附件（drill_plan_file）
      即同一份渲染产物，跳过附件解析避免重复注入；
    - 演练方案（定稿）为人工另一份文档，始终解析。
    """
    parts: list[str] = []

    doc = (
        await session.execute(
            select(EmergencyDrillDocument)
            .where(
                EmergencyDrillDocument.resource_id == record.id,
                EmergencyDrillDocument.doc_type == "drill_plan",
                ~EmergencyDrillDocument.is_deleted,
            )
            .order_by(EmergencyDrillDocument.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    has_ai_plan_doc = False
    if doc and doc.content_json:
        cj = doc.content_json
        lines: list[str] = []
        if cj.get("title"):
            lines.append(str(cj["title"]))
        if cj.get("summary"):
            lines.append(f"【摘要】{cj['summary']}")
        for sec in cj.get("sections", []) or []:
            if not isinstance(sec, dict):
                continue
            heading, content = sec.get("heading", ""), sec.get("content", "")
            if heading:
                lines.append(str(heading))
            if content:
                lines.append(str(content))
        if lines:
            has_ai_plan_doc = True
            parts.append("（以下为演练方案全文，是本次演练的设计基准）\n" + "\n".join(lines))

    # 附件方案：无 AI 方案文档时解析 drill_plan_file；定稿始终解析
    for attr, label, enabled in (
        ("drill_plan_file", "演练方案（AI）", not has_ai_plan_doc),
        ("plan_final_file", "演练方案（定稿）", True),
    ):
        if not enabled:
            continue
        files = getattr(record, attr, None)
        if not files:
            continue
        path = files[0] if not isinstance(files[0], dict) else files[0].get("path")
        if not path:
            continue
        text = extract_attachment_text(path)
        if len(text.strip()) >= 20:
            parts.append(f"（以下为{label}全文，是本次演练的设计基准）\n{text[:12000]}")

    return "\n\n".join(parts)


async def _write_bitable(
    record: EmergencyDrillRecord,
    output: DrillEvalOutput,
    doc_title: str,
    docx_bytes: bytes,
    backfill_fields: dict[str, Any],
) -> str | None:
    """写 Bitable：先置 sync-ignore 防回环，再上传附件、回填字段。

    Returns:
        统一存储路径（写入 eval_ai_file 的镜像值，与 handler 下载复用规则同名）。
    """
    from app.modules.safety import attachment_store
    from app.modules.safety.bitable_config.store import store
    from app.modules.safety.feishu.bitable_client import SafetyBitableClient
    from app.modules.safety.feishu.bitable_handler import _set_sync_ignore

    conn = store.get_connection("emergency_drill", "main")
    if conn is None or conn.status == "disabled":
        return None
    app_token, table_id = conn.app_token, conn.table_id
    if not app_token or not table_id or not record.feishu_record_id:
        return None

    await _set_sync_ignore(record.feishu_record_id, ttl=_SYNC_IGNORE_TTL)
    client = SafetyBitableClient(app_token=app_token, table_id=table_id)

    upload: dict | None = None
    safe_name = doc_title.replace("/", "_").replace("\\", "_")
    upload_name = f"{safe_name}.docx"
    tmp_path = pathlib.Path(tempfile.gettempdir()) / upload_name
    try:
        tmp_path.write_bytes(docx_bytes)
        upload = await client.upload_media(str(tmp_path.resolve()), upload_name)
        if upload:
            await client.update_record(
                record_id=record.feishu_record_id,
                fields={"演练评估表（AI）": [{"file_token": upload["file_token"], "name": upload_name}]},
            )
        else:
            logger.warning("Failed to upload eval docx to Bitable: record_id=%s", record.feishu_record_id)
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass

    # 统一存储落盘（文件名与 handler _download_and_replace_attachments 探测规则一致，
    # changed 事件回读时「已存在则复用」，避免重复下载）
    stored: str | None = None
    if upload:
        try:
            stored_filename = f"drill_{record.feishu_record_id}_{upload['file_token']}_{upload_name}"
            stored = attachment_store.store_bytes(
                "drill", stored_filename, docx_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        except Exception:
            logger.warning("Eval docx store_bytes failed: record_id=%s", record.feishu_record_id, exc_info=True)

    if backfill_fields:
        # 回填独立于附件上传执行：附件失败时字段回填仍尝试（各自降级，互不阻塞）
        await client.update_record(
            record_id=record.feishu_record_id,
            fields=backfill_fields,
        )
    return stored


def _build_backfill_fields(
    record: EmergencyDrillRecord,
    output: DrillEvalOutput,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """计算 Bitable 回填字段与 PG 回填值（人工已填不覆盖，判定基于 PG 镜像判空）。

    Returns:
        (bitable_fields, pg_values)
    """
    from app.modules.safety.feishu.bitable_id_mapper import get_bitable_person_value

    bitable_fields: dict[str, Any] = {}
    pg_values: dict[str, Any] = {}

    issues_text = build_issues_text(output.issues)
    if issues_text and not (record.issues or "").strip():
        bitable_fields["演练问题"] = issues_text
        pg_values["issues"] = issues_text

    rect_time = earliest_deadline(output)
    if rect_time and record.rectification_time is None:
        ts = int(datetime(rect_time.year, rect_time.month, rect_time.day, tzinfo=UTC).timestamp() * 1000)
        bitable_fields["整改时间"] = ts
        pg_values["rectification_time"] = rect_time
        if not record.status:
            status = "已完成" if rect_time < date.today() else "未完成"
            bitable_fields["状态"] = status
            pg_values["status"] = status

    for cn_field, attr, item_attr in (
        ("整改责任人", "rectification_person", "rectifier"),
        ("确认人", "confirmer", "confirmer"),
    ):
        if getattr(record, attr):
            continue
        name = next(
            (getattr(item, item_attr) for item in output.issues if getattr(item, item_attr, "")),
            "",
        )
        if not name:
            continue
        person_value = get_bitable_person_value(name=name)
        if person_value:
            bitable_fields[cn_field] = person_value
        else:
            logger.warning("Eval form person has no bitable_open_id mapping: %s=%s", cn_field, name)
        pg_values[attr] = name

    return bitable_fields, pg_values


# ── 主编排 ──


async def generate_eval_form(
    session: AsyncSession,
    record_id: uuid.UUID,
    *,
    source: str = "manual",
    record_file_token: str | None = None,
) -> EmergencyDrillDocument | None:
    """生成演练评估表（AI）。

    Args:
        session: 数据库会话（文档落库用传入会话，commit 由调用方负责）
        record_id: EmergencyDrillRecord.id
        source: manual | bitable（审计 channel）
        record_file_token: 触发时所用的演练记录表 file_token（事件上下文）；
            缺省从镜像 JSON 兜底。

    Returns:
        版本化文档；记录不存在 / 无记录表 / 无文本 / AI 失败 返回 None。
    """
    record = (
        await session.execute(
            select(EmergencyDrillRecord).where(
                EmergencyDrillRecord.id == record_id,
                ~EmergencyDrillRecord.is_deleted,
            )
        )
    ).scalar_one_or_none()
    if record is None:
        logger.warning("Eval generation aborted, record not found: %s", record_id)
        return None
    if not record.drill_record_file:
        logger.info("Eval generation aborted, no record form file: %s", record_id)
        return None

    # ── ① 输入组装：记录表全文（必须）+ 演练方案上下文（对照基准，可缺）──
    record_form_text = extract_attachment_text(record.drill_record_file[0])
    if len(record_form_text.strip()) < 20:
        logger.warning("Record form produced no text: record_id=%s", record_id)
        return None
    plan_text = await _collect_plan_context(session, record)

    # ── ② AI 生成（统一审计 scope）──
    record_fields: dict[str, str] = {}
    for label, attr in (
        ("演练内容", "drill_content"),
        ("演练类型", "drill_type"),
        ("演练部门", "department"),
        ("组织人", "organizer"),
        ("参演人员", "participants"),
        ("课时", "duration"),
        ("实施时间", "execution_time"),
    ):
        value = getattr(record, attr, None)
        if value:
            record_fields[label] = str(value)

    from app.modules.safety.ai_audit import ai_audit_scope
    from app.modules.safety.ai_audit.models import SCENARIO_DRILL_EVAL_GENERATION
    from app.modules.safety.service.config import create_ai_service

    response_output: DrillEvalOutput
    ai_model = None
    estimated_tokens = 0
    try:
        ai_service = create_ai_service("text")
    except Exception:
        logger.exception("Failed to create AI service for eval generation")
        return None

    try:
        with ai_audit_scope(
            scenario=SCENARIO_DRILL_EVAL_GENERATION,
            resource_type="drill_record",
            resource_id=record_id,
            channel=source,
        ):
            plugin = DrillEvalPlugin(ai_service)
            response_output = await plugin.review(
                DrillEvalInput(
                    record_fields=record_fields,
                    plan_text=plan_text,
                    record_form_text=record_form_text,
                )
            )
            ai_model = getattr(ai_service, "model", None)
            estimated_tokens = (
                len(record_form_text) // 3
                + len(plan_text) // 3
                + len(json.dumps(record_fields, ensure_ascii=False)) // 3
                + len(json.dumps(response_output.model_dump(), ensure_ascii=False)) // 3
            )
    except Exception:
        logger.exception("AI eval generation failed: record_id=%s", record_id)
        return None
    finally:
        await ai_service.close()

    # ── ③ 渲染 docx ──
    from app.modules.safety.service.eval_docx import render_eval_docx

    department = record.department or ""
    scene = (response_output.drill_name or record.drill_content or "应急演练").strip()[:60]
    doc_title = f"{department}{scene}演练评估表"[:80]
    docx_bytes = render_eval_docx(
        response_output, doc_title=doc_title, drill_type_hint=record.drill_type or "",
    )

    # ── ④ 版本化落库 ──
    version = await _next_eval_version(session, record_id)
    doc = EmergencyDrillDocument(
        resource_type="drill_record",
        resource_id=record_id,
        doc_type=_DOC_TYPE_EVAL,
        title=doc_title,
        content=response_output.overall_comment or None,
        content_json=response_output.model_dump(),
        generation_params={
            "record_id": str(record_id),
            "source": source,
            "record_file_token": record_file_token or _record_file_token(record) or "",
        },
        ai_model=ai_model,
        ai_tokens_used=estimated_tokens,
        version=version,
    )
    session.add(doc)
    await session.flush()

    # ── ⑤ Bitable 回写 + 回填 ──
    try:
        bitable_fields, pg_values = _build_backfill_fields(record, response_output)
        stored = await _write_bitable(record, response_output, doc_title, docx_bytes, bitable_fields)
    except Exception:
        logger.warning(
            "Bitable eval writeback failed, doc kept: record_id=%s", record_id, exc_info=True,
        )
        return doc

    # ── ⑥ PG 更新（附件镜像 + 去重 token + 回填值；record 由传入 session 管理，commit 归调用方）──
    record.eval_ai_file = [stored] if stored else None
    record.eval_source_record_file_token = record_file_token or _record_file_token(record)
    for attr, value in (pg_values or {}).items():
        setattr(record, attr, value)

    logger.info(
        "AI eval form generated: doc_id=%s record_id=%s version=%s source=%s",
        doc.id, record_id, version, source,
    )
    return doc
