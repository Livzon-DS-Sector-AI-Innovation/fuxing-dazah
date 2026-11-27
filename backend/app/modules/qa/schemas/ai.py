"""QA AI 分析与主数据提案 API 契约。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)

from app.modules.qa.schemas.document import AIAuthorityPolicy

AIAnalysisStatus = Literal[
    "queued", "processing", "ready", "partial", "failed", "stale"
]


class AIAnalysisTriggerRequest(BaseModel):
    force: bool = False


class AIRelationConfirmationRequest(BaseModel):
    accepted_suggestion_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=500
    )
    manual_master_object_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=200
    )
    remove_master_object_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=200
    )


class AIEntityObservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    chunk_id: uuid.UUID | None = None
    raw_block_id: uuid.UUID | None = None
    mention_text: str
    normalized_text: str
    entity_type: str
    quote: str
    evidence_hash: str
    locator: str
    page_number: int | None = None
    paragraph_index: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    column_index: int | None = None
    source_order: int | None = None
    confidence: float = 0
    extraction_method: str = "deterministic"
    normalization_hint: str | None = None
    observation_metadata: dict[str, Any] | None = None


class AIRelationSuggestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    observation_id: uuid.UUID
    master_object_id: uuid.UUID
    relation_type: str
    match_method: str
    rank: int
    confidence: float
    selected_by_default: bool
    status: str
    rationale: str | None = None


class MasterObjectProposalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    analysis_run_id: uuid.UUID
    observation_id: uuid.UUID | None = None
    proposal_type: str
    target_master_object_id: uuid.UUID | None = None
    object_type: str
    proposed_payload: dict[str, Any]
    field_diffs: dict[str, Any] | None = None
    evidence: list[dict[str, Any]] | None = None
    conflicts: list[dict[str, Any]] | None = None
    base_snapshot: dict[str, Any] | None = None
    base_fingerprint: str | None = None
    status: str
    created_at: datetime | None = None
    reviewed_at: datetime | None = None


class AIAnalysisRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    version_id: uuid.UUID
    file_id: uuid.UUID
    extraction_run_id: uuid.UUID | None = None
    chunk_run_id: uuid.UUID | None = None
    status: AIAnalysisStatus
    provider: str
    model: str
    prompt_version: str
    schema_version: str
    source_policy: AIAuthorityPolicy
    catalog_fingerprint: str
    input_fingerprint: str
    processed_chunks: int = 0
    total_chunks: int = 0
    entity_count: int = 0
    suggestion_count: int = 0
    proposal_count: int = 0
    error: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    observations: list[AIEntityObservationOut] = Field(default_factory=list)
    suggestions: list[AIRelationSuggestionOut] = Field(default_factory=list)
    proposals: list[MasterObjectProposalOut] = Field(default_factory=list)


class MasterObjectProposalApproveRequest(BaseModel):
    """允许审核人修正提案字段；sources 明确不接受 AI 自动来源。"""

    payload: dict[str, Any] | None = None
