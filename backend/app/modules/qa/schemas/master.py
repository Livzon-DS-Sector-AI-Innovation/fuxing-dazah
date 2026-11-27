"""QA 主数据 API 契约。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

MasterObjectType = Literal["PRODUCT", "MATERIAL", "EQUIPMENT", "SUPPLIER", "REGION"]


LifecycleStatus = Literal["active", "inactive"]


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
        default=None,
        max_length=64,
        validation_alias=AliasChoices("responsible_department_id", "department_id"),
    )
    responsible_department_name_snapshot: str | None = Field(
        default=None,
        max_length=200,
        validation_alias=AliasChoices(
            "responsible_department_name_snapshot",
            "responsible_department_name",
            "department_name",
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
            return [
                item if isinstance(item, dict) else {"alias": item} for item in value
            ]
        return value


class MasterObjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    responsible_department_id: str | None = Field(
        default=None,
        max_length=64,
        validation_alias=AliasChoices("responsible_department_id", "department_id"),
    )
    responsible_department_name_snapshot: str | None = Field(
        default=None,
        max_length=200,
        validation_alias=AliasChoices(
            "responsible_department_name_snapshot",
            "responsible_department_name",
            "department_name",
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
            return [
                item if isinstance(item, dict) else {"alias": item} for item in value
            ]
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
