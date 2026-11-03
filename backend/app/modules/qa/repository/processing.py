"""QA 正文提取与 AI 分析仓储。"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.modules.qa.models import (
    DocumentChunkBlock,
    DocumentChunkRun,
    DocumentExtractionRun,
    DocumentFile,
    DocumentTextChunk,
    DocumentTextSegment,
)


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


async def get_segments(
    db: AsyncSession, file_id: uuid.UUID
) -> list[DocumentTextSegment]:
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


async def get_chunks(
    db: AsyncSession, chunk_run_id: uuid.UUID
) -> list[DocumentTextChunk]:
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
        .order_by(
            DocumentExtractionRun.created_at.desc(), DocumentExtractionRun.id.desc()
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_chunk_run(db: AsyncSession, run_id: uuid.UUID) -> DocumentChunkRun | None:
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
    """分页读取当前 chunk 的检索文本预览；不向查看器返回原始正文。"""

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
            # retrieval_text 是新增的可空列且没有回填，迁移前的 chunk 全是
            # NULL；直接 substr 会让整个存量语料在查看器里显示"尚无检索文本"，
            # 而正文其实取得到。按 models 里写明的规则回退 content——重新解析
            # 之后自然回到检索文本，不必为了看一眼正文去动 MinerU。
            func.substr(
                func.coalesce(
                    DocumentTextChunk.retrieval_text, DocumentTextChunk.content
                ),
                1,
                content_limit + 1,
            ).label("retrieval_text_preview"),
            func.coalesce(
                DocumentTextChunk.retrieval_char_count, DocumentTextChunk.char_count
            ).label("retrieval_char_count"),
            DocumentTextChunk.retrieval_text_hash,
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
