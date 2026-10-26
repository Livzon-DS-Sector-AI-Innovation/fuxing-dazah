"""QA AI 分析模型：分析运行、实体观察、关系建议与主数据提案。"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.qa.models.document import RelationType
from app.shared.base_model import BaseModel


class AIAnalysisStatus(enum.StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    PARTIAL = "partial"
    FAILED = "failed"
    STALE = "stale"


class AIProposalStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONFLICT = "conflict"
    STALE = "stale"


class AISuggestionStatus(enum.StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    STALE = "stale"


class DocumentAIAnalysisRun(BaseModel):
    """一次文档 AI 分析请求的持久化状态。"""

    __tablename__ = "document_ai_analysis_runs"
    __table_args__ = (
        Index("ix_qa_document_ai_analysis_runs_version", "version_id", "created_at"),
        Index("ix_qa_document_ai_analysis_runs_queue", "status", "lease_until"),
        Index(
            "ix_qa_document_ai_analysis_runs_fingerprint",
            "version_id",
            "input_fingerprint",
        ),
        {"schema": "qa"},
    )

    version_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    file_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    extraction_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    chunk_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=AIAnalysisStatus.QUEUED.value
    )
    provider: Mapped[str] = mapped_column(
        String(64), nullable=False, default="openai-compatible"
    )
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    catalog_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_policy: Mapped[str] = mapped_column(String(24), nullable=False)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    retry_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    entity_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    suggestion_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    proposal_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    processed_chunks: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    total_chunks: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
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


class DocumentEntityObservation(BaseModel):
    """模型/规则发现的实体事实；不是正式主数据。"""

    __tablename__ = "document_entity_observations"
    __table_args__ = (
        Index(
            "ix_qa_document_entity_observations_run", "analysis_run_id", "source_order"
        ),
        Index("ix_qa_document_entity_observations_normalized", "normalized_text"),
        Index("ix_qa_document_entity_observations_evidence_hash", "evidence_hash"),
        {"schema": "qa"},
    )

    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    raw_block_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    mention_text: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_text: Mapped[str] = mapped_column(String(500), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="证据定位与片段内容的稳定哈希"
    )
    locator: Mapped[str] = mapped_column(String(255), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paragraph_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    table_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    row_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    column_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    extraction_method: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="deterministic",
        server_default="deterministic",
    )
    normalization_hint: Mapped[str | None] = mapped_column(String(500), nullable=True)
    observation_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSON, nullable=True
    )


class DocumentRelationSuggestion(BaseModel):
    """已有 QA 主数据的候选关联；确认前不写正式关系表。"""

    __tablename__ = "document_relation_suggestions"
    __table_args__ = (
        Index(
            "uq_qa_document_relation_suggestions_identity",
            "analysis_run_id",
            "observation_id",
            "master_object_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "ix_qa_document_relation_suggestions_run",
            "analysis_run_id",
            "status",
            "rank",
        ),
        CheckConstraint(
            "relation_type = 'APPLIES_TO'",
            name="ck_qa_document_relation_suggestions_type",
        ),
        {"schema": "qa"},
    )

    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    observation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    master_object_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=RelationType.APPLIES_TO.value,
        server_default=RelationType.APPLIES_TO.value,
    )
    match_method: Mapped[str] = mapped_column(String(32), nullable=False)
    rank: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    selected_by_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=AISuggestionStatus.PENDING.value,
        server_default=AISuggestionStatus.PENDING.value,
    )
    rationale: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class MasterObjectProposal(BaseModel):
    """待人工审核的 QA 主数据新建/字段变更提案。"""

    __tablename__ = "master_object_proposals"
    __table_args__ = (
        CheckConstraint(
            "proposal_type IN ('create', 'update')",
            name="ck_qa_master_object_proposals_type",
        ),
        Index("ix_qa_master_object_proposals_status", "status", "created_at"),
        Index("ix_qa_master_object_proposals_run", "analysis_run_id"),
        Index("ix_qa_master_object_proposals_target", "target_master_object_id"),
        {"schema": "qa"},
    )

    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    observation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    proposal_type: Mapped[str] = mapped_column(
        String(24), nullable=False, comment="create/update"
    )
    target_master_object_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    proposed_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    field_diffs: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    evidence: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    conflicts: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    base_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    base_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=AIProposalStatus.PENDING.value,
        server_default=AIProposalStatus.PENDING.value,
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
