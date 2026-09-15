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

    @field_validator("code", "name", mode="before")
    @classmethod
    def strip_value(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class DocumentTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    status: LifecycleStatus | None = None
    description: str | None = Field(default=None, max_length=1000)

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
