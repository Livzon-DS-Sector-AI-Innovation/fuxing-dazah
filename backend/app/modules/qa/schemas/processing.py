"""QA 正文提取结果视图契约。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    Field,
)

from app.modules.qa.schemas.document import ExtractionStatus


class RetryExtractionRequest(BaseModel):
    force: bool = False


ProcessingResultView = Literal["raw_blocks", "chunks"]


class DocumentExtractionRunSummary(BaseModel):
    """前端解析结果查看器所需的解析运行摘要。

    worker token、租约等内部调度字段不属于只读展示契约，避免把后台实现
    细节暴露给浏览器。
    """

    id: uuid.UUID
    status: str
    is_current: bool = False
    parser_mode: str
    parser_version: str
    provider: str | None = None
    provider_state: str | None = None
    block_count: int = 0
    char_count: int = 0
    statistics: dict[str, Any] | None = None
    error: str | None = None
    retry_count: int = 0
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class DocumentChunkRunSummary(BaseModel):
    """前端解析结果查看器所需的分块运行摘要。"""

    id: uuid.UUID
    extraction_run_id: uuid.UUID
    status: str
    is_current: bool = False
    chunk_version: str
    chunk_count: int = 0
    char_count: int = 0
    statistics: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class DocumentRawBlockPreviewOut(BaseModel):
    id: uuid.UUID
    source_order: int | None = None
    block_type: str
    locator: str
    page_number: int | None = None
    paragraph_index: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    column_index: int | None = None
    heading_path: list[str] | None = None
    content_preview: str
    content_length: int
    content_truncated: bool
    text_hash: str
    structure_metadata: dict[str, Any] | None = None


class DocumentChunkSourceBlockOut(BaseModel):
    segment_id: uuid.UUID
    block_order: int
    char_start: int | None = None
    char_end: int | None = None
    locator: str
    block_type: str


class DocumentChunkPreviewOut(BaseModel):
    id: uuid.UUID
    chunk_order: int
    char_count: int
    # 供后续模型限长/下游消费保留；文件详情前端不展示 token 统计。
    token_count: int
    heading_path: list[str] | None = None
    page_start: int | None = None
    page_end: int | None = None
    source_start: int | None = None
    source_end: int | None = None
    retrieval_text_preview: str | None = None
    retrieval_char_count: int | None = None
    retrieval_text_truncated: bool = False
    retrieval_text_hash: str | None = None
    content_hash: str
    metadata: dict[str, Any] | None = None
    source_blocks: list[DocumentChunkSourceBlockOut] = Field(default_factory=list)


class DocumentProcessingResultOut(BaseModel):
    """当前有效 raw block/chunk 的受限预览及运行状态。"""

    file_id: uuid.UUID
    extraction_status: ExtractionStatus
    extraction_error: str | None = None
    retry_count: int = 0
    parser_mode: str
    parser_version: str | None = None
    legacy: bool = False
    current_extraction_run: DocumentExtractionRunSummary | None = None
    latest_extraction_run: DocumentExtractionRunSummary | None = None
    current_chunk_run: DocumentChunkRunSummary | None = None
    latest_chunk_run: DocumentChunkRunSummary | None = None
    view: ProcessingResultView
    page: int
    page_size: int
    total: int
    raw_blocks: list[DocumentRawBlockPreviewOut] = Field(default_factory=list)
    chunks: list[DocumentChunkPreviewOut] = Field(default_factory=list)
