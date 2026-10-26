"""QA 正文提取管线模型：文本段、提取运行、提取产物、分块运行与文本块。"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class ExtractionRunStatus(enum.StrEnum):
    """解析/分块运行状态。"""

    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    TEXT_NOT_AVAILABLE = "text_not_available"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"
    STALE = "stale"


class DocumentTextSegment(BaseModel):
    """可定位正文片段（PDF 页、DOCX 段落/表格单元）。"""

    __tablename__ = "document_text_segments"
    __table_args__ = (
        Index("ix_qa_document_text_segments_file_locator", "file_id", "locator"),
        Index(
            "ix_qa_document_text_segments_content_trgm",
            "content",
            postgresql_using="gin",
            postgresql_ops={"content": "gin_trgm_ops"},
        ),
        Index(
            "ix_qa_document_text_segments_retrieval_trgm",
            "retrieval_text",
            postgresql_using="gin",
            postgresql_ops={"retrieval_text": "gin_trgm_ops"},
        ),
        Index("ix_qa_document_text_segments_hash", "text_hash"),
        Index("ix_qa_document_text_segments_retrieval_hash", "retrieval_text_hash"),
        Index(
            "ix_qa_document_text_segments_run_order",
            "extraction_run_id",
            "source_order",
        ),
        Index(
            "ix_qa_document_text_segments_pdf_position",
            "file_id",
            "page_number",
            "paragraph_index",
        ),
        {"schema": "qa"},
    )

    file_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="所属文件 ID（逻辑引用）"
    )
    locator: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="可读定位符（如 page:3/paragraph:12）"
    )
    page_number: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="PDF 页码（从 1 开始）"
    )
    paragraph_index: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="DOCX 段落序号（从 0 开始）"
    )
    table_index: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="DOCX 表格序号（从 0 开始）"
    )
    cell_index: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="DOCX 表格单元序号（从 0 开始）"
    )
    extraction_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, comment="解析运行 ID；为空表示 legacy 数据"
    )
    source_order: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="文件内全局 raw block 顺序"
    )
    block_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="paragraph",
        server_default="paragraph",
        comment="paragraph/heading/list_item/table_header/table_row/pdf_block",
    )
    row_index: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="表格行序号"
    )
    column_index: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="表格列序号"
    )
    heading_path: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True, comment="标题层级路径"
    )
    source_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="坐标、表格网格、样式等结构元数据"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="正文片段")
    text_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="正文片段 SHA-256"
    )
    retrieval_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="去除版式标记后的检索文本；legacy 数据为空时回退 content",
    )
    retrieval_text_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="检索文本 SHA-256（规范化版本）"
    )


class DocumentExtractionRun(BaseModel):
    """一次可重建、可审计的 raw block 解析运行。"""

    __tablename__ = "document_extraction_runs"
    __table_args__ = (
        Index("ix_qa_document_extraction_runs_file", "file_id", "created_at"),
        Index("ix_qa_document_extraction_runs_queue", "status", "lease_until"),
        Index("ix_qa_document_extraction_runs_input", "file_id", "input_hash"),
        {"schema": "qa"},
    )

    file_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="native_text"
    )
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="native",
        server_default="native",
        comment="正文提取后端（native/mineru）",
    )
    provider_task_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="远程提取后端任务 ID",
    )
    provider_state: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="远程提取后端状态快照",
    )
    next_poll_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="下一次远程状态轮询时间",
    )
    provider_context: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        comment="远程任务续跑上下文（不含 token）",
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ExtractionRunStatus.QUEUED.value
    )
    block_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    char_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    statistics: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    worker_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retry_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )


class DocumentExtractionArtifact(BaseModel):
    """MinerU 等远程解析器产生的原始产物。

    产物与 ``file_id``、``extraction_run_id`` 同时关联，重解析只会追加新
    运行的产物，不会覆盖历史证据。对象本身保存在 QA 私有 MinIO bucket。
    """

    __tablename__ = "document_extraction_artifacts"
    __table_args__ = (
        Index("ix_qa_document_extraction_artifacts_file", "file_id", "created_at"),
        Index(
            "ix_qa_document_extraction_artifacts_run",
            "extraction_run_id",
            "artifact_type",
        ),
        Index(
            "uq_qa_document_extraction_artifacts_key",
            "storage_key",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "qa"},
    )

    file_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    extraction_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="markdown/zip/structure/asset",
    )
    source_name: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        comment="产物在 MinerU ZIP 中的原始路径",
    )
    storage_key: Mapped[str] = mapped_column(String(768), nullable=False)
    mime_type: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="application/octet-stream",
    )
    size_bytes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSON,
        nullable=True,
    )


class DocumentChunkRun(BaseModel):
    """raw block 的确定性分块运行。"""

    __tablename__ = "document_chunk_runs"
    __table_args__ = (
        Index("ix_qa_document_chunk_runs_file", "file_id", "created_at"),
        Index("ix_qa_document_chunk_runs_extraction", "extraction_run_id"),
        Index("ix_qa_document_chunk_runs_queue", "status", "lease_until"),
        {"schema": "qa"},
    )

    file_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    extraction_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    chunk_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ExtractionRunStatus.QUEUED.value
    )
    chunk_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    char_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    statistics: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    worker_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DocumentTextChunk(BaseModel):
    """供下游消费的派生上下文块。"""

    __tablename__ = "document_text_chunks"
    __table_args__ = (
        Index(
            "uq_qa_document_text_chunks_order",
            "chunk_run_id",
            "chunk_order",
            unique=True,
        ),
        Index("ix_qa_document_text_chunks_file", "file_id", "chunk_order"),
        Index("ix_qa_document_text_chunks_hash", "content_hash"),
        Index("ix_qa_document_text_chunks_retrieval_hash", "retrieval_text_hash"),
        Index(
            "ix_qa_document_text_chunks_content_trgm",
            "content",
            postgresql_using="gin",
            postgresql_ops={"content": "gin_trgm_ops"},
        ),
        Index(
            "ix_qa_document_text_chunks_retrieval_trgm",
            "retrieval_text",
            postgresql_using="gin",
            postgresql_ops={"retrieval_text": "gin_trgm_ops"},
        ),
        {"schema": "qa"},
    )

    file_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    chunk_run_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    chunk_order: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    retrieval_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="去除版式标记后的检索文本；legacy 数据为空时回退 content",
    )
    retrieval_text_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="检索文本 SHA-256（规范化版本）"
    )
    retrieval_char_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="检索文本字符数；legacy 数据为空"
    )
    retrieval_token_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="检索文本 token 估算；legacy 数据为空"
    )
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    heading_path: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSON, nullable=True
    )


class DocumentChunkBlock(BaseModel):
    """chunk 与 raw block 的完整映射；不把证据折叠成不可追溯文本。"""

    __tablename__ = "document_chunk_blocks"
    __table_args__ = (
        Index(
            "uq_qa_document_chunk_blocks_identity",
            "chunk_id",
            "segment_id",
            unique=True,
        ),
        Index("ix_qa_document_chunk_blocks_segment", "segment_id"),
        {"schema": "qa"},
    )

    chunk_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    segment_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    block_order: Mapped[int] = mapped_column(Integer, nullable=False)
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)


# 早期 service/repository 代码常使用简短的 TextSegment 名称；保留别名
TextSegment = DocumentTextSegment
