"""QA 文档 AI 分析服务。

AI 运行只产生事实、候选和待审核提案。任何正式的
``document_master_links``、``master_objects`` 或 ``master_object_sources``
写入都必须经过现有人工确认/主数据服务。
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AppException, ForbiddenException, NotFoundException
from app.modules.qa.document_processing import CHUNK_VERSION
from app.modules.qa.models import (
    AIAnalysisStatus,
    AIAuthorityPolicy,
    AIProposalStatus,
    AISuggestionStatus,
    Document,
    DocumentAIAnalysisRun,
    DocumentChunkBlock,
    DocumentEntityObservation,
    DocumentFile,
    DocumentMasterLink,
    DocumentRelationSuggestion,
    DocumentTextChunk,
    DocumentTextSegment,
    DocumentType,
    DocumentVersion,
    MasterObject,
    MasterObjectAlias,
    MasterObjectProposal,
    MasterObjectType,
    RecordStatus,
    RelationType,
    VersionStatus,
)
from app.modules.qa.repository import (
    get_ai_run,
    get_aliases,
    get_chunks,
    get_file_for_version,
    get_version,
    list_masters,
    list_proposals,
)
from app.modules.qa.service import _actor_id, _audit, normalize_text
from app.platform.identity.models import User
from app.platform.integrations.ai.client import AIOutputError, AIService
from app.platform.permission.deps import get_user_permissions

logger = logging.getLogger(__name__)

PROMPT_VERSION = "qa-entity-v1"
SCHEMA_VERSION = "qa-entity-schema-v1"
AI_MAX_RETRY_COUNT = 3
AI_LEASE_MINUTES = 15
# 单个提案保留的证据条数上限，与 observation 的证据位置上限保持一致。
# 页眉/页脚会让同一实体在几十个 chunk 里反复出现，无上限追加会让一个
# JSON 列涨到数 MB，并把去重扫描变成 O(n²)。
MAX_PROPOSAL_EVIDENCE = 10
ENTITY_TYPES = {item.value for item in MasterObjectType}
_MODEL_ENTITY_TO_MASTER: dict[str, str] = {
    "PRODUCT": "PRODUCT",
    "MATERIAL": "MATERIAL",
    "EQUIPMENT": "EQUIPMENT",
    "SUPPLIER": "SUPPLIER",
    "REGION": "REGION",
    "产品": "PRODUCT",
    "物料": "MATERIAL",
    "设备": "EQUIPMENT",
    "供应商": "SUPPLIER",
    "区域": "REGION",
}


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _analysis_audit_context(run: DocumentAIAnalysisRun) -> dict[str, Any]:
    """供决策审计复用的运行元数据；不包含 prompt、正文或模型原始响应。"""

    return {
        "analysis_run_id": str(run.id),
        "input_fingerprint": run.input_fingerprint,
        "catalog_fingerprint": run.catalog_fingerprint,
        "model": run.model,
        "provider": run.provider,
        "prompt_version": run.prompt_version,
        "schema_version": run.schema_version,
    }


def _quote(content: str, mention: str, max_chars: int = 600) -> str:
    index = content.casefold().find(mention.casefold())
    if index < 0:
        return content[:max_chars]
    start = max(0, index - max_chars // 3)
    end = min(len(content), start + max_chars)
    return content[start:end]


def _safe_entity_type(value: Any) -> str | None:
    normalized = str(value or "").strip().upper()
    mapped = _MODEL_ENTITY_TO_MASTER.get(normalized)
    if mapped:
        return mapped
    return normalized if normalized in ENTITY_TYPES else None


def _evidence_location_metadata(source: DocumentTextSegment | None) -> dict[str, Any]:
    """提取不含正文的版面定位摘要，供审核端展示。

    raw block 的 ``source_metadata`` 会完整保存（包括表格网格和 PDF span），
    但实体事实只需要复制有限的坐标/结构摘要。这样既能让 PDF 证据显示
    bbox/行列位置，也不会把整段原文或模型输入重复写进 observation JSON。
    """

    if source is None:
        return {}
    raw = source.source_metadata or {}
    result: dict[str, Any] = {
        "block_type": source.block_type,
        "heading_path": list(source.heading_path or []),
    }
    if source.block_type == "pdf_block":
        pdf: dict[str, Any] = {}
        for key in (
            "bbox",
            "page_width",
            "page_height",
            "block_index",
            "reading_order",
            "boilerplate_candidate",
        ):
            if key in raw:
                value = raw[key]
                # 坐标和尺寸来自 PyMuPDF，全部转成普通 JSON 数字；其它
                # 字段只接受标量，避免把未知解析器对象带进 JSON 列。
                if key in {"bbox", "page_width", "page_height"}:
                    if isinstance(value, (list, tuple)):
                        pdf[key] = [float(item) for item in value[:4]]
                    elif isinstance(value, (int, float)):
                        pdf[key] = float(value)
                elif isinstance(value, (str, int, float, bool)):
                    pdf[key] = value
        lines = raw.get("lines")
        if isinstance(lines, list):
            line_boxes: list[list[float]] = []
            span_boxes: list[dict[str, Any]] = []
            for line in lines:
                if not isinstance(line, dict):
                    continue
                line_bbox = line.get("bbox")
                if isinstance(line_bbox, (list, tuple)) and len(line_bbox) >= 4:
                    line_boxes.append([float(item) for item in line_bbox[:4]])
                spans = line.get("spans")
                if isinstance(spans, list):
                    for span in spans:
                        if not isinstance(span, dict):
                            continue
                        bbox = span.get("bbox")
                        if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
                            continue
                        item: dict[str, Any] = {
                            "bbox": [float(value) for value in bbox[:4]],
                        }
                        for key in ("font", "size"):
                            if isinstance(span.get(key), (str, int, float)):
                                item[key] = span[key]
                        span_boxes.append(item)
            if line_boxes:
                pdf["line_bboxes"] = line_boxes
            if span_boxes:
                # 坐标摘要最多保留 256 个 span，避免异常 PDF 让每个实体
                # observation 过度膨胀；raw block 仍保存完整结构。
                pdf["span_positions"] = span_boxes[:256]
        if pdf:
            result["pdf"] = pdf
    elif source.block_type in {"table_header", "table_row"}:
        table: dict[str, Any] = {}
        for key in (
            "row",
            "row_count",
            "column_count",
            "is_header",
            "is_repeated_header",
        ):
            if key in raw and isinstance(raw[key], (str, int, float, bool)):
                table[key] = raw[key]
        cells = raw.get("cells")
        if isinstance(cells, list):
            table["cells"] = [
                {
                    key: cell[key]
                    for key in ("row", "column", "grid_span", "v_merge")
                    if key in cell
                    and isinstance(cell[key], (str, int, float, bool, type(None)))
                }
                for cell in cells[:256]
                if isinstance(cell, dict)
            ]
        if table:
            result["table"] = table
    else:
        structure = {
            key: raw[key]
            for key in ("style", "numbering")
            if key in raw
            and isinstance(raw[key], (str, int, float, bool, dict, type(None)))
        }
        if structure:
            result["structure"] = structure
    return result


def _merge_evidence_locations(
    existing: list[dict[str, Any]], entry: dict[str, Any], cap: int = 10
) -> list[dict[str, Any]]:
    """同一实体跨 chunk 重复出现时合并证据位置：按哈希去重、超出上限截断。

    分块会把表头复制进每个派生块、PDF 页眉页脚逐页保留，同一实体可能
    出现几十次；位置列表只保留前 ``cap`` 处供审核端展示，避免 observation
    JSON 无限膨胀。重复哈希（同一 raw block 被多个 chunk 引用）直接忽略。
    """
    if any(
        item.get("evidence_hash") == entry.get("evidence_hash") for item in existing
    ):
        return list(existing)
    return [*existing, entry][:cap]


async def _catalog(
    db: AsyncSession,
) -> tuple[list[MasterObject], dict[uuid.UUID, list[str]], str]:
    # 分析快照只取 active 且未删除的 QA 主数据；不读取跨模块来源，避免
    # AI 越过人工来源选择边界。
    # 不能假设主数据目录小于固定页大小；分析快照必须覆盖全部 active
    # 主数据，否则同一文档在目录规模扩大后会出现隐式漏匹配。
    masters, total = await list_masters(
        db, status=RecordStatus.ACTIVE.value, page=1, page_size=10000
    )
    page = 2
    while len(masters) < total:
        next_page, _ = await list_masters(
            db, status=RecordStatus.ACTIVE.value, page=page, page_size=10000
        )
        if not next_page:
            break
        masters.extend(next_page)
        page += 1
    if not masters:
        return [], {}, _fingerprint([])
    aliases_result = await db.execute(
        select(MasterObjectAlias).where(
            MasterObjectAlias.master_object_id.in_([m.id for m in masters]),
            MasterObjectAlias.is_deleted.is_(False),
        )
    )
    aliases: dict[uuid.UUID, list[str]] = {}
    for alias in aliases_result.scalars():
        aliases.setdefault(alias.master_object_id, []).append(alias.alias)
    fingerprint = _fingerprint(
        [
            {
                "id": str(master.id),
                "object_type": master.object_type,
                "code": master.code,
                "name": master.name,
                "aliases": sorted(aliases.get(master.id, [])),
            }
            for master in masters
        ]
    )
    return masters, aliases, fingerprint


async def create_analysis_run(
    db: AsyncSession,
    version_id: uuid.UUID,
    user: User | None = None,
    *,
    force: bool = False,
) -> DocumentAIAnalysisRun:
    settings = get_settings()
    # 同一版本的触发请求按版本行串行化，避免并发请求在看不到彼此未提交
    # 运行时创建两个相同 fingerprint 的任务。force=True 会显式新建运行，
    # 并让该版本上一个仍可发布的运行失效，防止两个结果都被确认。
    version_result = await db.execute(
        select(DocumentVersion)
        .where(
            DocumentVersion.id == version_id,
            DocumentVersion.is_deleted.is_(False),
        )
        .with_for_update()
    )
    version = version_result.scalar_one_or_none()
    if version is None:
        raise NotFoundException("文件版本", str(version_id))
    if version.status == VersionStatus.INACTIVE.value or not version.approved_declared:
        raise AppException(
            status_code=422, message="停用或未批准声明的版本不能进行 AI 分析"
        )
    file_row = await get_file_for_version(db, version_id)
    if file_row is None:
        raise AppException(status_code=422, message="版本缺少主文件")
    if not file_row.current_chunk_run_id or file_row.extraction_status != "ready":
        raise AppException(
            status_code=409, message="该文件尚未完成新版解析/分块，请先重新解析"
        )
    document = await db.get(Document, version.document_id)
    if (
        document is None
        or document.is_deleted
        or document.status != RecordStatus.ACTIVE.value
    ):
        raise AppException(
            status_code=422, message="停用或不存在的文件台账不能进行 AI 分析"
        )
    doc_type = (
        await db.get(DocumentType, document.document_type_id) if document else None
    )
    if (
        doc_type is None
        or doc_type.is_deleted
        or doc_type.status != RecordStatus.ACTIVE.value
    ):
        raise AppException(status_code=422, message="文件类型不存在或已停用")
    policy = getattr(
        doc_type, "ai_source_policy", AIAuthorityPolicy.AUTHORITATIVE.value
    )
    if policy == AIAuthorityPolicy.DISABLED.value:
        raise AppException(status_code=409, message="该文件类型已停用 AI 分析")
    masters, _, catalog_fingerprint = await _catalog(db)
    input_fingerprint = _fingerprint(
        {
            "sha256": file_row.sha256,
            "extraction_run_id": str(file_row.current_extraction_run_id),
            "chunk_run_id": str(file_row.current_chunk_run_id),
            "catalog": catalog_fingerprint,
            "model": settings.QA_AI_MODEL,
            # max_tokens 会截断实体 JSON 从而改变分析结果，必须参与指纹，
            # 否则调小它之后 force=false 的重新分析会命中旧运行、看似无效。
            "max_tokens": settings.QA_AI_MAX_TOKENS,
            "provider": "openai-compatible",
            "base_url": settings.QA_AI_BASE_URL,
            "enabled": bool(settings.QA_AI_ENABLED and settings.QA_AI_API_KEY),
            "prompt": getattr(settings, "QA_AI_PROMPT_VERSION", PROMPT_VERSION),
            "schema": getattr(settings, "QA_AI_SCHEMA_VERSION", SCHEMA_VERSION),
            "source_policy": policy,
        }
    )
    latest_result = await db.execute(
        select(DocumentAIAnalysisRun)
        .where(
            DocumentAIAnalysisRun.version_id == version_id,
            DocumentAIAnalysisRun.is_deleted.is_(False),
        )
        .order_by(DocumentAIAnalysisRun.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    latest = latest_result.scalar_one_or_none()
    if latest and not force and latest.input_fingerprint == input_fingerprint:
        if latest.status in {
            AIAnalysisStatus.QUEUED.value,
            AIAnalysisStatus.PROCESSING.value,
            AIAnalysisStatus.READY.value,
            AIAnalysisStatus.PARTIAL.value,
        }:
            return latest
        if (
            latest.status == AIAnalysisStatus.FAILED.value
            and latest.retry_count < AI_MAX_RETRY_COUNT
        ):
            # 失败任务仍有自动重试额度时复用同一运行，避免用户点击重试
            # 与调度器下一次扫描同时创建相同 fingerprint 的并行任务。
            latest.status = AIAnalysisStatus.QUEUED.value
            latest.worker_token = None
            latest.lease_until = None
            latest.finished_at = None
            await db.flush()
            await _audit(
                db,
                action="ai_analysis_retry_requested",
                user=user,
                resource_type="document_ai_analysis_run",
                resource_id=latest.id,
                new_value={
                    "status": latest.status,
                    "retry_count": latest.retry_count,
                },
                extra={"input_fingerprint": latest.input_fingerprint},
            )
            return latest
    if force:
        # 强制重跑不能让同一版本的旧结果继续可确认。除了最近一次运行，
        # 也回收更早但仍 ready/partial 的运行，避免用户在旧标签页中提交
        # 一个已经被新运行替代的候选；事实和审计仍完整保留。
        active_runs_result = await db.execute(
            select(DocumentAIAnalysisRun)
            .where(
                DocumentAIAnalysisRun.version_id == version_id,
                DocumentAIAnalysisRun.is_deleted.is_(False),
                DocumentAIAnalysisRun.status.in_(
                    [
                        AIAnalysisStatus.QUEUED.value,
                        AIAnalysisStatus.PROCESSING.value,
                        AIAnalysisStatus.READY.value,
                        AIAnalysisStatus.PARTIAL.value,
                    ]
                ),
            )
            .with_for_update()
        )
        for active_run in active_runs_result.scalars():
            await _mark_analysis_stale(db, active_run, "已被人工强制重跑替代", user=user)
    run = DocumentAIAnalysisRun(
        version_id=version_id,
        file_id=file_row.id,
        extraction_run_id=file_row.current_extraction_run_id,
        chunk_run_id=file_row.current_chunk_run_id,
        status=AIAnalysisStatus.QUEUED.value,
        provider="openai-compatible",
        model=settings.QA_AI_MODEL,
        prompt_version=getattr(settings, "QA_AI_PROMPT_VERSION", PROMPT_VERSION),
        schema_version=getattr(settings, "QA_AI_SCHEMA_VERSION", SCHEMA_VERSION),
        catalog_fingerprint=catalog_fingerprint,
        input_fingerprint=input_fingerprint,
        source_policy=policy,
        requested_by=_actor_id(user),
        created_by=_actor_id(user),
        updated_by=_actor_id(user),
    )
    db.add(run)
    await db.flush()
    await _audit(
        db,
        action="ai_analysis_requested",
        user=user,
        resource_type="document_ai_analysis_run",
        resource_id=run.id,
        new_value={"version_id": str(version_id), "status": run.status},
        extra={
            "sha256": file_row.sha256,
            "input_fingerprint": input_fingerprint,
            "catalog_fingerprint": catalog_fingerprint,
            "model": run.model,
            "prompt_version": run.prompt_version,
            "schema_version": run.schema_version,
        },
    )
    return run


async def _model_entities(chunk: DocumentTextChunk) -> list[dict[str, Any]]:
    settings = get_settings()
    if not settings.QA_AI_ENABLED or not settings.QA_AI_API_KEY:
        return []
    prompt = (
        "你是质量文件实体抽取器。只从给定文本中抽取明确出现、与质量主数据有关的实体。"
        "不要猜测，不要生成主数据 ID，不要返回文本中不存在的证据。"
        '返回 JSON：{"entities":[{"mention_text":"原文",'
        '"entity_type":"PRODUCT|MATERIAL|EQUIPMENT|SUPPLIER|REGION",'
        '"quote":"包含原文的短证据","normalization_hint":"可选规范化名称"}]}。\n\n'
        f"文本：\n{chunk.content[:12000]}"
    )
    last_error: Exception | None = None
    for attempt in range(max(1, int(settings.QA_AI_MAX_RETRIES) + 1)):
        client = AIService(
            api_key=settings.QA_AI_API_KEY,
            base_url=settings.QA_AI_BASE_URL,
            model=settings.QA_AI_MODEL,
            timeout=settings.QA_AI_TIMEOUT_SECONDS,
        )
        try:
            raw = await client.chat(
                [
                    {"role": "system", "content": "只输出合法 JSON，不输出 Markdown。"},
                    {"role": "user", "content": prompt},
                ],
                response_format="json_object",
                temperature=0,
                max_tokens=settings.QA_AI_MAX_TOKENS,
            )
            parsed = json.loads(raw)
            if not isinstance(parsed, dict) or not isinstance(
                parsed.get("entities"), list
            ):
                raise AIOutputError("AI entities schema invalid")
            entities: list[dict[str, Any]] = []
            for item in parsed["entities"]:
                if not isinstance(item, dict):
                    continue
                mention = str(item.get("mention_text") or "").strip()[:500]
                quote = str(item.get("quote") or "").strip()[:600]
                if not mention or mention.casefold() not in chunk.content.casefold():
                    continue
                entity_type = _safe_entity_type(item.get("entity_type"))
                if entity_type is None:
                    # 模型返回未知类型时保留不了可靠的主数据目录边界，
                    # 不把它武断归为 MATERIAL，也不生成正式提案。
                    continue
                if quote and quote.casefold() not in chunk.content.casefold():
                    quote = _quote(chunk.content, mention)
                entities.append(
                    {
                        "mention_text": mention,
                        "quote": quote or _quote(chunk.content, mention),
                        "entity_type": entity_type,
                        "normalization_hint": str(
                            item.get("normalization_hint") or ""
                        ).strip()[:500]
                        or None,
                    }
                )
            return entities
        except (
            httpx.HTTPStatusError,
            httpx.TimeoutException,
            httpx.TransportError,
            AIOutputError,
            json.JSONDecodeError,
            KeyError,
            IndexError,
            TypeError,
        ) as exc:
            last_error = exc
            if isinstance(
                exc, httpx.HTTPStatusError
            ) and exc.response.status_code not in {429, 500, 502, 503, 504}:
                break
            if attempt < int(settings.QA_AI_MAX_RETRIES):
                await asyncio.sleep(min(2**attempt, 4))
        finally:
            await client.close()
    if last_error:
        raise last_error
    return []


def _deterministic_matches(
    content: str,
    masters: list[MasterObject],
    aliases: dict[uuid.UUID, list[str]],
) -> list[tuple[MasterObject, str, str, float]]:
    normalized_content = normalize_text(content)
    candidates: list[tuple[MasterObject, str, str, float]] = []
    for master in masters:
        terms: list[tuple[str, str, float]] = [
            (master.code, "exact_code", 1.0),
            (master.name, "exact_name", 0.95),
        ]
        terms.extend(
            (alias, "exact_alias", 0.98) for alias in aliases.get(master.id, [])
        )
        priority = {"exact_code": 3, "exact_alias": 2, "exact_name": 1}
        for term, method, confidence in sorted(
            terms,
            key=lambda item: (priority.get(item[1], 0), len(item[0])),
            reverse=True,
        ):
            term_normalized = normalize_text(term)
            if len(term_normalized) < 2:
                continue
            if term_normalized in normalized_content:
                candidates.append((master, term, method, confidence))
                break
    return candidates


def _fuzzy_match(
    mention: str,
    masters: list[MasterObject],
    aliases: dict[uuid.UUID, list[str]],
    *,
    entity_type: str | None = None,
) -> list[tuple[MasterObject, str, float]]:
    query = normalize_text(mention)
    ranked: list[tuple[float, MasterObject, str]] = []
    for master in masters:
        if entity_type and master.object_type != entity_type:
            continue
        terms = [master.code, master.name, *aliases.get(master.id, [])]
        for term in terms:
            score = difflib.SequenceMatcher(None, query, normalize_text(term)).ratio()
            if score >= 0.82:
                ranked.append((score, master, term))
    ranked.sort(key=lambda item: item[0], reverse=True)
    unique: list[tuple[MasterObject, str, float]] = []
    seen: set[uuid.UUID] = set()
    for score, master, term in ranked:
        if master.id in seen:
            continue
        seen.add(master.id)
        unique.append((master, term, score))
        if len(unique) == 3:
            break
    return unique


async def _lock_analysis_run_for_worker(
    db: AsyncSession,
    run_id: uuid.UUID,
    lease_token: str | None,
) -> DocumentAIAnalysisRun | None:
    """在写入分析结果前原子确认当前 worker 仍持有租约。

    模型调用期间不持有数据库锁；返回后用 ``FOR UPDATE`` 把 token 校验
    与后续结果写入放进同一事务，避免租约刚被回收时旧 worker 仍提交候选。
    ``None`` token 仅服务于没有调度器的兼容性直调用，也必须保持数据库
    token 为空。
    """

    statement = select(DocumentAIAnalysisRun).where(
        DocumentAIAnalysisRun.id == run_id,
        DocumentAIAnalysisRun.is_deleted.is_(False),
    )
    if lease_token is None:
        statement = statement.where(DocumentAIAnalysisRun.worker_token.is_(None))
    else:
        statement = statement.where(DocumentAIAnalysisRun.worker_token == lease_token)
    result = await db.execute(statement.with_for_update())
    return result.scalar_one_or_none()


async def process_analysis_run(
    db: AsyncSession,
    run_id: uuid.UUID,
    *,
    worker_token: str | None = None,
) -> DocumentAIAnalysisRun:
    run = await get_ai_run(db, run_id)
    if run is None:
        raise NotFoundException("AI 分析运行", str(run_id))
    # 保存本次 worker 领取到的 token。外层异常处理必须重新按该 token
    # claim 行锁，不能直接使用可能已经过期的 ORM 对象覆盖新 worker 的状态。
    run_lease_token = worker_token if worker_token is not None else run.worker_token
    if run_lease_token is not None and run.worker_token != run_lease_token:
        return run
    if run.status in {AIAnalysisStatus.READY.value, AIAnalysisStatus.PARTIAL.value}:
        return run
    # 兼容直接调用与调度器调用：在把运行置为 processing 前先确认并锁住
    # 当前 token，避免扫描器刚接管时旧调用覆盖 claim。
    claimed_run = await _lock_analysis_run_for_worker(db, run_id, run_lease_token)
    if claimed_run is None:
        await db.rollback()
        return await get_ai_run(db, run_id) or run
    run = claimed_run
    if run.status in {AIAnalysisStatus.READY.value, AIAnalysisStatus.PARTIAL.value}:
        await db.commit()
        return run
    run.status = AIAnalysisStatus.PROCESSING.value
    run.started_at = run.started_at or datetime.now(UTC)
    run.lease_until = datetime.now(UTC) + timedelta(minutes=AI_LEASE_MINUTES)
    if run.retry_count or run.processed_chunks:
        for model in (
            DocumentEntityObservation,
            DocumentRelationSuggestion,
            MasterObjectProposal,
        ):
            await db.execute(
                update(model)
                .where(model.analysis_run_id == run.id, model.is_deleted.is_(False))
                .values(is_deleted=True)
            )
        run.processed_chunks = 0
        run.entity_count = 0
        run.suggestion_count = 0
        run.proposal_count = 0
        run.error = None
    await db.flush()
    # claim/运行元数据先提交；后续模型 HTTP 调用不持有数据库行锁。
    await db.commit()
    try:
        chunks = await get_chunks(db, run.chunk_run_id) if run.chunk_run_id else []
        masters, aliases, catalog_fingerprint = await _catalog(db)
        if catalog_fingerprint != run.catalog_fingerprint:
            stale_run = await _lock_analysis_run_for_worker(db, run_id, run_lease_token)
            if stale_run is None:
                await db.rollback()
                return await get_ai_run(db, run_id) or run
            run = stale_run
            await _mark_analysis_stale(
                db, run, "主数据目录在分析开始前发生变化，请重新运行"
            )
            return run
        current_file = await get_file_for_version(db, run.version_id)
        if (
            current_file is None
            or current_file.id != run.file_id
            or current_file.current_extraction_run_id != run.extraction_run_id
            or current_file.current_chunk_run_id != run.chunk_run_id
        ):
            stale_run = await _lock_analysis_run_for_worker(db, run_id, run_lease_token)
            if stale_run is None:
                await db.rollback()
                return await get_ai_run(db, run_id) or run
            run = stale_run
            await _mark_analysis_stale(db, run, "文件解析或分块版本已变化，请重新运行")
            return run
        segment_rows = await db.execute(
            select(DocumentTextSegment).where(
                DocumentTextSegment.file_id == run.file_id,
                DocumentTextSegment.extraction_run_id == run.extraction_run_id,
                DocumentTextSegment.is_deleted.is_(False),
            )
        )
        segments_by_order = {
            row.source_order: row
            for row in segment_rows.scalars()
            if row.source_order is not None
        }
        chunk_orders_by_id: dict[uuid.UUID, list[int]] = {}
        chunk_offsets_by_id: dict[
            uuid.UUID, list[tuple[int, int | None, int | None]]
        ] = {}
        if chunks:
            mapping_rows = await db.execute(
                select(DocumentChunkBlock)
                .where(
                    DocumentChunkBlock.chunk_id.in_([chunk.id for chunk in chunks]),
                    DocumentChunkBlock.is_deleted.is_(False),
                )
                .order_by(DocumentChunkBlock.chunk_id, DocumentChunkBlock.block_order)
            )
            for mapping in mapping_rows.scalars():
                chunk_orders_by_id.setdefault(mapping.chunk_id, []).append(
                    mapping.block_order
                )
                chunk_offsets_by_id.setdefault(mapping.chunk_id, []).append(
                    (mapping.block_order, mapping.char_start, mapping.char_end)
                )
        run.total_chunks = len(chunks)
        await db.flush()
        await db.commit()
        observation_by_key: dict[tuple[str, str], DocumentEntityObservation] = {}
        proposal_by_key: dict[tuple[str, str], MasterObjectProposal] = {}
        settings = get_settings()
        partial_error: str | None = (
            "未配置 QA AI 模型，本次仅执行编码/名称/别名规则匹配"
            if not settings.QA_AI_ENABLED or not settings.QA_AI_API_KEY
            else None
        )
        for chunk in chunks:
            # 不在此处 refresh：下面的 _lock_analysis_run_for_worker 已经以
            # FOR UPDATE 重读同一行并重新校验 worker_token/status，预检既多一次
            # SELECT（大文档按 chunk 累计），又违反 async 禁 refresh 规则。
            # 提交后再调用模型，避免网络等待期间让一个无锁的长事务占用连接。
            await db.commit()
            # 每个 chunk 开始前续租；大文档即使累计处理很久，也不会让
            # 调度器把仍在工作的 worker 当成失联任务回收。
            renewed_run = await _lock_analysis_run_for_worker(
                db, run_id, run_lease_token
            )
            if renewed_run is None:
                await db.rollback()
                return await get_ai_run(db, run_id) or run
            if renewed_run.status != AIAnalysisStatus.PROCESSING.value:
                await db.commit()
                return renewed_run
            renewed_run.lease_until = datetime.now(UTC) + timedelta(
                minutes=AI_LEASE_MINUTES
            )
            await db.flush()
            await db.commit()
            run = renewed_run
            deterministic = _deterministic_matches(chunk.content, masters, aliases)
            entities: list[dict[str, Any]] = []
            deterministic_groups: dict[tuple[str, str], dict[str, Any]] = {}
            term_master_ids: dict[str, set[uuid.UUID]] = {}
            for master, term, method, confidence in deterministic:
                normalized_term = normalize_text(term)
                term_master_ids.setdefault(normalized_term, set()).add(master.id)
                group = deterministic_groups.setdefault(
                    (normalized_term, master.object_type),
                    {
                        "mention_text": term,
                        "normalized_text": normalized_term,
                        "entity_type": master.object_type,
                        "quote": _quote(chunk.content, term),
                        "method": method,
                        "confidence": confidence,
                        "candidates": [],
                    },
                )
                group["confidence"] = max(float(group["confidence"]), confidence)
                group["candidates"].append(
                    {
                        "master": master,
                        "method": method,
                        "confidence": confidence,
                    }
                )
            for group in deterministic_groups.values():
                group["candidates"].sort(
                    key=lambda item: float(item["confidence"]), reverse=True
                )
                ambiguous = len(term_master_ids[group["normalized_text"]]) > 1
                for rank, candidate in enumerate(group["candidates"], start=1):
                    candidate["rank"] = rank
                    candidate["selected_by_default"] = not ambiguous and candidate[
                        "method"
                    ] in {"exact_code", "exact_alias"}
                    candidate["rationale"] = (
                        "存在同名/同别名歧义，请人工选择"
                        if ambiguous
                        else "编码/名称/别名精确命中"
                    )
                entities.append(group)

            # 规则匹配覆盖不了正文的大部分上下文时，仍让模型处理剩余语义；
            # 已被规则识别的实体会在下方去重，不让模型覆盖后端精确结果。
            matched_chars = sum(len(term) for _, term, _, _ in deterministic)
            has_ambiguity = any(len(ids) > 1 for ids in term_master_ids.values())
            needs_model = (
                not deterministic
                or has_ambiguity
                or len(chunk.content) > max(80, matched_chars * 4)
            )
            if needs_model and settings.QA_AI_ENABLED and settings.QA_AI_API_KEY:
                try:
                    deterministic_mentions = {
                        item["normalized_text"] for item in entities
                    }
                    for entity in await _model_entities(chunk):
                        mention_normalized = normalize_text(entity["mention_text"])
                        if mention_normalized in deterministic_mentions:
                            continue
                        entity["normalized_text"] = normalize_text(
                            entity.get("normalization_hint") or entity["mention_text"]
                        )
                        entity["method"] = "model"
                        matches = _fuzzy_match(
                            entity["normalized_text"],
                            masters,
                            aliases,
                            entity_type=entity["entity_type"],
                        )
                        entity["confidence"] = (
                            max(0.65, min(0.89, matches[0][2] * 0.9))
                            if matches
                            else 0.65
                        )
                        entity["candidates"] = [
                            {
                                "master": master,
                                "method": "model_fuzzy",
                                "confidence": min(0.89, max(0.5, score * 0.9)),
                                "rank": rank,
                                "selected_by_default": False,
                                "rationale": f"模型实体经后端受限模糊召回：{matched_term}",
                            }
                            for rank, (master, matched_term, score) in enumerate(
                                matches, start=1
                            )
                        ]
                        entities.append(entity)
                except Exception as exc:
                    # 单 chunk 失败不抹掉规则结果；最终标记 partial 并保留错误摘要。
                    partial_error = f"模型调用失败：{type(exc).__name__}"
            # 模型调用不持有行锁；返回后重新按 token 加锁，保证下面的
            # observation/suggestion/proposal 写入与租约校验在同一事务内。
            locked_run = await _lock_analysis_run_for_worker(
                db, run_id, run_lease_token
            )
            if locked_run is None:
                await db.rollback()
                return await get_ai_run(db, run_id) or run
            run = locked_run
            if run.status != AIAnalysisStatus.PROCESSING.value:
                await db.commit()
                return run
            if partial_error:
                run.error = partial_error
            for entity in entities:
                # 同一实体的去重键是整个运行级别的 (规范化文本, 实体类型)。
                # 不含 chunk/quote：分块会把表头复制进每个派生块、PDF 页眉
                # 页脚逐页保留，同一实体天然跨多个 chunk 出现；按 chunk 去重
                # 会让候选卡片和未匹配实体在审核端重复出现。
                key = (entity["normalized_text"], entity["entity_type"])
                existing_observation = observation_by_key.get(key)
                # ``source_start/source_end`` 是便于范围检索的摘要，并不
                # 表示 chunk 中所有连续的 raw order：表格跨块时会复制表头，
                # 未来版面解析也可能留下非连续 block。必须按实际映射集合
                # 取证据，否则重复实体可能错误指向前一块的行。
                chunk_block_orders = list(
                    dict.fromkeys(chunk_orders_by_id.get(chunk.id, []))
                )
                # 兼容尚未持久化映射的旧测试/过渡数据；正式新链路总是
                # 从 document_chunk_blocks 读取，不依赖 ORM 不存在的字段。
                if not chunk_block_orders:
                    chunk_block_orders = list(
                        dict.fromkeys(getattr(chunk, "raw_block_orders", ()))
                    )
                source_rows = [
                    segments_by_order[order]
                    for order in chunk_block_orders
                    if order in segments_by_order
                ]
                fallback_source_order = (
                    chunk_block_orders[0] if chunk_block_orders else chunk.source_start
                )
                normalized_mention = normalize_text(entity["mention_text"])
                source = next(
                    (
                        row
                        for row in source_rows
                        if normalized_mention in normalize_text(row.content)
                    ),
                    source_rows[0] if source_rows else None,
                )
                offset_rows = chunk_offsets_by_id.get(chunk.id, [])
                if not offset_rows:
                    offset_rows = list(getattr(chunk, "block_offsets", ()))
                evidence_offsets = next(
                    (
                        (start, end)
                        for block_order, start, end in offset_rows
                        if source is not None and block_order == source.source_order
                    ),
                    (None, None),
                )
                evidence_hash = _fingerprint(
                    {
                        # 证据哈希故意不包含每次运行生成的 UUID；同一文件、
                        # 同一解析/分块版本重建后仍应得到相同哈希。运行 ID
                        # 已单独保存在 observation/provenance 字段中。
                        "file_sha256": current_file.sha256,
                        "parser_version": current_file.parser_version,
                        "chunk_version": CHUNK_VERSION,
                        "chunk_content_hash": chunk.content_hash,
                        "raw_block_hash": source.text_hash if source else None,
                        "source_order": source.source_order
                        if source
                        else fallback_source_order,
                        "locator": source.locator
                        if source
                        else f"chunk:{chunk.chunk_order}",
                        "char_start": evidence_offsets[0],
                        "char_end": evidence_offsets[1],
                        "mention_text": entity["mention_text"],
                        "normalized_text": entity["normalized_text"],
                        "quote": entity["quote"],
                    }
                )
                candidates = entity.get("candidates") or []
                location_entry = {
                    "evidence_hash": evidence_hash,
                    "locator": source.locator
                    if source
                    else f"chunk:{chunk.chunk_order}",
                    "location": _evidence_location_metadata(source),
                }
                if existing_observation is not None:
                    # 重复出现：只合并证据位置，不再新建 observation/候选。
                    # 候选对同一 key 跨 chunk 是确定的（精确匹配取决于目录、
                    # 模糊召回只依赖规范化文本），无需逐块重建；唯一例外是
                    # 首块未召回候选而本块召回——补挂 suggestion，避免“首次
                    # 未匹配”永久压制更好的结果。
                    metadata = {**(existing_observation.observation_metadata or {})}
                    metadata["evidence_locations"] = _merge_evidence_locations(
                        list(metadata.get("evidence_locations") or []), location_entry
                    )
                    if candidates and not int(metadata.get("candidate_count") or 0):
                        for candidate in candidates:
                            db.add(
                                DocumentRelationSuggestion(
                                    analysis_run_id=run.id,
                                    observation_id=existing_observation.id,
                                    master_object_id=candidate["master"].id,
                                    relation_type=RelationType.APPLIES_TO.value,
                                    match_method=candidate["method"],
                                    rank=int(candidate["rank"]),
                                    confidence=float(candidate["confidence"]),
                                    selected_by_default=bool(
                                        candidate["selected_by_default"]
                                    ),
                                    status=AISuggestionStatus.PENDING.value,
                                    rationale=candidate["rationale"],
                                    created_by=run.requested_by,
                                    updated_by=run.requested_by,
                                )
                            )
                        metadata["candidate_count"] = len(candidates)
                        existing_observation.confidence = max(
                            float(existing_observation.confidence or 0),
                            float(entity["confidence"]),
                        )
                        existing_observation.extraction_method = entity["method"]
                        if entity.get("normalization_hint"):
                            existing_observation.normalization_hint = entity[
                                "normalization_hint"
                            ]
                        existing_observation.updated_by = run.requested_by
                    # JSON 列必须整体重新赋值，原地修改不会被 ORM 检测。
                    existing_observation.observation_metadata = metadata
                    continue
                observation = DocumentEntityObservation(
                    analysis_run_id=run.id,
                    chunk_id=chunk.id,
                    raw_block_id=source.id if source else None,
                    mention_text=entity["mention_text"],
                    normalized_text=entity["normalized_text"],
                    entity_type=entity["entity_type"],
                    quote=entity["quote"],
                    evidence_hash=evidence_hash,
                    locator=source.locator if source else f"chunk:{chunk.chunk_order}",
                    page_number=source.page_number if source else chunk.page_start,
                    paragraph_index=source.paragraph_index if source else None,
                    table_index=source.table_index if source else None,
                    row_index=source.row_index if source else None,
                    column_index=source.column_index if source else None,
                    source_order=source.source_order
                    if source
                    else fallback_source_order,
                    confidence=float(entity["confidence"]),
                    extraction_method=entity["method"],
                    normalization_hint=entity.get("normalization_hint"),
                    observation_metadata={
                        "chunk_order": chunk.chunk_order,
                        "chunk_content_hash": chunk.content_hash,
                        "char_start": evidence_offsets[0],
                        "char_end": evidence_offsets[1],
                        "raw_block_text_hash": source.text_hash if source else None,
                        "candidate_count": len(candidates),
                        "evidence_location": location_entry["location"],
                        "evidence_locations": [location_entry],
                    },
                    created_by=run.requested_by,
                    updated_by=run.requested_by,
                )
                db.add(observation)
                await db.flush()
                observation_by_key[key] = observation
                for candidate in candidates:
                    db.add(
                        DocumentRelationSuggestion(
                            analysis_run_id=run.id,
                            observation_id=observation.id,
                            master_object_id=candidate["master"].id,
                            relation_type=RelationType.APPLIES_TO.value,
                            match_method=candidate["method"],
                            rank=int(candidate["rank"]),
                            confidence=float(candidate["confidence"]),
                            selected_by_default=bool(candidate["selected_by_default"]),
                            status=AISuggestionStatus.PENDING.value,
                            rationale=candidate["rationale"],
                            created_by=run.requested_by,
                            updated_by=run.requested_by,
                        )
                    )
                evidence = {
                    "locator": observation.locator,
                    "quote": observation.quote,
                    "evidence_hash": observation.evidence_hash,
                    "evidence_location": location_entry["location"],
                }
                # authoritative 文件允许对“唯一、高相似度模型召回”的规范化
                # 名称提出字段变更建议；仍只落提案，不直接修改主数据。
                if (
                    candidates
                    and len(candidates) == 1
                    and run.source_policy == AIAuthorityPolicy.AUTHORITATIVE.value
                    and entity["method"] == "model"
                    and entity.get("normalization_hint")
                    and candidates[0]["confidence"] >= 0.81
                    and normalize_text(entity["normalization_hint"])
                    != normalize_text(candidates[0]["master"].name)
                ):
                    target = candidates[0]["master"]
                    proposed_name = str(entity["normalization_hint"])[:200]
                    proposal_key = (f"update:{target.id}", "name")
                    proposal = proposal_by_key.get(proposal_key)
                    if proposal is None:
                        base_snapshot = {
                            "id": str(target.id),
                            "name": target.name,
                            "description": target.description,
                            "status": target.status,
                            "aliases": sorted(
                                aliases.get(target.id, []), key=normalize_text
                            ),
                            "updated_at": target.updated_at.isoformat()
                            if target.updated_at
                            else None,
                        }
                        proposal = MasterObjectProposal(
                            analysis_run_id=run.id,
                            observation_id=observation.id,
                            proposal_type="update",
                            target_master_object_id=target.id,
                            object_type=target.object_type,
                            proposed_payload={"name": proposed_name},
                            field_diffs={
                                "name": {"from": target.name, "to": proposed_name}
                            },
                            evidence=[evidence],
                            base_snapshot=base_snapshot,
                            base_fingerprint=_fingerprint(base_snapshot),
                            status=AIProposalStatus.PENDING.value,
                            created_by=run.requested_by,
                            updated_by=run.requested_by,
                        )
                        proposal_by_key[proposal_key] = proposal
                        db.add(proposal)
                    else:
                        existing_evidence = list(proposal.evidence or [])
                        if (
                            len(existing_evidence) < MAX_PROPOSAL_EVIDENCE
                            and evidence not in existing_evidence
                        ):
                            proposal.evidence = [*existing_evidence, evidence]
                if (
                    not candidates
                    and run.source_policy == AIAuthorityPolicy.AUTHORITATIVE.value
                ):
                    payload = {
                        "object_type": entity["entity_type"],
                        "code": entity["mention_text"][:100],
                        "name": (
                            entity.get("normalization_hint") or entity["mention_text"]
                        )[:200],
                        "description": None,
                        "aliases": [entity["mention_text"][:200]],
                    }
                    proposal_key = (
                        entity["normalized_text"],
                        entity["entity_type"],
                    )
                    proposal = proposal_by_key.get(proposal_key)
                    if proposal is None:
                        proposal = MasterObjectProposal(
                            analysis_run_id=run.id,
                            observation_id=observation.id,
                            proposal_type="create",
                            object_type=entity["entity_type"],
                            proposed_payload=payload,
                            evidence=[evidence],
                            status=AIProposalStatus.PENDING.value,
                            created_by=run.requested_by,
                            updated_by=run.requested_by,
                        )
                        proposal_by_key[proposal_key] = proposal
                        db.add(proposal)
                    else:
                        existing_evidence = list(proposal.evidence or [])
                        if (
                            len(existing_evidence) < MAX_PROPOSAL_EVIDENCE
                            and evidence not in existing_evidence
                        ):
                            proposal.evidence = [*existing_evidence, evidence]
            run.processed_chunks += 1
            await db.flush()
            await db.commit()
        # 统计使用数据库查询，避免依赖 flush 前的 collection 状态。
        obs_count = await db.scalar(
            select(func.count())
            .select_from(DocumentEntityObservation)
            .where(
                DocumentEntityObservation.analysis_run_id == run.id,
                DocumentEntityObservation.is_deleted.is_(False),
            )
        )
        sug_count = await db.scalar(
            select(func.count())
            .select_from(DocumentRelationSuggestion)
            .where(
                DocumentRelationSuggestion.analysis_run_id == run.id,
                DocumentRelationSuggestion.is_deleted.is_(False),
            )
        )
        prop_count = await db.scalar(
            select(func.count())
            .select_from(MasterObjectProposal)
            .where(
                MasterObjectProposal.analysis_run_id == run.id,
                MasterObjectProposal.is_deleted.is_(False),
            )
        )
        final_run = await _lock_analysis_run_for_worker(db, run_id, run_lease_token)
        if final_run is None:
            await db.rollback()
            return await get_ai_run(db, run_id) or run
        run = final_run
        if run.status != AIAnalysisStatus.PROCESSING.value:
            await db.commit()
            return run
        run.entity_count = int(obs_count or 0)
        run.suggestion_count = int(sug_count or 0)
        run.proposal_count = int(prop_count or 0)
        if partial_error:
            run.error = partial_error
        final_stale_reason = await _analysis_stale_reason(db, run)
        if final_stale_reason:
            await _mark_analysis_stale(db, run, final_stale_reason)
            return run
        run.status = (
            AIAnalysisStatus.PARTIAL.value
            if run.error
            else AIAnalysisStatus.READY.value
        )
        run.finished_at = datetime.now(UTC)
        run.lease_until = None
        run.worker_token = None
        await db.flush()
        await _audit(
            db,
            action="ai_analysis_completed"
            if run.status == AIAnalysisStatus.READY.value
            else "ai_analysis_partial",
            user=None,
            resource_type="document_ai_analysis_run",
            resource_id=run.id,
            new_value={
                "status": run.status,
                "entity_count": run.entity_count,
                "suggestion_count": run.suggestion_count,
                "proposal_count": run.proposal_count,
            },
            extra={
                "input_fingerprint": run.input_fingerprint,
                "catalog_fingerprint": run.catalog_fingerprint,
                "model": run.model,
                "prompt_version": run.prompt_version,
                "schema_version": run.schema_version,
            },
        )
        return run
    except asyncio.CancelledError:
        # wait_for/服务停机取消时只回滚当前事务，保留已提交的 worker
        # token 与租约，让调度器安全回收；不能在这里清理可能已转交给
        # 新 worker 的租约。
        await db.rollback()
        raise
    except Exception as exc:
        # 模型调用/数据库处理期间租约可能已被回收并由新 worker 继续。
        # 旧 worker 不能直接把 ORM 中的 run 写成 FAILED 或清除新租约。
        # 回滚本次事务后，使用 worker token + 行锁确认仍由自己持有；
        # token 不匹配时只返回数据库最新状态，不做任何写入。
        # AIOutputError 可能携带截断后的原始模型响应；错误审计只保留
        # 异常类型，绝不把 prompt/模型响应写入数据库。其它传输错误也仅
        # 保留短摘要，避免 URL/header 等实现细节扩散到审计记录。
        if isinstance(exc, AIOutputError):
            error_text = f"{type(exc).__name__}"
        else:
            detail = " ".join(str(exc).split())[:240]
            error_text = (
                f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__
            )
        try:
            await db.rollback()
            statement = select(DocumentAIAnalysisRun).where(
                DocumentAIAnalysisRun.id == run_id,
                DocumentAIAnalysisRun.is_deleted.is_(False),
            )
            if run_lease_token is not None:
                statement = statement.where(
                    DocumentAIAnalysisRun.worker_token == run_lease_token
                )
            else:
                # 没有 token 的兼容性调用只能在仍处于 processing 时收尾，
                # 且要求数据库 token 仍为空，避免覆盖已被调度器接管的运行。
                statement = statement.where(
                    DocumentAIAnalysisRun.status == AIAnalysisStatus.PROCESSING.value,
                    DocumentAIAnalysisRun.worker_token.is_(None),
                )
            result = await db.execute(statement.with_for_update())
            claimed_run = result.scalar_one_or_none()
            if claimed_run is None:
                return await get_ai_run(db, run_id) or run
            if claimed_run.status != AIAnalysisStatus.PROCESSING.value:
                return claimed_run
            # 非租约异常也必须消耗一次有限重试额度；否则调度器会把
            # failed 运行反复拾起，或让失败状态与 retry_count 不一致。
            next_retry = int(claimed_run.retry_count or 0) + 1
            claimed_run.status = AIAnalysisStatus.FAILED.value
            claimed_run.error = error_text
            claimed_run.retry_count = next_retry
            claimed_run.finished_at = datetime.now(UTC)
            claimed_run.lease_until = None
            claimed_run.worker_token = None
            await db.flush()
            await _audit(
                db,
                action="ai_analysis_failed",
                user=None,
                resource_type="document_ai_analysis_run",
                resource_id=claimed_run.id,
                new_value={
                    "status": claimed_run.status,
                    "error": error_text,
                    "retry_count": next_retry,
                },
                extra={
                    "input_fingerprint": claimed_run.input_fingerprint,
                    "catalog_fingerprint": claimed_run.catalog_fingerprint,
                    "model": claimed_run.model,
                    "prompt_version": claimed_run.prompt_version,
                    "schema_version": claimed_run.schema_version,
                    "retry_count": next_retry,
                },
            )
            await db.commit()
            return claimed_run
        except Exception:
            # 收尾失败时保留数据库现有租约，交给调度器按 lease_until 回收；
            # 尽量读取最新行，绝不再清理未知 worker 的 token。
            logger.exception(
                "QA AI analysis failure finalization failed",
                extra={"run_id": str(run_id)},
            )
            try:
                await db.rollback()
                return await get_ai_run(db, run_id) or run
            except Exception:
                return run


async def _analysis_stale_reason(
    db: AsyncSession, run: DocumentAIAnalysisRun
) -> str | None:
    """校验分析结果仍对应当前解析、目录快照和来源策略。"""

    current_file = await get_file_for_version(db, run.version_id)
    if (
        current_file is None
        or current_file.id != run.file_id
        or current_file.current_extraction_run_id != run.extraction_run_id
        or current_file.current_chunk_run_id != run.chunk_run_id
        or current_file.extraction_status != "ready"
    ):
        return "文件解析或分块版本已变化，请重新运行"
    _, _, catalog_fingerprint = await _catalog(db)
    if catalog_fingerprint != run.catalog_fingerprint:
        return "主数据目录已变化，请重新运行"
    version = await get_version(db, run.version_id)
    if version is None or not version.approved_declared:
        return "文件版本已不再满足批准/登记条件，请重新运行"
    if version.status == VersionStatus.INACTIVE.value:
        return "文件版本已停用，请重新运行"
    document = await db.get(Document, version.document_id) if version else None
    if (
        document is None
        or document.is_deleted
        or document.status != RecordStatus.ACTIVE.value
    ):
        return "文件台账已停用，请重新运行"
    doc_type = (
        await db.get(DocumentType, document.document_type_id) if document else None
    )
    if (
        doc_type is None
        or doc_type.is_deleted
        or doc_type.status != RecordStatus.ACTIVE.value
    ):
        return "文件类型已停用，请重新运行"
    current_policy = (
        getattr(doc_type, "ai_source_policy", None) if doc_type is not None else None
    )
    if current_policy != run.source_policy:
        return "文件类型的 AI 来源策略已变化，请重新运行"
    return None


async def _lock_analysis_file(
    db: AsyncSession, run: DocumentAIAnalysisRun
) -> DocumentFile | None:
    """锁定分析对应文件，避免解析提交与确认/审批交错。"""

    result = await db.execute(
        select(DocumentFile)
        .where(
            DocumentFile.id == run.file_id,
            DocumentFile.is_deleted.is_(False),
        )
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def _lock_master_proposal(
    db: AsyncSession, proposal_id: uuid.UUID
) -> MasterObjectProposal | None:
    """在 analysis run 之后锁提案，统一 AI 决策路径的锁顺序。"""

    result = await db.execute(
        select(MasterObjectProposal)
        .where(
            MasterObjectProposal.id == proposal_id,
            MasterObjectProposal.is_deleted.is_(False),
        )
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def _mark_analysis_stale(
    db: AsyncSession,
    run: DocumentAIAnalysisRun,
    reason: str,
    *,
    user: User | None = None,
) -> None:
    run.status = AIAnalysisStatus.STALE.value
    run.error = reason
    run.finished_at = datetime.now(UTC)
    run.lease_until = None
    run.worker_token = None
    # 派生候选/提案仍作为审计事实保留，但不允许在输入失效后继续
    # 发布。正式关系和主数据表都不会被这里直接修改。
    await db.execute(
        update(DocumentRelationSuggestion)
        .where(
            DocumentRelationSuggestion.analysis_run_id == run.id,
            DocumentRelationSuggestion.status == AISuggestionStatus.PENDING.value,
            DocumentRelationSuggestion.is_deleted.is_(False),
        )
        .values(status=AISuggestionStatus.STALE.value)
    )
    await db.execute(
        update(MasterObjectProposal)
        .where(
            MasterObjectProposal.analysis_run_id == run.id,
            MasterObjectProposal.status == AIProposalStatus.PENDING.value,
            MasterObjectProposal.is_deleted.is_(False),
        )
        .values(
            status=AIProposalStatus.STALE.value,
            conflicts=[{"reason": reason}],
        )
    )
    await db.flush()
    await _audit(
        db,
        action="ai_analysis_stale",
        user=user,
        resource_type="document_ai_analysis_run",
        resource_id=run.id,
        new_value={"status": run.status, "reason": reason},
        extra={
            "input_fingerprint": run.input_fingerprint,
            "catalog_fingerprint": run.catalog_fingerprint,
            "model": run.model,
            "prompt_version": run.prompt_version,
            "schema_version": run.schema_version,
        },
    )


async def analysis_to_dict(
    db: AsyncSession, run: DocumentAIAnalysisRun, *, user: User | None = None
) -> dict[str, Any]:
    if run.status in {AIAnalysisStatus.READY.value, AIAnalysisStatus.PARTIAL.value}:
        stale_reason = await _analysis_stale_reason(db, run)
        if stale_reason:
            # 读接口也会触发失效（打开面板即作废待审提案），因此把发起人一起
            # 写进审计：否则只剩一条 user=None 的不可归属记录。
            await _mark_analysis_stale(db, run, stale_reason, user=user)
    observations = await db.execute(
        select(DocumentEntityObservation)
        .where(
            DocumentEntityObservation.analysis_run_id == run.id,
            DocumentEntityObservation.is_deleted.is_(False),
        )
        .order_by(
            DocumentEntityObservation.source_order, DocumentEntityObservation.created_at
        )
    )
    suggestions = await db.execute(
        select(DocumentRelationSuggestion)
        .where(
            DocumentRelationSuggestion.analysis_run_id == run.id,
            DocumentRelationSuggestion.is_deleted.is_(False),
        )
        .order_by(
            DocumentRelationSuggestion.rank,
            DocumentRelationSuggestion.confidence.desc(),
        )
    )
    proposals = await db.execute(
        select(MasterObjectProposal)
        .where(
            MasterObjectProposal.analysis_run_id == run.id,
            MasterObjectProposal.is_deleted.is_(False),
        )
        .order_by(MasterObjectProposal.created_at)
    )
    return {
        "id": run.id,
        "version_id": run.version_id,
        "file_id": run.file_id,
        "extraction_run_id": run.extraction_run_id,
        "chunk_run_id": run.chunk_run_id,
        "status": run.status,
        "provider": run.provider,
        "model": run.model,
        "prompt_version": run.prompt_version,
        "schema_version": run.schema_version,
        "source_policy": run.source_policy,
        "catalog_fingerprint": run.catalog_fingerprint,
        "input_fingerprint": run.input_fingerprint,
        "processed_chunks": run.processed_chunks,
        "total_chunks": run.total_chunks,
        "entity_count": run.entity_count,
        "suggestion_count": run.suggestion_count,
        "proposal_count": run.proposal_count,
        "error": run.error,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "observations": [row for row in observations.scalars()],
        "suggestions": [row for row in suggestions.scalars()],
        "proposals": [row for row in proposals.scalars()],
    }


async def confirm_relations(
    db: AsyncSession,
    run_id: uuid.UUID,
    *,
    accepted_suggestion_ids: list[uuid.UUID],
    manual_master_object_ids: list[uuid.UUID],
    remove_master_object_ids: list[uuid.UUID],
    user: User | None = None,
) -> list[Any]:
    run = await get_ai_run(db, run_id)
    if run is None:
        raise NotFoundException("AI 分析运行", str(run_id))
    version = await get_version(db, run.version_id)
    if version is None:
        raise NotFoundException("文件版本", str(run.version_id))
    if version.status not in {
        VersionStatus.REGISTERED.value,
        VersionStatus.CURRENT.value,
    }:
        raise AppException(
            status_code=409, message="只有登记或现行版本才能确认文件关联"
        )
    if run.status not in {AIAnalysisStatus.READY.value, AIAnalysisStatus.PARTIAL.value}:
        raise AppException(status_code=409, message="AI 分析尚未完成，不能确认关联")
    stale_reason = await _analysis_stale_reason(db, run)
    if stale_reason:
        await _mark_analysis_stale(db, run, stale_reason, user=user)
        # 状态必须在返回 409 前落库，否则请求级 rollback 会丢掉 stale 标记。
        await db.commit()
        raise AppException(status_code=409, message=stale_reason)
    from app.modules.qa.service import (
        _get_version_with_document_lock,
        set_relations_append,
    )

    locked_version = await _get_version_with_document_lock(db, version.id)
    if locked_version is None or locked_version.status not in {
        VersionStatus.REGISTERED.value,
        VersionStatus.CURRENT.value,
    }:
        raise AppException(
            status_code=409, message="文件版本已是历史或停用，不能确认关联"
        )
    # 与 process_file 使用同一把 document_files 行锁。拿到锁后再检查当前
    # 解析/分块指针，并一直持有到正式关系写入提交，避免检查通过后新解析
    # 恰好切换 current_* 指针而把旧候选写入正式关系。
    locked_file = await _lock_analysis_file(db, run)
    if (
        locked_file is None
        or locked_file.current_extraction_run_id != run.extraction_run_id
        or locked_file.current_chunk_run_id != run.chunk_run_id
    ):
        reason = "文件解析或分块版本已变化，请重新运行"
        await _mark_analysis_stale(db, run, reason, user=user)
        await db.commit()
        raise AppException(status_code=409, message=reason)
    # 文件锁建立后重新锁定并读取分析运行，避免并发 worker 在前一次
    # status 检查之后把 READY 运行标为 STALE/FAILED，而本请求仍沿用旧
    # ORM 快照写入正式关系。
    locked_run_result = await db.execute(
        select(DocumentAIAnalysisRun)
        .where(
            DocumentAIAnalysisRun.id == run.id,
            DocumentAIAnalysisRun.is_deleted.is_(False),
        )
        .with_for_update()
    )
    locked_run = locked_run_result.scalar_one_or_none()
    if locked_run is None:
        raise NotFoundException("AI 分析运行", str(run.id))
    run = locked_run
    if run.status not in {AIAnalysisStatus.READY.value, AIAnalysisStatus.PARTIAL.value}:
        raise AppException(status_code=409, message="AI 分析已失效，不能确认关联")
    # 版本行锁拿到后再次校验输入；前一次检查与加锁之间可能刚好完成了
    # 新解析、主数据目录变更或文件类型策略调整，不能让旧分析覆盖正式关系。
    stale_reason = await _analysis_stale_reason(db, run)
    if stale_reason:
        await _mark_analysis_stale(db, run, stale_reason, user=user)
        await db.commit()
        raise AppException(status_code=409, message=stale_reason)
    # 只允许对仍待审核的候选作出首次决定。已接受、已拒绝或因输入变化
    # 过期的候选都不能被后续请求“复活”；重复提交应重新运行分析或使用
    # 纯人工关系维护入口。
    all_suggestions_result = await db.execute(
        select(DocumentRelationSuggestion)
        .where(
            DocumentRelationSuggestion.analysis_run_id == run.id,
            DocumentRelationSuggestion.is_deleted.is_(False),
        )
        .with_for_update()
    )
    all_suggestions = list(all_suggestions_result.scalars())
    pending_suggestions = [
        item
        for item in all_suggestions
        if item.status == AISuggestionStatus.PENDING.value
    ]
    if all_suggestions and not pending_suggestions:
        raise AppException(
            status_code=409, message="本次分析的候选关联已经确认，不能重复提交"
        )
    accepted = [
        item for item in pending_suggestions if item.id in set(accepted_suggestion_ids)
    ]
    accepted_ids = {row.id for row in accepted}
    if len(accepted_ids) != len(set(accepted_suggestion_ids)):
        raise AppException(
            status_code=409,
            message="存在不属于本次分析、已处理或已过期的候选关联",
        )
    decided_at = datetime.now(UTC)
    for suggestion in pending_suggestions:
        suggestion.status = (
            AISuggestionStatus.ACCEPTED.value
            if suggestion.id in accepted_ids
            else AISuggestionStatus.REJECTED.value
        )
        suggestion.decided_by = _actor_id(user)
        suggestion.decided_at = decided_at
    existing = await db.execute(
        select(DocumentMasterLink).where(
            DocumentMasterLink.version_id == locked_version.id,
            DocumentMasterLink.is_deleted.is_(False),
        )
    )
    current_ids = {row.master_object_id for row in existing.scalars()}
    additions = {row.master_object_id for row in accepted} | set(
        manual_master_object_ids
    )
    final_ids = (current_ids | additions) - set(remove_master_object_ids)
    # 传入的是「current + additions - removals」最终集合，需显式声明
    # 清理语义：不在集合里的既有关系按用户勾选移除软删除。
    rows = await set_relations_append(
        db, locked_version.id, sorted(final_ids, key=str), user, prune_missing=True
    )
    await _audit(
        db,
        action="ai_relations_confirmed",
        user=user,
        resource_type="document_ai_analysis_run",
        resource_id=run.id,
        old_value={"count": len(current_ids)},
        new_value={
            "count": len(rows),
            "accepted_suggestion_count": len(accepted),
            "rejected_suggestion_count": len(pending_suggestions) - len(accepted),
            "manual_count": len(manual_master_object_ids),
            "removed_count": len(remove_master_object_ids),
        },
        extra={
            **_analysis_audit_context(run),
            "version_id": str(locked_version.id),
            "accepted_suggestion_ids": [str(item) for item in accepted_ids],
            "rejected_suggestion_ids": [
                str(item.id)
                for item in pending_suggestions
                if item.id not in accepted_ids
            ],
            "manual_master_object_ids": [
                str(item) for item in manual_master_object_ids
            ],
            "remove_master_object_ids": [
                str(item) for item in remove_master_object_ids
            ],
        },
    )
    return rows


async def list_proposal_page(
    db: AsyncSession, *, status: str | None = None, page: int = 1, page_size: int = 50
) -> tuple[list[dict[str, Any]], int]:
    """提案箱分页，返回已序列化的 dict。

    证据本身只引用段落，审核人首先要知道「来自哪个文件」：按
    proposal → analysis run → 版本 → 文件回填 ``document_name`` 等字段
    （生成时写入的新数据和未写入的存量提案都经这里统一补齐）。在
    序列化后的 dict 上合并，避免原地修改 ORM 的 JSON 字段被中间件
    顺手提交。
    """
    from app.modules.qa.schemas import MasterObjectProposalOut

    rows, total = await list_proposals(
        db, status=status, page=page, page_size=page_size
    )
    document_by_proposal: dict[uuid.UUID, dict[str, str]] = {}
    if rows:
        document_result = await db.execute(
            select(
                MasterObjectProposal.id,
                Document.id,
                Document.title,
                Document.document_no,
            )
            .join(
                DocumentAIAnalysisRun,
                DocumentAIAnalysisRun.id == MasterObjectProposal.analysis_run_id,
            )
            .join(
                DocumentVersion, DocumentVersion.id == DocumentAIAnalysisRun.version_id
            )
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(MasterObjectProposal.id.in_([row.id for row in rows]))
        )
        for proposal_id, document_id, title, document_no in document_result:
            document_by_proposal[proposal_id] = {
                "document_id": str(document_id),
                "document_name": title,
                "document_no": document_no,
            }
    items: list[dict[str, Any]] = []
    for row in rows:
        item = MasterObjectProposalOut.model_validate(row).model_dump(mode="json")
        document = document_by_proposal.get(row.id)
        if document and item.get("evidence"):
            item["evidence"] = [
                {**evidence, **document} for evidence in item["evidence"]
            ]
        items.append(item)
    return items, total


def _validate_master_payload(model: type[Any], data: Any) -> Any:
    """校验审批载荷；失败转 422。

    直接 `model_validate` 抛出的 pydantic ``ValidationError`` 不是
    ``AppException``，会落到全局兜底处理器变成 500，既丢掉了字段级信息、
    也不写审计。AI 生成的 proposed_payload 本身就可能带非法 name/object_type，
    所以这条路径不需要用户恶意就能触发。
    """

    try:
        return model.model_validate(data)
    except ValidationError as exc:
        details = exc.errors()
        first: dict[str, Any] = dict(details[0]) if details else {}
        location = ".".join(str(part) for part in first.get("loc", ()))
        message = f"提案内容不合法：{location} {first.get('msg', '')}".strip()
        raise AppException(status_code=422, message=message) from exc


async def approve_proposal(
    db: AsyncSession,
    proposal_id: uuid.UUID,
    payload: dict[str, Any] | None,
    user: User | None = None,
) -> tuple[MasterObjectProposal, str | None]:
    # 先无锁读取来源运行 ID；正式决策按 file -> analysis run -> proposal
    # 顺序加锁。若先锁 proposal，再等待 worker 已锁住的 analysis run，
    # worker 同时批量 stale proposal 时会形成反向锁序和死锁窗口。
    proposal_result = await db.execute(
        select(MasterObjectProposal).where(
            MasterObjectProposal.id == proposal_id,
            MasterObjectProposal.is_deleted.is_(False),
        )
    )
    proposal = proposal_result.scalar_one_or_none()
    if proposal is None:
        raise NotFoundException("主数据提案", str(proposal_id))
    if proposal.status != AIProposalStatus.PENDING.value:
        raise AppException(status_code=409, message="该提案已经处理，不能重复审批")
    analysis_run = await get_ai_run(db, proposal.analysis_run_id)
    if analysis_run is None:
        proposal = await _lock_master_proposal(db, proposal_id)
        if proposal is None:
            raise NotFoundException("主数据提案", str(proposal_id))
        if proposal.status != AIProposalStatus.PENDING.value:
            raise AppException(status_code=409, message="该提案已经处理，不能重复审批")
        proposal.status = AIProposalStatus.STALE.value
        proposal.conflicts = [{"reason": "来源分析运行不存在"}]
        await _audit(
            db,
            action="ai_proposal_stale",
            user=user,
            resource_type="master_object_proposal",
            resource_id=proposal.id,
            new_value={"status": proposal.status, "reason": "analysis_run_missing"},
            extra={"analysis_run_id": str(proposal.analysis_run_id)},
        )
        await db.commit()
        raise AppException(
            status_code=409, message="提案来源分析运行不存在，已标记过期"
        )
    # 提案通过后会在同一事务内自动追加文件关联，那里要先锁 document 行。
    # 这里提前按 confirm_relations 的统一顺序（document → file）拿住锁，
    # 避免与「先锁 document 再锁 file」的人工关联确认形成反向锁序。
    from app.modules.qa.service import _get_version_with_document_lock

    await _get_version_with_document_lock(db, analysis_run.version_id)
    # 锁住对应文件直到提案发布完成，和解析 worker 的 current_* 更新形成
    # 同一并发边界；否则 stale 检查通过后新解析可能立即让提案过期。
    locked_file = await _lock_analysis_file(db, analysis_run)
    file_is_current = not (
        locked_file is None
        or locked_file.current_extraction_run_id != analysis_run.extraction_run_id
        or locked_file.current_chunk_run_id != analysis_run.chunk_run_id
    )
    locked_analysis_result = await db.execute(
        select(DocumentAIAnalysisRun)
        .where(
            DocumentAIAnalysisRun.id == analysis_run.id,
            DocumentAIAnalysisRun.is_deleted.is_(False),
        )
        .with_for_update()
    )
    locked_analysis = locked_analysis_result.scalar_one_or_none()
    if locked_analysis is None:
        proposal = await _lock_master_proposal(db, proposal_id)
        if proposal is None:
            raise NotFoundException("主数据提案", str(proposal_id))
        if proposal.status != AIProposalStatus.PENDING.value:
            raise AppException(status_code=409, message="该提案已经处理，不能重复审批")
        proposal.status = AIProposalStatus.STALE.value
        proposal.conflicts = [{"reason": "来源分析运行不存在"}]
        await db.commit()
        raise AppException(
            status_code=409, message="提案来源分析运行不存在，已标记过期"
        )
    analysis_run = locked_analysis
    proposal = await _lock_master_proposal(db, proposal_id)
    if proposal is None:
        raise NotFoundException("主数据提案", str(proposal_id))
    if proposal.status != AIProposalStatus.PENDING.value:
        raise AppException(status_code=409, message="该提案已经处理，不能重复审批")
    if user is not None:
        required_permission = (
            "qa:master:create"
            if proposal.proposal_type == "create"
            else "qa:master:update"
        )
        permissions = await get_user_permissions(str(user.id), db)
        if required_permission not in permissions:
            raise ForbiddenException(f"审批该提案需要权限: {required_permission}")
    if analysis_run.status not in {
        AIAnalysisStatus.READY.value,
        AIAnalysisStatus.PARTIAL.value,
    }:
        proposal.status = AIProposalStatus.STALE.value
        proposal.conflicts = [{"reason": f"来源分析状态为 {analysis_run.status}"}]
        await _audit(
            db,
            action="ai_proposal_stale",
            user=user,
            resource_type="master_object_proposal",
            resource_id=proposal.id,
            new_value={
                "status": proposal.status,
                "reason": "analysis_run_not_publishable",
            },
            extra=_analysis_audit_context(analysis_run),
        )
        await db.commit()
        raise AppException(status_code=409, message="提案来源已失效，不能审批")
    if analysis_run.source_policy != AIAuthorityPolicy.AUTHORITATIVE.value:
        reason = "只有 authoritative 文件类型的分析才能产生主数据提案"
        await _mark_analysis_stale(db, analysis_run, reason, user=user)
        await db.commit()
        raise AppException(status_code=409, message=reason)
    if not file_is_current:
        reason = "文件解析或分块版本已变化，请重新运行"
        await _mark_analysis_stale(db, analysis_run, reason, user=user)
        await db.commit()
        raise AppException(status_code=409, message="提案来源已过期，请重新分析文档")
    stale_reason = await _analysis_stale_reason(db, analysis_run)
    if stale_reason:
        await _mark_analysis_stale(db, analysis_run, stale_reason, user=user)
        await db.commit()
        raise AppException(status_code=409, message="提案来源已过期，请重新分析文档")
    original_payload = dict(proposal.proposed_payload)
    data = dict(original_payload)
    if payload:
        data.update(payload)
    # 更新提案通常只携带模型建议变更字段（例如 name）。只有提案本身或
    # 本次请求明确携带 aliases 时才执行别名替换。
    if (
        proposal.proposal_type == "update"
        and "aliases" not in original_payload
        and (payload is None or "aliases" not in payload)
    ):
        data.pop("aliases", None)
    # 明确禁止 AI/提案审批路径写来源对象；来源选择仍走人工主数据页面。
    data.pop("sources", None)
    from app.modules.qa.schemas import MasterObjectCreate, MasterObjectUpdate
    from app.modules.qa.service import create_master, update_master

    if proposal.proposal_type == "create":
        # 先做与正式创建服务相同的编码冲突预检。若主数据目录在分析后
        # 新增了同编码对象，提案应留下可审计的 conflict，而不是只把
        # DuplicateException 返回给前端并让提案永远停在 pending。
        proposed_type = str(data.get("object_type") or proposal.object_type).upper()
        proposed_code = normalize_text(str(data.get("code") or ""))
        if proposed_code:
            conflict_result = await db.execute(
                select(MasterObject).where(
                    MasterObject.object_type == proposed_type,
                    MasterObject.normalized_code == proposed_code,
                )
            )
            conflict = conflict_result.scalar_one_or_none()
            if conflict is not None:
                proposal.status = AIProposalStatus.CONFLICT.value
                proposal.conflicts = [
                    {
                        "reason": "业务编码已被占用",
                        "master_object_id": str(conflict.id),
                        "code": conflict.code,
                    }
                ]
                proposal.reviewed_by = _actor_id(user)
                proposal.reviewed_at = datetime.now(UTC)
                await db.flush()
                await _audit(
                    db,
                    action="ai_proposal_conflict",
                    user=user,
                    resource_type="master_object_proposal",
                    resource_id=proposal.id,
                    new_value={"status": proposal.status, "reason": "code_conflict"},
                    extra=_analysis_audit_context(analysis_run),
                )
                await db.commit()
                raise AppException(
                    status_code=409, message="提案业务编码已被占用，已标记冲突"
                )
        obj = await create_master(
            db, _validate_master_payload(MasterObjectCreate, data), user
        )
        proposal.target_master_object_id = obj.id
    else:
        if proposal.target_master_object_id is None:
            raise AppException(status_code=409, message="更新提案缺少目标主数据")
        current_result = await db.execute(
            select(MasterObject)
            .where(
                MasterObject.id == proposal.target_master_object_id,
                MasterObject.is_deleted.is_(False),
            )
            .with_for_update()
        )
        current = current_result.scalar_one_or_none()
        if current is None:
            proposal.status = AIProposalStatus.CONFLICT.value
            proposal.conflicts = [{"reason": "目标主数据不存在或已删除"}]
            proposal.reviewed_by = _actor_id(user)
            proposal.reviewed_at = datetime.now(UTC)
            await _audit(
                db,
                action="ai_proposal_conflict",
                user=user,
                resource_type="master_object_proposal",
                resource_id=proposal.id,
                new_value={"status": proposal.status, "reason": "target_missing"},
                extra=_analysis_audit_context(analysis_run),
            )
            await db.commit()
            raise AppException(
                status_code=409, message="目标主数据已不存在，提案已标记冲突"
            )
        current_aliases = await get_aliases(db, current.id)
        current_snapshot_full = {
            "id": str(current.id),
            "name": current.name,
            "description": current.description,
            "status": current.status,
            "aliases": sorted(
                (alias.alias for alias in current_aliases), key=normalize_text
            ),
            "updated_at": current.updated_at.isoformat()
            if current.updated_at
            else None,
        }
        current_snapshot = (
            {key: current_snapshot_full.get(key) for key in proposal.base_snapshot}
            if proposal.base_snapshot
            else current_snapshot_full
        )
        if proposal.base_fingerprint and proposal.base_fingerprint != _fingerprint(
            current_snapshot
        ):
            proposal.status = AIProposalStatus.CONFLICT.value
            proposal.conflicts = [
                {"reason": "基础版本已变化", "current": current_snapshot}
            ]
            proposal.reviewed_by = _actor_id(user)
            proposal.reviewed_at = datetime.now(UTC)
            await _audit(
                db,
                action="ai_proposal_conflict",
                user=user,
                resource_type="master_object_proposal",
                resource_id=proposal.id,
                new_value={"status": proposal.status, "reason": "base_version_changed"},
                extra=_analysis_audit_context(analysis_run),
            )
            await db.commit()
            raise AppException(
                status_code=409, message="主数据已发生变化，提案已标记冲突"
            )
        await update_master(
            db,
            proposal.target_master_object_id,
            _validate_master_payload(MasterObjectUpdate, data),
            user,
        )
    proposal.proposed_payload = data
    proposal.status = AIProposalStatus.APPROVED.value
    proposal.reviewed_by = _actor_id(user)
    proposal.reviewed_at = datetime.now(UTC)
    await db.flush()
    # 审批自身会写入主数据（新建，或改名/改别名），而目录指纹恰恰包含
    # code/name/aliases。若不在这里把运行快照推进到写入后的目录状态，同一次
    # 分析里剩下的提案会在下一次审批时被判为「主数据目录已变化」，整批提案
    # 连同待确认关联一起被标记过期，且没有恢复入口（只能重跑分析）。
    # 推进之后出现的差异仍然只可能来自别人的改动，校验语义不变。
    _, _, catalog_fingerprint = await _catalog(db)
    analysis_run.catalog_fingerprint = catalog_fingerprint
    # 审批通过即代表审核人认可「该文件的证据支持此主数据」：在同一事务
    # 内自动追加文件关联，免去再去确认一次。版本已锁定等无法追加的情形
    # 只跳过关联、不阻塞审批——主数据已落库，关联仍可走人工入口；该
    # 附属动作不单独写审计。
    auto_link_skipped: str | None = None
    from app.modules.qa.service import set_relations_append

    try:
        await set_relations_append(
            db,
            analysis_run.version_id,
            [proposal.target_master_object_id],
            user,
            audit=False,
        )
    except AppException as exc:
        auto_link_skipped = str(exc.message)
    await _audit(
        db,
        action="ai_proposal_approved",
        user=user,
        resource_type="master_object_proposal",
        resource_id=proposal.id,
        new_value={
            "proposal_type": proposal.proposal_type,
            "target_master_object_id": str(proposal.target_master_object_id)
            if proposal.target_master_object_id
            else None,
        },
        extra=_analysis_audit_context(analysis_run),
    )
    return proposal, auto_link_skipped


async def reject_proposal(
    db: AsyncSession, proposal_id: uuid.UUID, user: User | None = None
) -> MasterObjectProposal:
    """拒绝提案即软删除：不记录拒绝原因，也不写审计。"""
    proposal_result = await db.execute(
        select(MasterObjectProposal)
        .where(
            MasterObjectProposal.id == proposal_id,
            MasterObjectProposal.is_deleted.is_(False),
        )
        .with_for_update()
    )
    proposal = proposal_result.scalar_one_or_none()
    if proposal is None:
        raise NotFoundException("主数据提案", str(proposal_id))
    if proposal.status != AIProposalStatus.PENDING.value:
        raise AppException(status_code=409, message="该提案已经处理，不能重复拒绝")
    if user is not None:
        required_permission = (
            "qa:master:create"
            if proposal.proposal_type == "create"
            else "qa:master:update"
        )
        permissions = await get_user_permissions(str(user.id), db)
        if required_permission not in permissions:
            raise ForbiddenException(f"处理该提案需要权限: {required_permission}")
    proposal.status = AIProposalStatus.REJECTED.value
    proposal.reviewed_by = _actor_id(user)
    proposal.reviewed_at = datetime.now(UTC)
    proposal.is_deleted = True
    await db.flush()
    return proposal
