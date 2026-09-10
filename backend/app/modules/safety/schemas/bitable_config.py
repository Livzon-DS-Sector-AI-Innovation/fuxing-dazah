"""Bitable 配置中心 API Schema — 请求体 + 响应契约（backend-design §4.1-4.2）。

- 请求体：``ConnectionUpdate``（PUT connections/{domain}/{kind}）、
  ``MappingsUpdate``（PUT mappings/{domain}/{kind}）、``TestConnectionRequest``；
- 响应契约：``ConnectionViewOut`` / ``DomainOverviewOut`` / ``MappingsView`` /
  ``TestConnectionResult`` / ``ResubscribeResult`` / ``AuditRow``（端点经
  ``success_response(data=...)`` 返回，结构与本文件一致，供前端对齐）。

校验要点（§2.1/§2.2 与 ticket 03）：
- ``field_type`` 枚举 8 种（``registry.FieldType``，语义对齐 audit/parser.py）；
- ``value_map`` 为 ``Dict[str, str]``（源中文值 → 模型枚举）；
- ``combined`` 仅 ``combined_text`` 类型可出现，结构 ``{parts, sep, prefix}``；
- ``extra_table_ids`` 规则：每项 ``tbl`` 开头、非空、去重、不得包含主表
  table_id（域级白名单「仅 central_alarm 支持」由 API 层按路径 domain 校验，
  见 api/bitable_config.py）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.modules.safety.bitable_config.registry import FieldType

# 连接行 status：db=DB 行 / default=registry 默认 / disabled=停用 / missing=无配置
ConnectionStatus = Literal["db", "default", "disabled", "missing"]
# 域总览 kind 状态（API 层把 store 的 db → configured 语义映射后输出）
KindOverviewStatus = Literal["configured", "default", "disabled", "missing"]
# 域级 config_status 四态：全部已配置 / 部分已配置 / 全部停用 / 全部缺失
DomainConfigStatus = Literal["configured", "partial", "disabled", "missing"]
# 映射来源：db=DB 行 / default=registry 默认
MappingStatus = Literal["db", "default"]

# 非空字符串（strip 后校验，空白串 → 422）
_NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
# extra_table_ids 表 ID：strip 后必须以 tbl 开头（白名单域校验，§2.1）
_TableIdStr = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^tbl")]


class ConnectionUpdate(BaseModel):
    """PUT /bitable-config/connections/{domain}/{kind} 请求体。

    app_token/table_id 必填（连接核心身份，store 校验非空）；
    enabled/extra_table_ids/note 可选——不传保持 DB 现值不变
    （API 层 ``model_dump(exclude_unset=True)``），
    extra_table_ids 显式传 null 表示清空白名单。
    """

    app_token: _NonEmptyStr = Field(
        ..., max_length=128, description="飞书多维表格 app_token（base/wiki 文档 token）"
    )
    table_id: _NonEmptyStr = Field(
        ..., max_length=128, description="表 table_id（central_alarm 为白名单主表）"
    )
    enabled: bool = Field(True, description="是否启用（false=停用，不回退 registry 默认）")
    extra_table_ids: list[_TableIdStr] | None = Field(
        None,
        min_length=1,
        description="仅 central_alarm：白名单其余表 ID（tbl 开头/非空/去重/不含主表）",
    )
    note: str | None = Field(None, max_length=255, description="备注")

    @model_validator(mode="after")
    def _check_extra_table_ids(self) -> ConnectionUpdate:
        extra = self.extra_table_ids
        if extra is None:
            return self
        if len(set(extra)) != len(extra):
            raise ValueError("extra_table_ids 不能包含重复表 ID")
        if self.table_id in extra:
            raise ValueError("extra_table_ids 不能包含主表 table_id")
        return self


class CombinedSpec(BaseModel):
    """combined_text 专属拼接结构（§2.2）。"""

    parts: list[str] = Field(default_factory=list, description="参与拼接的源字段名列表")
    sep: str = Field(default="\n", description="拼接分隔符")
    prefix: dict[str, str] = Field(
        default_factory=dict, description="按源字段名的前缀（如 {字段1: 提示：}）"
    )


class MappingItem(BaseModel):
    """字段映射单项（§2.2 JSONB 结构，PUT mappings 校验）。"""

    source_field: str | None = Field(
        None, description="Bitable 中文字段名；combined_text 时可为 null"
    )
    target_field: _NonEmptyStr = Field(
        ..., max_length=128, description="目标模型字段名（英文 snake_case）"
    )
    field_type: FieldType = Field(
        default="text", description="8 种字段类型（语义对齐 audit/parser.py）"
    )
    default_value: Any = Field(None, description="解析缺失/失败时的兜底值")
    value_map: dict[str, str] | None = Field(
        None, description="enum 专属：源中文值 → 模型枚举"
    )
    optional: bool = Field(False, description="true=读取失败仅告警不阻断整条记录")
    combined: CombinedSpec | None = Field(
        None, description="仅 combined_text 类型出现"
    )

    @model_validator(mode="after")
    def _check_combined(self) -> MappingItem:
        if self.combined is not None and self.field_type != "combined_text":
            raise ValueError(
                f"combined 仅 combined_text 类型支持（target_field={self.target_field}）"
            )
        return self


class MappingsUpdate(BaseModel):
    """PUT /bitable-config/mappings/{domain}/{kind} 请求体（JSONB 全量替换）。"""

    mappings: list[MappingItem] = Field(
        ..., description="字段映射列表（全量替换；空列表=清空映射）"
    )


class TestConnectionRequest(BaseModel):
    """POST /bitable-config/test-connection 请求体。"""

    app_token: _NonEmptyStr = Field(
        ..., max_length=128, description="待校验的 app_token"
    )
    table_id: _NonEmptyStr = Field(
        ..., max_length=128, description="待校验的 table_id"
    )


# ═══════════════════════════════════════════════════════════════
# 响应契约（§4.2；端点以 success_response(data=...) 返回同构 dict）
# ═══════════════════════════════════════════════════════════════


class ConnectionViewOut(BaseModel):
    """连接视图响应（与 store.ConnectionView 一致，status 四态）。"""

    model_config = ConfigDict(from_attributes=True)

    domain: str
    kind: str
    app_token: str
    table_id: str
    extra_table_ids: list[str] | None
    enabled: bool
    note: str | None
    status: ConnectionStatus


class KindOverviewOut(BaseModel):
    """域总览单 kind 条目。"""

    kind: str
    label: str
    app_token: str
    table_id: str
    enabled: bool
    status: KindOverviewStatus
    mapping_status: MappingStatus


class DomainOverviewOut(BaseModel):
    """域总览条目（14 域，GET /domains）。"""

    key: str
    label: str
    purpose: str
    subscribe: Literal["drive", "record"]
    config_status: DomainConfigStatus
    kinds: list[KindOverviewOut]


class MappingsView(BaseModel):
    """映射读/写响应（GET/PUT /mappings/{domain}/{kind}）。"""

    domain: str
    kind: str
    status: MappingStatus
    mappings: list[dict[str, Any]]


class TestConnectionResult(BaseModel):
    """test-connection 成功响应。"""

    ok: bool
    app_token: str
    table_id: str
    meta: dict[str, Any] | None = None


class ResubscribeResult(BaseModel):
    """resubscribe 响应（results: {kind: ok|skipped|failed} 或 {skipped: True}）。"""

    domain: str
    results: dict[str, Any]


class AuditRow(BaseModel):
    """变更审计行（GET /audits，append-only）。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    domain: str
    kind: str
    action: str
    # jsonb 列既可存对象（字段级 diff）也可存数组（如字段映射定义列表），
    # 只声明 dict 会让列表型审计行在 model_validate 时 500。
    before_json: dict[str, Any] | list[Any] | None
    after_json: dict[str, Any] | list[Any] | None
    operator_name: str | None
    created_at: datetime
