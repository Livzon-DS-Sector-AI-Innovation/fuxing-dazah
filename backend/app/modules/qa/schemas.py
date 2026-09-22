"""QA 模块的 API 契约。

QA 的记录是对外部已批准文件及质量主数据的登记，不承载审批流。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

MasterObjectType = Literal["PRODUCT", "MATERIAL", "EQUIPMENT", "SUPPLIER", "REGION"]
LifecycleStatus = Literal["active", "inactive"]
ExtractionStatus = Literal[
    "queued", "processing", "ready", "text_not_available", "unsupported", "failed"
]
AIAuthorityPolicy = Literal["authoritative", "reference", "disabled"]
AIAnalysisStatus = Literal["queued", "processing", "ready", "partial", "failed", "stale"]


class AliasIn(BaseModel):
    alias: str = Field(min_length=1, max_length=200)


class SourceLinkIn(BaseModel):
    source_module: str = Field(min_length=1, max_length=50)
    source_entity: str = Field(min_length=1, max_length=100)
    source_id: uuid.UUID


class MasterObjectCreate(BaseModel):
    object_type: MasterObjectType = Field(
        validation_alias=AliasChoices("object_type", "kind", "type")
    )
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    responsible_department_id: str | None = Field(
        default=None, max_length=64,
        validation_alias=AliasChoices("responsible_department_id", "department_id"),
    )
    responsible_department_name_snapshot: str | None = Field(
        default=None, max_length=200,
        validation_alias=AliasChoices(
            "responsible_department_name_snapshot", "responsible_department_name", "department_name"
        ),
    )
    region_parent_id: uuid.UUID | None = Field(
        default=None,
        validation_alias=AliasChoices("region_parent_id", "parent_id"),
    )
    contact_name: str | None = Field(default=None, max_length=100)
    contact_phone: str | None = Field(default=None, max_length=50)
    contact_email: str | None = Field(default=None, max_length=255)
    remark: str | None = Field(default=None, max_length=4000)
    # 上限与 MasterObjectUpdate 对齐：创建路径对每个别名/来源各发一次查询（别名查重、
    # 来源走跨模块校验），不封顶时一个请求就能压出成千上万次串行往返。
    aliases: list[AliasIn | str] = Field(default_factory=list, max_length=200)
    sources: list[SourceLinkIn] = Field(default_factory=list, max_length=50)

    @field_validator("code", "name", mode="before")
    @classmethod
    def strip_required(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value

    @field_validator("aliases", mode="before")
    @classmethod
    def normalize_alias_inputs(cls, value: object) -> object:
        if isinstance(value, list):
            return [item if isinstance(item, dict) else {"alias": item} for item in value]
        return value


class MasterObjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    responsible_department_id: str | None = Field(
        default=None, max_length=64,
        validation_alias=AliasChoices("responsible_department_id", "department_id"),
    )
    responsible_department_name_snapshot: str | None = Field(
        default=None, max_length=200,
        validation_alias=AliasChoices(
            "responsible_department_name_snapshot", "responsible_department_name", "department_name"
        ),
    )
    region_parent_id: uuid.UUID | None = Field(
        default=None, validation_alias=AliasChoices("region_parent_id", "parent_id")
    )
    contact_name: str | None = Field(default=None, max_length=100)
    contact_phone: str | None = Field(default=None, max_length=50)
    contact_email: str | None = Field(default=None, max_length=255)
    remark: str | None = Field(default=None, max_length=4000)
    aliases: list[AliasIn | str] | None = Field(default=None, max_length=200)
    sources: list[SourceLinkIn] | None = Field(default=None, max_length=50)

    @field_validator("aliases", mode="before")
    @classmethod
    def normalize_alias_inputs(cls, value: object) -> object:
        if isinstance(value, list):
            return [item if isinstance(item, dict) else {"alias": item} for item in value]
        return value


class MasterObjectStatusIn(BaseModel):
    status: LifecycleStatus


class MasterObjectAliasOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    alias: str
    normalized_alias: str
    created_at: datetime | None = None


class MasterObjectSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    source_module: str
    source_entity: str
    source_id: uuid.UUID
    source_code_snapshot: str | None = None
    source_name_snapshot: str | None = None
    source_available: bool | None = None
    created_at: datetime | None = None


class MasterObjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    object_type: MasterObjectType
    code: str
    name: str
    description: str | None = None
    status: LifecycleStatus
    responsible_department_id: str | None = None
    responsible_department_name_snapshot: str | None = None
    region_parent_id: uuid.UUID | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    remark: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    aliases: list[MasterObjectAliasOut] = Field(default_factory=list)
    sources: list[MasterObjectSourceOut] = Field(default_factory=list)
    document_count: int = 0


class DepartmentReferenceOut(BaseModel):
    id: uuid.UUID
    feishu_department_id: str
    name: str
    path: str | None = None
    available: bool = True


class ExternalSourceOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    source_module: str
    source_entity: str
    available: bool = True


class DocumentTypeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    ai_source_policy: AIAuthorityPolicy = "authoritative"

    @field_validator("code", "name", mode="before")
    @classmethod
    def strip_value(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class DocumentTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    status: LifecycleStatus | None = None
    description: str | None = Field(default=None, max_length=1000)
    ai_source_policy: AIAuthorityPolicy | None = None

    @field_validator("status", mode="before")
    @classmethod
    def reject_null_status(cls, value: object) -> object:
        if value is None:
            raise ValueError("状态不能为 null")
        return value


class DocumentTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    name: str
    status: LifecycleStatus
    description: str | None = None
    ai_source_policy: AIAuthorityPolicy = "authoritative"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DocumentCreate(BaseModel):
    document_no: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=500)
    document_type_id: uuid.UUID
    responsible_department_id: str | None = Field(
        default=None, max_length=64,
        validation_alias=AliasChoices("responsible_department_id", "department_id"),
    )
    responsible_department_name_snapshot: str | None = Field(
        default=None, max_length=200,
        validation_alias=AliasChoices(
            "responsible_department_name_snapshot", "responsible_department_name", "department_name"
        ),
    )
    @field_validator("document_no", "title", mode="before")
    @classmethod
    def strip_value(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    document_type_id: uuid.UUID | None = None
    responsible_department_id: str | None = Field(
        default=None, max_length=64,
        validation_alias=AliasChoices("responsible_department_id", "department_id"),
    )
    responsible_department_name_snapshot: str | None = Field(
        default=None, max_length=200,
        validation_alias=AliasChoices(
            "responsible_department_name_snapshot", "responsible_department_name", "department_name"
        ),
    )


class DocumentFileSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    original_filename: str
    extension: str
    mime_type: str | None = None
    size_bytes: int
    sha256: str
    extraction_status: ExtractionStatus
    extraction_error: str | None = None
    retry_count: int = 0
    parser_mode: str = "native_text"
    parser_version: str | None = None
    current_extraction_run_id: uuid.UUID | None = None
    current_chunk_run_id: uuid.UUID | None = None
    legacy: bool = False


class RelationIn(BaseModel):
    master_object_id: uuid.UUID
    relation_type: str = Field(default="APPLIES_TO", max_length=50)

    @field_validator("relation_type", mode="before")
    @classmethod
    def normalize_relation(cls, value: str) -> str:
        return value.strip().upper() if isinstance(value, str) else value


class RelationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    master_object_id: uuid.UUID
    relation_type: str
    code_snapshot: str
    name_snapshot: str
    object_type: str | None = None
    status: str | None = None


class DocumentVersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    document_id: uuid.UUID
    version_label: str
    version_sequence: int
    status: str
    approved_declared: bool
    locked_at: datetime | None = None
    first_locked_at: datetime | None = None
    created_at: datetime | None = None
    file: DocumentFileSummary | None = None
    relations: list[RelationOut] = Field(default_factory=list)


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    document_no: str
    title: str
    document_type_id: uuid.UUID
    document_type: DocumentTypeOut | None = None
    responsible_department_id: str | None = None
    responsible_department_name_snapshot: str | None = None
    status: LifecycleStatus
    current_version_id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    versions: list[DocumentVersionSummary] = Field(default_factory=list)


class DocumentListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    document_no: str
    title: str
    document_type_id: uuid.UUID
    document_type_name: str | None = None
    responsible_department_id: str | None = None
    responsible_department_name_snapshot: str | None = None
    status: LifecycleStatus
    current_version_id: uuid.UUID | None = None
    current_version_label: str | None = None
    current_extraction_status: ExtractionStatus | None = None
    version_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SearchHit(BaseModel):
    kind: Literal["master_object", "department", "document", "document_segment"]
    id: uuid.UUID
    score: float = 0
    code: str | None = None
    title: str | None = None
    name: str | None = None
    object_type: str | None = None
    document_id: uuid.UUID | None = None
    document_no: str | None = None
    version_id: uuid.UUID | None = None
    version_label: str | None = None
    snippet: str | None = None
    locator: str | None = None
    status: str | None = None


class RelationUpdateRequest(BaseModel):
    relations: list[RelationIn] = Field(default_factory=list, max_length=200)


class AuditLogOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None = None
    action: str
    resource_type: str | None = None
    resource_id: uuid.UUID | None = None
    old_value: dict[str, Any] | None = None
    new_value: dict[str, Any] | None = None
    extra: dict[str, Any] | None = None
    created_at: datetime | None = None


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
    content_preview: str
    content_truncated: bool
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


class AIAnalysisTriggerRequest(BaseModel):
    force: bool = False


class AIRelationConfirmationRequest(BaseModel):
    accepted_suggestion_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    manual_master_object_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    remove_master_object_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)


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


