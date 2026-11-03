"""QA 全局检索：主数据、部门、文件与正文片段的排序与摘要。"""

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.qa import (
    file_service as file_service,  # 显式再导出，供 api 层与测试补丁使用
)
from app.modules.qa.models import (
    Document,
    DocumentFile,
    DocumentMasterLink,
    DocumentTextSegment,
    DocumentVersion,
    ExtractionStatus,
    MasterObject,
    MasterObjectAlias,
    RecordStatus,
    VersionStatus,
)
from app.modules.qa.repository import (
    current_text_segment_condition,
)
from app.modules.qa.service._shared import (
    normalize_text,
)

logger = logging.getLogger(__name__)


def _compact(value: str) -> str:
    """搜索用的紧凑键，允许 ``R101`` 命中 ``R-101``。"""
    return "".join(ch for ch in value.upper() if ch.isalnum())


def _snippet(content: str, query: str, limit: int = 240) -> str:
    clean = " ".join(content.split())
    if len(clean) <= limit:
        return clean
    q = query.strip()
    pos = clean.lower().find(q.lower()) if q else -1
    if pos < 0:
        # 对去标点命中的情况，按首部返回可读片段。
        return clean[: max(0, limit - 1)] + "…"
    start = max(0, pos - 80)
    # 前后省略号也计入上限，保证 API 返回片段不超过 limit 字符。
    prefix = "…" if start else ""
    suffix_budget = 1 if start + limit < len(clean) else 0
    content_limit = max(0, limit - len(prefix) - suffix_budget)
    end = min(len(clean), start + content_limit)
    # 若从中间截取后仍有尾部内容，保留一个省略号字符的预算。
    suffix = "…" if end < len(clean) else ""
    if len(prefix) + len(clean[start:end]) + len(suffix) > limit:
        end = start + max(0, limit - len(prefix) - len(suffix))
    prefix = "…" if start else ""
    return prefix + clean[start:end] + suffix


def _rank(kind: str, field: str, query: str, value: str) -> float:
    q = normalize_text(query)
    v = normalize_text(value)
    if _compact(v) == _compact(q):
        return 100.0 if field in {"code", "document_no"} else 95.0
    if v == q:
        return 98.0 if field in {"code", "document_no"} else 94.0
    if v.startswith(q):
        return 80.0
    if q in v:
        return 70.0 if field in {"name", "title"} else 60.0
    return 0.0


async def search(
    db: AsyncSession,
    query: str,
    *,
    include_history: bool = False,
    include_inactive: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """统一检索主数据、部门、文件及正文片段。

    查询结果在首版按明确的业务优先级排序；PostgreSQL 上模型/迁移提供
    trigram/GIN 索引，Python 层只负责合并跨实体命中和生成片段。
    """
    q = query.strip()
    if not q:
        return [], 0
    q_lower = q.lower()
    compact_q = _compact(q)
    hits: list[dict[str, Any]] = []

    # 主数据、别名及其关联文件。
    master_stmt = select(MasterObject).where(MasterObject.is_deleted.is_(False))
    if not include_inactive:
        master_stmt = master_stmt.where(
            MasterObject.status == RecordStatus.ACTIVE.value
        )
    masters = list((await db.execute(master_stmt)).scalars())
    alias_result = await db.execute(
        select(MasterObjectAlias).where(MasterObjectAlias.is_deleted.is_(False))
    )
    alias_rows = list(alias_result.scalars())
    aliases_by_master: dict[uuid.UUID, list[MasterObjectAlias]] = {}
    for alias in alias_rows:
        aliases_by_master.setdefault(alias.master_object_id, []).append(alias)

    master_ids = [obj.id for obj in masters]
    links_by_master: dict[uuid.UUID, list[DocumentMasterLink]] = {}
    if master_ids:
        link_result = await db.execute(
            select(DocumentMasterLink).where(
                DocumentMasterLink.master_object_id.in_(master_ids),
                DocumentMasterLink.is_deleted.is_(False),
            )
        )
        for link in link_result.scalars():
            links_by_master.setdefault(link.master_object_id, []).append(link)
    linked_version_ids = [
        link.version_id for links in links_by_master.values() for link in links
    ]
    linked_versions: dict[uuid.UUID, DocumentVersion] = {}
    if linked_version_ids:
        version_result = await db.execute(
            select(DocumentVersion).where(
                DocumentVersion.id.in_(linked_version_ids),
                DocumentVersion.is_deleted.is_(False),
            )
        )
        linked_versions = {version.id: version for version in version_result.scalars()}
    linked_document_ids = {version.document_id for version in linked_versions.values()}
    linked_documents: dict[uuid.UUID, Document] = {}
    if linked_document_ids:
        document_result = await db.execute(
            select(Document).where(
                Document.id.in_(linked_document_ids),
                Document.is_deleted.is_(False),
            )
        )
        linked_documents = {
            document.id: document for document in document_result.scalars()
        }

    for obj in masters:
        candidates = [("code", obj.code), ("name", obj.name)]
        candidates.extend(("alias", a.alias) for a in aliases_by_master.get(obj.id, []))
        score = max(
            (_rank("master_object", field, q, value) for field, value in candidates),
            default=0,
        )
        # 紧凑键命中（例如 R101 / R-101）即使普通 SQL contains 不命中也保留。
        if score == 0 and any(
            compact_q and compact_q in _compact(value) for _, value in candidates
        ):
            score = 75.0
        if score:
            hits.append(
                {
                    "kind": "master_object",
                    "id": obj.id,
                    "score": score,
                    "code": obj.code,
                    "name": obj.name,
                    "object_type": obj.object_type,
                    "status": obj.status,
                }
            )

        # 关系命中：返回文件结果，关联快照可用于解释命中。
        links = links_by_master.get(obj.id, [])
        if links:
            for link in links:
                version = linked_versions.get(link.version_id)
                if version is None:
                    continue
                if (
                    not include_history
                    and version.status != VersionStatus.CURRENT.value
                ):
                    continue
                if (
                    not include_inactive
                    and version.status == VersionStatus.INACTIVE.value
                ):
                    continue
                document = linked_documents.get(version.document_id)
                if document is None or (
                    not include_inactive
                    and document.status != RecordStatus.ACTIVE.value
                ):
                    continue
                if not score:
                    continue
                hits.append(
                    {
                        "kind": "document",
                        "id": document.id,
                        "score": max(60.0, score - 20),
                        "code": document.document_no,
                        "title": document.title,
                        "document_id": document.id,
                        "document_no": document.document_no,
                        "version_id": version.id,
                        "version_label": version.version_label,
                        "status": version.status,
                    }
                )

    # 部门是身份平台的只读引用，不复制进 QA。
    try:
        from app.platform.identity.public_api import list_department_briefs

        departments = await list_department_briefs(db, keyword=q)
        for dept in departments:
            score = max(
                _rank("department", "code", q, dept.feishu_department_id),
                _rank("department", "name", q, dept.name),
            )
            if score:
                hits.append(
                    {
                        "kind": "department",
                        "id": dept.id,
                        "score": score,
                        "code": dept.feishu_department_id,
                        "name": dept.name,
                        "status": "active" if dept.is_active else "inactive",
                    }
                )
    except Exception:
        logger.debug("Department search unavailable", exc_info=True)

    # 文件台账、版本和正文片段。这里使用宽松 SQL 初筛，再按业务排序合并。
    doc_stmt = select(Document).where(Document.is_deleted.is_(False))
    if not include_inactive:
        doc_stmt = doc_stmt.where(Document.status == RecordStatus.ACTIVE.value)
    documents = list((await db.execute(doc_stmt)).scalars())
    document_ids = [document.id for document in documents]
    versions_by_document: dict[uuid.UUID, list[DocumentVersion]] = {}
    files_by_version: dict[uuid.UUID, DocumentFile] = {}
    segments_by_file: dict[uuid.UUID, list[DocumentTextSegment]] = {}
    if document_ids:
        version_result = await db.execute(
            select(DocumentVersion).where(
                DocumentVersion.document_id.in_(document_ids),
                DocumentVersion.is_deleted.is_(False),
            )
        )
        versions = list(version_result.scalars())
        for version in versions:
            versions_by_document.setdefault(version.document_id, []).append(version)
        version_ids = [version.id for version in versions]
        if version_ids:
            file_result = await db.execute(
                select(DocumentFile).where(
                    DocumentFile.version_id.in_(version_ids),
                    DocumentFile.is_deleted.is_(False),
                )
            )
            files = list(file_result.scalars())
            files_by_version = {file.version_id: file for file in files}
            file_ids = [file.id for file in files]
            if file_ids:
                segment_result = await db.execute(
                    select(DocumentTextSegment)
                    .join(DocumentFile, DocumentFile.id == DocumentTextSegment.file_id)
                    .where(
                        DocumentTextSegment.file_id.in_(file_ids),
                        DocumentTextSegment.is_deleted.is_(False),
                        DocumentFile.is_deleted.is_(False),
                        current_text_segment_condition(),
                    )
                )
                for segment in segment_result.scalars():
                    segments_by_file.setdefault(segment.file_id, []).append(segment)
    for document in documents:
        doc_score = max(
            _rank("document", "document_no", q, document.document_no),
            _rank("document", "title", q, document.title),
        )
        versions = versions_by_document.get(document.id, [])
        for version in versions:
            if not include_history and version.id != document.current_version_id:
                continue
            if not include_inactive and version.status == VersionStatus.INACTIVE.value:
                continue
            if doc_score:
                hits.append(
                    {
                        "kind": "document",
                        "id": document.id,
                        "score": doc_score,
                        "code": document.document_no,
                        "title": document.title,
                        "document_id": document.id,
                        "document_no": document.document_no,
                        "version_id": version.id,
                        "version_label": version.version_label,
                        "status": version.status,
                    }
                )
            file_row = files_by_version.get(version.id)
            if (
                file_row is None
                or file_row.extraction_status != ExtractionStatus.READY.value
            ):
                continue
            segments = segments_by_file.get(file_row.id, [])
            for segment in segments:
                # 检索使用去除 MinerU HTML/版式噪声的派生文本；只有
                # ``None`` 的 legacy 行回退 raw。空字符串是空锚点的有意结果，
                # 不能再次把 ``<a id=...>`` 当作正文检索，snippet 也返回可读文本。
                content = (
                    segment.retrieval_text
                    if segment.retrieval_text is not None
                    else segment.content
                )
                if q_lower in content.lower() or (
                    compact_q and compact_q in _compact(content)
                ):
                    hits.append(
                        {
                            "kind": "document_segment",
                            "id": segment.id,
                            "score": 40.0,
                            "document_id": document.id,
                            "document_no": document.document_no,
                            "title": document.title,
                            "version_id": version.id,
                            "version_label": version.version_label,
                            "snippet": _snippet(content, q),
                            "locator": segment.locator,
                            "page_number": segment.page_number,
                            "paragraph_index": segment.paragraph_index,
                            "table_index": segment.table_index,
                            "row_index": segment.row_index,
                            "column_index": segment.column_index,
                            "segment_type": segment.block_type,
                            "status": version.status,
                        }
                    )

    # 同一文件通过台账和关联对象命中时保留最高分，正文片段独立返回定位。
    hits.sort(
        key=lambda item: (
            -float(item.get("score", 0)),
            str(item.get("document_no") or item.get("code") or ""),
        )
    )
    deduped: list[dict[str, Any]] = []
    seen_keys: set[tuple[Any, ...]] = set()
    for hit in hits:
        key = (
            hit["kind"],
            hit.get("id"),
            hit.get("version_id"),
            hit.get("locator"),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(hit)
    total = len(deduped)
    start = (page - 1) * page_size
    return deduped[start : start + page_size], total
