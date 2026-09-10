"""AI 配置中心 API Schema — 请求体 + 响应契约（backend-design §5、三期 §6）。

- ``AiProfileUpdate``：PUT /scheduler-config/ai-config/{profile} 请求体，
  字段全部可选（API 层 ``model_dump(exclude_unset=True)``）；
  「哪些字段适用于哪组 profile」的校验放 store 层
  （``_validate_profile_payload``，见 ticket 03 交付）；
- ``AiConfigTestRequest``：POST /scheduler-config/ai-config/test 请求体
  （profile 必填，config 可选覆盖）；
- ``AiConfigAuditItem``：GET /scheduler-config/ai-config/audits 响应行契约
  （append-only，before/after 的 api_key 已脱敏为 ****后4位）；
- ``AiScenarioUpdate`` / ``AiScenarioItemOut`` / ``AiScenarioAuditItem``：
  三期场景配置 API 契约（GET ai-scenarios / PUT ai-scenarios/{scenario} /
  GET ai-scenarios/audits；场景表无密钥，before/after 无需脱敏）。

本文件只描述 API 契约，不 import ORM model、不写业务规则。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool


class AiProfileUpdate(BaseModel):
    """PUT /ai-config/{profile} 请求体（字段全部可选，exclude_unset）。

    注意：``api_key`` 空串/None = 不修改（保留 DB 现值）；非空 = 覆盖。
    ``temperature``/``timeout`` 仅 text/vision（timeout 含 text_backup）、
    ``dims`` 仅 embedding 适用，跨 profile 传无关字段由 store 校验报 422。
    """

    api_key: str | None = Field(
        None, max_length=512, description="API Key；空串/None = 不修改（明文只在请求体中，不回显）"
    )
    base_url: str | None = Field(None, max_length=512, description="API Base URL；None = 不修改")
    model: str | None = Field(None, max_length=256, description="模型名；None = 不修改")
    dims: int | None = Field(None, ge=1, description="向量维度（仅 embedding 适用）")
    temperature: float | None = Field(
        None, ge=0, le=2, description="温度 0-2（仅 text/vision 适用）"
    )
    timeout: int | None = Field(
        None, ge=1, le=600, description="超时秒数 1-600（仅 text/vision/text_backup 适用）"
    )
    # StrictBool：拒绝 "yes"/1 等宽松布尔（WARN3 修复，与 AiScenarioUpdate.enabled 对齐）
    enabled: StrictBool | None = Field(None, description="是否启用；None = 保持现值")
    note: str | None = Field(None, max_length=255, description="备注；None = 保持现值")


class AiConfigTestRequest(BaseModel):
    """POST /ai-config/test 请求体（连通性探测，不写审计）。"""

    profile: str = Field(
        ..., description="profile 名（text/text_backup/vision/embedding/rerank，未注册返回 404）"
    )
    config: dict[str, Any] | None = Field(
        None, description="覆盖配置；提供时与当前生效配置覆盖式合并后探测（不保存）"
    )


class AiConfigAuditItem(BaseModel):
    """变更审计行（GET /ai-config/audits，append-only，最新在前）。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    profile: str
    action: str
    # jsonb 列既可存对象（字段级 diff）也可存数组，只声明 dict 会 500。
    before_json: dict[str, Any] | list[Any] | None
    after_json: dict[str, Any] | list[Any] | None
    operator_name: str | None
    created_at: datetime


class AiScenarioUpdate(BaseModel):
    """PUT /scheduler-config/ai-scenarios/{scenario} 请求体（字段全部可选，exclude_unset）。

    ``model_profile`` 允许值：text / text_backup / vision / embedding / rerank；
    非空值必须 ∈ 该场景 ``allowed_profiles``（白名单校验在 store 层，API 映射 422），
    ``null`` = 清绑定（按场景 model_type 默认）。``note`` 仅备注，不参与熔断。
    """

    # StrictBool：宽松 bool（如 "yes"）→ 422，防止误写走 Pydantic 隐式强转（WARN3 修复）
    enabled: StrictBool | None = Field(None, description="场景开关；None = 保持现值")
    model_profile: str | None = Field(
        None, max_length=32, description="绑定 profile 名；null = 清绑定按场景默认"
    )
    note: str | None = Field(None, max_length=255, description="备注；None = 保持现值")


class AiScenarioItemOut(BaseModel):
    """单场景合并视图（GET /ai-scenarios 列表项 & PUT 成功响应，与 store.ScenarioView 同构）。"""

    model_config = ConfigDict(from_attributes=True)

    scenario: str
    label: str
    description: str
    model_type: str
    channel: str
    deprecated: bool
    allowed_profiles: list[str]
    enabled: bool
    model_profile: str | None
    effective_profile: str
    source: str
    status: str


class AiScenarioAuditItem(BaseModel):
    """场景配置审计行（GET /ai-scenarios/audits，append-only，最新在前；无密钥不脱敏）。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    scenario: str
    action: str
    # jsonb 列既可存对象（字段级 diff）也可存数组，只声明 dict 会 500。
    before_json: dict[str, Any] | list[Any] | None
    after_json: dict[str, Any] | list[Any] | None
    operator_name: str | None
    created_at: datetime
