"""QA 模块数据访问层。

本文件只负责 SQL 查询和持久化；状态、跨模块校验及审计由 service 编排。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.modules.qa.models import (
    Document,
    DocumentAIAnalysisRun,
    DocumentChunkBlock,
    DocumentChunkRun,
    DocumentExtractionRun,
    DocumentFile,
    DocumentMasterLink,
    DocumentTextChunk,
    DocumentTextSegment,
    DocumentType,
    DocumentVersion,
    MasterObject,
    MasterObjectAlias,
    MasterObjectProposal,
    MasterObjectSource,
)
from app.shared.sql import escape_like


def current_text_segment_condition() -> ColumnElement[bool]:
    """只选择文件当前解析运行的 raw block，并兼容未迁移的 legacy 数据。"""
    return or_(
        and_(
            DocumentFile.current_extraction_run_id.is_not(None),
            DocumentTextSegment.extraction_run_id
            == DocumentFile.current_extraction_run_id,
        ),
        and_(
            DocumentFile.current_extraction_run_id.is_(None),
            DocumentTextSegment.extraction_run_id.is_(None),
        ),
    )


async def get_master(db: AsyncSession, object_id: uuid.UUID) -> MasterObject | None:
    result = await db.execute(
        select(MasterObject).where(
            MasterObject.id == object_id,
            MasterObject.is_deleted.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def list_masters(
    db: AsyncSession,
    *,
    object_type: str | None = None,
    keyword: str | None = None,
    status: str | None = None,
    include_deleted: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[MasterObject], int]:
    conditions: list[ColumnElement[bool]] = []
    if not include_deleted:
        conditions.append(MasterObject.is_deleted.is_(False))
    if object_type:
        conditions.append(MasterObject.object_type == object_type)
    if status:
        conditions.append(MasterObject.status == status)
    if keyword:
        # 用户输入的 % / _ 是字面量；不转义时 keyword="%" 会命中全表。
        term = f"%{escape_like(keyword.strip())}%"
        conditions.append(
            or_(
                MasterObject.code.ilike(term, escape="\\"),
                MasterObject.name.ilike(term, escape="\\"),
                MasterObject.normalized_code.ilike(term, escape="\\"),
                MasterObject.id.in_(
                    select(MasterObjectAlias.master_object_id).where(
                        MasterObjectAlias.normalized_alias.ilike(term, escape="\\"),
                        MasterObjectAlias.is_deleted.is_(False),
                    )
                ),
            )
        )
    base = select(MasterObject).where(*conditions)
    total = int(
        (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    )
    result = await db.execute(
        base.order_by(MasterObject.object_type, MasterObject.code)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars()), total


async def get_aliases(db: AsyncSession, object_id: uuid.UUID) -> list[MasterObjectAlias]:
    result = await db.execute(
        select(MasterObjectAlias)
        .where(
            MasterObjectAlias.master_object_id == object_id,
            MasterObjectAlias.is_deleted.is_(False),
        )
        .order_by(MasterObjectAlias.alias)
    )
    return list(result.scalars())


async def get_sources(db: AsyncSession, object_id: uuid.UUID) -> list[MasterObjectSource]:
    result = await db.execute(
        select(MasterObjectSource)
        .where(
            MasterObjectSource.master_object_id == object_id,
            MasterObjectSource.is_deleted.is_(False),
        )
        .order_by(MasterObjectSource.source_module, MasterObjectSource.source_entity)
    )
    return list(result.scalars())


async def get_aliases_for_masters(
    db: AsyncSession, object_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[MasterObjectAlias]]:
    """批量取别名，供列表页一次查完（逐行查会变成 N+1）。"""
    if not object_ids:
        return {}
    result = await db.execute(
        select(MasterObjectAlias)
        .where(
            MasterObjectAlias.master_object_id.in_(object_ids),
            MasterObjectAlias.is_deleted.is_(False),
        )
        .order_by(MasterObjectAlias.alias)
    )
    grouped: dict[uuid.UUID, list[MasterObjectAlias]] = {}
    for row in result.scalars():
        grouped.setdefault(row.master_object_id, []).append(row)
    return grouped


async def get_sources_for_masters(
    db: AsyncSession, object_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[MasterObjectSource]]:
    """批量取外部来源，供列表页一次查完（逐行查会变成 N+1）。"""
    if not object_ids:
        return {}
    result = await db.execute(
        select(MasterObjectSource)
        .where(
            MasterObjectSource.master_object_id.in_(object_ids),
            MasterObjectSource.is_deleted.is_(False),
        )
        .order_by(MasterObjectSource.source_module, MasterObjectSource.source_entity)
    )
    grouped: dict[uuid.UUID, list[MasterObjectSource]] = {}
    for row in result.scalars():
        grouped.setdefault(row.master_object_id, []).append(row)
    return grouped


async def get_document_type(db: AsyncSession, type_id: uuid.UUID) -> DocumentType | None:
    result = await db.execute(
        select(DocumentType).where(
            DocumentType.id == type_id,
            DocumentType.is_deleted.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def list_document_types(
    db: AsyncSession, *, include_inactive: bool = False
) -> list[DocumentType]:
    stmt = select(DocumentType).where(DocumentType.is_deleted.is_(False))
    if not include_inactive:
        stmt = stmt.where(DocumentType.status == "active")
    result = await db.execute(stmt.order_by(DocumentType.code))
    return list(result.scalars())


async def get_document(db: AsyncSession, document_id: uuid.UUID) -> Document | None:
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.is_deleted.is_(False),
        )
    )
    return result.scalar_one_or_none()


# 台账可排序字段白名单。传白名单外的值回落到编号，不接受任意列名。
DOCUMENT_SORT_COLUMNS = {
    "document_no": Document.document_no,
    "title": Document.title,
}


async def list_documents(
    db: AsyncSession,
    *,
    keyword: str | None = None,
    document_type_id: uuid.UUID | None = None,
    responsible_department_id: str | None = None,
    status: str | None = None,
    include_inactive: bool = False,
    has_current_version: bool | None = None,
    sort_by: str = "document_no",
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Document], int]:
    conditions: list[ColumnElement[bool]] = [Document.is_deleted.is_(False)]
    if not include_inactive:
        conditions.append(Document.status == "active")
    if document_type_id:
        conditions.append(Document.document_type_id == document_type_id)
    if responsible_department_id:
        conditions.append(Document.responsible_department_id == responsible_department_id)
    if status:
        conditions.append(Document.status == status)
    if has_current_version is not None:
        # 首页「已设当前版本」统计用：拿 total 即可，不必逐页拉台账。
        conditions.append(
            Document.current_version_id.is_not(None)
            if has_current_version
            else Document.current_version_id.is_(None)
        )
    if keyword:
        # 用户输入的 % / _ 是字面量；不转义时 keyword="%" 会命中全表。
        term = f"%{escape_like(keyword.strip())}%"
        conditions.append(
            or_(
                Document.document_no.ilike(term, escape="\\"),
                Document.title.ilike(term, escape="\\"),
                Document.id.in_(
                    select(DocumentVersion.document_id).where(
                        DocumentVersion.id.in_(
                            select(DocumentFile.version_id)
                            .join(
                                DocumentTextSegment,
                                DocumentTextSegment.file_id == DocumentFile.id,
                            )
                            .where(
                                DocumentTextSegment.content.ilike(
                                    term, escape="\\"
                                ),
                                DocumentTextSegment.is_deleted.is_(False),
                                DocumentFile.is_deleted.is_(False),
                                current_text_segment_condition(),
                            )
                        ),
                        DocumentVersion.is_deleted.is_(False),
                    )
                ),
                Document.id.in_(
                    select(DocumentVersion.document_id).where(
                        DocumentVersion.id.in_(
                            select(DocumentMasterLink.version_id).where(
                                DocumentMasterLink.master_object_id.in_(
                                    select(MasterObject.id).where(
                                        or_(
                                            MasterObject.code.ilike(term, escape="\\"),
                                            MasterObject.name.ilike(term, escape="\\"),
                                        ),
                                        MasterObject.is_deleted.is_(False),
                                    )
                                ),
                                DocumentMasterLink.is_deleted.is_(False),
                            )
                        ),
                        DocumentVersion.is_deleted.is_(False),
                    )
                ),
            )
        )
    base = select(Document).where(*conditions)
    total = int(
        (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    )
    # 二级按编号：标题可重复，只按标题排时分页边界会飘，同一份文件可能出现在两页。
    result = await db.execute(
        base.order_by(
            DOCUMENT_SORT_COLUMNS.get(sort_by, Document.document_no), Document.document_no
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars()), total


async def get_versions(db: AsyncSession, document_id: uuid.UUID) -> list[DocumentVersion]:
    result = await db.execute(
        select(DocumentVersion)
        .where(
            DocumentVersion.document_id == document_id,
            DocumentVersion.is_deleted.is_(False),
        )
        .order_by(DocumentVersion.version_sequence.desc())
    )
    return list(result.scalars())


async def get_version(db: AsyncSession, version_id: uuid.UUID) -> DocumentVersion | None:
    result = await db.execute(
        select(DocumentVersion).where(
            DocumentVersion.id == version_id,
            DocumentVersion.is_deleted.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def get_file_for_version(
    db: AsyncSession, version_id: uuid.UUID
) -> DocumentFile | None:
    result = await db.execute(
        select(DocumentFile).where(
            DocumentFile.version_id == version_id,
            DocumentFile.is_deleted.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def get_file(db: AsyncSession, file_id: uuid.UUID) -> DocumentFile | None:
    result = await db.execute(
        select(DocumentFile).where(
            DocumentFile.id == file_id,
            DocumentFile.is_deleted.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def get_segments(db: AsyncSession, file_id: uuid.UUID) -> list[DocumentTextSegment]:
    result = await db.execute(
        select(DocumentTextSegment)
        .join(DocumentFile, DocumentFile.id == DocumentTextSegment.file_id)
        .where(
            DocumentTextSegment.file_id == file_id,
            DocumentTextSegment.is_deleted.is_(False),
            DocumentFile.is_deleted.is_(False),
            current_text_segment_condition(),
        )
        .order_by(
            func.coalesce(DocumentTextSegment.source_order, 2_147_483_647),
            DocumentTextSegment.page_number,
            DocumentTextSegment.paragraph_index,
            DocumentTextSegment.id,
        )
    )
    return list(result.scalars())


async def get_chunks(db: AsyncSession, chunk_run_id: uuid.UUID) -> list[DocumentTextChunk]:
    result = await db.execute(
        select(DocumentTextChunk)
        .where(
            DocumentTextChunk.chunk_run_id == chunk_run_id,
            DocumentTextChunk.is_deleted.is_(False),
        )
        .order_by(DocumentTextChunk.chunk_order)
    )
    return list(result.scalars())


async def get_extraction_run(
    db: AsyncSession, run_id: uuid.UUID
) -> DocumentExtractionRun | None:
    result = await db.execute(
        select(DocumentExtractionRun).where(
            DocumentExtractionRun.id == run_id,
            DocumentExtractionRun.is_deleted.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def get_latest_extraction_run_any_status(
    db: AsyncSession, file_id: uuid.UUID
) -> DocumentExtractionRun | None:
    """返回最近一次解析尝试，包括 queued/processing/failed/stale。"""

    result = await db.execute(
        select(DocumentExtractionRun)
        .where(
            DocumentExtractionRun.file_id == file_id,
            DocumentExtractionRun.is_deleted.is_(False),
        )
        .order_by(DocumentExtractionRun.created_at.desc(), DocumentExtractionRun.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_chunk_run(
    db: AsyncSession, run_id: uuid.UUID
) -> DocumentChunkRun | None:
    result = await db.execute(
        select(DocumentChunkRun).where(
            DocumentChunkRun.id == run_id,
            DocumentChunkRun.is_deleted.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def get_latest_chunk_run_any_status(
    db: AsyncSession, file_id: uuid.UUID
) -> DocumentChunkRun | None:
    result = await db.execute(
        select(DocumentChunkRun)
        .where(
            DocumentChunkRun.file_id == file_id,
            DocumentChunkRun.is_deleted.is_(False),
        )
        .order_by(DocumentChunkRun.created_at.desc(), DocumentChunkRun.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_current_raw_block_previews(
    db: AsyncSession,
    file: DocumentFile,
    *,
    page: int,
    page_size: int,
    content_limit: int,
    allow_legacy: bool = True,
) -> tuple[list[dict[str, Any]], int]:
    """分页读取当前 raw block；正文在 SQL 层截断，避免加载完整大段文本。"""

    # 没有 current 指针时只有真正的迁移前 legacy 文件才允许回退到
    # extraction_run_id IS NULL。新运行处于 queued/processing/failed 时，
    # 旧 raw block 不能冒充本次运行的结果。
    if file.current_extraction_run_id is None and not allow_legacy:
        return [], 0
    run_condition = (
        DocumentTextSegment.extraction_run_id == file.current_extraction_run_id
        if file.current_extraction_run_id is not None
        else DocumentTextSegment.extraction_run_id.is_(None)
    )
    conditions = (
        DocumentTextSegment.file_id == file.id,
        DocumentTextSegment.is_deleted.is_(False),
        run_condition,
    )
    total = int(
        (
            await db.execute(
                select(func.count()).select_from(DocumentTextSegment).where(*conditions)
            )
        ).scalar_one()
    )
    preview_length = content_limit + 1
    result = await db.execute(
        select(
            DocumentTextSegment.id,
            DocumentTextSegment.source_order,
            DocumentTextSegment.block_type,
            DocumentTextSegment.locator,
            DocumentTextSegment.page_number,
            DocumentTextSegment.paragraph_index,
            DocumentTextSegment.table_index,
            DocumentTextSegment.row_index,
            DocumentTextSegment.column_index,
            DocumentTextSegment.heading_path,
            func.substr(DocumentTextSegment.content, 1, preview_length).label(
                "content_preview"
            ),
            func.length(DocumentTextSegment.content).label("content_length"),
            DocumentTextSegment.text_hash,
            DocumentTextSegment.source_metadata,
        )
        .where(*conditions)
        .order_by(
            func.coalesce(DocumentTextSegment.source_order, 2_147_483_647),
            DocumentTextSegment.id,
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return [dict(row) for row in result.mappings().all()], total


async def list_current_chunk_previews(
    db: AsyncSession,
    file: DocumentFile,
    *,
    page: int,
    page_size: int,
    content_limit: int,
) -> tuple[list[dict[str, Any]], int]:
    """分页读取当前 chunk；没有 current 指针时绝不回退到历史运行。"""

    if file.current_chunk_run_id is None:
        return [], 0
    conditions = (
        DocumentTextChunk.file_id == file.id,
        DocumentTextChunk.chunk_run_id == file.current_chunk_run_id,
        DocumentTextChunk.is_deleted.is_(False),
    )
    total = int(
        (
            await db.execute(
                select(func.count()).select_from(DocumentTextChunk).where(*conditions)
            )
        ).scalar_one()
    )
    result = await db.execute(
        select(
            DocumentTextChunk.id,
            DocumentTextChunk.chunk_order,
            DocumentTextChunk.char_count,
            DocumentTextChunk.token_count,
            DocumentTextChunk.heading_path,
            DocumentTextChunk.page_start,
            DocumentTextChunk.page_end,
            DocumentTextChunk.source_start,
            DocumentTextChunk.source_end,
            func.substr(DocumentTextChunk.content, 1, content_limit + 1).label(
                "content_preview"
            ),
            DocumentTextChunk.content_hash,
            DocumentTextChunk.chunk_metadata,
        )
        .where(*conditions)
        .order_by(DocumentTextChunk.chunk_order, DocumentTextChunk.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return [dict(row) for row in result.mappings().all()], total


async def list_chunk_block_locations(
    db: AsyncSession, chunk_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[dict[str, Any]]]:
    """批量读取 chunk 到 raw block 的非正文映射，避免分页结果出现 N+1。"""

    if not chunk_ids:
        return {}
    result = await db.execute(
        select(
            DocumentChunkBlock.chunk_id,
            DocumentChunkBlock.segment_id,
            DocumentChunkBlock.block_order,
            DocumentChunkBlock.char_start,
            DocumentChunkBlock.char_end,
            DocumentTextSegment.locator,
            DocumentTextSegment.block_type,
        )
        .join(
            DocumentTextSegment,
            DocumentTextSegment.id == DocumentChunkBlock.segment_id,
        )
        .where(
            DocumentChunkBlock.chunk_id.in_(chunk_ids),
            DocumentChunkBlock.is_deleted.is_(False),
            DocumentTextSegment.is_deleted.is_(False),
        )
        .order_by(DocumentChunkBlock.chunk_id, DocumentChunkBlock.block_order)
    )
    output: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for row in result.mappings().all():
        value = dict(row)
        chunk_id = value.pop("chunk_id")
        output.setdefault(chunk_id, []).append(value)
    return output


async def get_latest_ai_run(
    db: AsyncSession, version_id: uuid.UUID
) -> DocumentAIAnalysisRun | None:
    result = await db.execute(
        select(DocumentAIAnalysisRun)
        .where(
            DocumentAIAnalysisRun.version_id == version_id,
            DocumentAIAnalysisRun.is_deleted.is_(False),
        )
        .order_by(DocumentAIAnalysisRun.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_ai_run(db: AsyncSession, run_id: uuid.UUID) -> DocumentAIAnalysisRun | None:
    result = await db.execute(
        select(DocumentAIAnalysisRun).where(
            DocumentAIAnalysisRun.id == run_id,
            DocumentAIAnalysisRun.is_deleted.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def list_proposals(
    db: AsyncSession, *, status: str | None = None, page: int = 1, page_size: int = 50
) -> tuple[list[MasterObjectProposal], int]:
    conditions: list[ColumnElement[bool]] = [MasterObjectProposal.is_deleted.is_(False)]
    if status:
        conditions.append(MasterObjectProposal.status == status)
    base = select(MasterObjectProposal).where(*conditions)
    total = int((await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one())
    result = await db.execute(
        base.order_by(MasterObjectProposal.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars()), total


async def get_links(db: AsyncSession, version_id: uuid.UUID) -> list[DocumentMasterLink]:
    result = await db.execute(
        select(DocumentMasterLink)
        .where(
            DocumentMasterLink.version_id == version_id,
            DocumentMasterLink.is_deleted.is_(False),
        )
        .order_by(DocumentMasterLink.code_snapshot)
    )
    return list(result.scalars())


async def get_links_for_master(
    db: AsyncSession, object_id: uuid.UUID, *, include_history: bool = False
) -> list[DocumentMasterLink]:
    stmt = select(DocumentMasterLink).where(
        DocumentMasterLink.master_object_id == object_id,
        DocumentMasterLink.is_deleted.is_(False),
    )
    if not include_history:
        stmt = stmt.where(
            DocumentMasterLink.version_id.in_(
                select(Document.current_version_id).where(
                    Document.current_version_id.is_not(None),
                    Document.is_deleted.is_(False),
                )
            )
        )
    result = await db.execute(stmt)
    return list(result.scalars())
