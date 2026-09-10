"""职业健康岗位危害台账 schemas — Enum 化（Pydantic v2）。

对齐 backend-design.md §1.3 OhPosition 列定义。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class OhHazardFactorsStatus(StrEnum):
    """岗位危害因素状态"""

    FILLED = "filled"
    EMPTY = "empty"
    INFERRED = "inferred"


OH_HAZARD_FACTORS_STATUS_OPTIONS = [
    {"value": OhHazardFactorsStatus.FILLED, "label": "已填"},
    {"value": OhHazardFactorsStatus.EMPTY, "label": "未填"},
    {"value": OhHazardFactorsStatus.INFERRED, "label": "AI 推断"},
]


class OhPositionBase(BaseModel):
    """岗位危害因素台账基础字段"""

    model_config = ConfigDict(use_enum_values=True)

    feishu_record_id: str | None = Field(None, max_length=64, description="Bitable 记录 ID")
    source: str = Field("manual", max_length=16, description="数据来源: bitable/manual")
    department: str | None = Field(None, max_length=100, description="部门")
    position: str | None = Field(None, max_length=100, description="岗位")
    job_title: str | None = Field(None, max_length=100, description="职务")
    hazard_factors: list[str] | None = Field(None, description="危害因素 [标准名]")
    hazard_factors_status: OhHazardFactorsStatus | None = Field(None, description="危害因素状态")
    notes: str | None = Field(None, description="备注")


class OhPositionCreate(OhPositionBase):
    """创建岗位台账"""

    pass


class OhPositionUpdate(BaseModel):
    """更新岗位台账（所有字段可选）"""

    feishu_record_id: str | None = Field(None, max_length=64)
    department: str | None = Field(None, max_length=100)
    position: str | None = Field(None, max_length=100)
    job_title: str | None = Field(None, max_length=100)
    hazard_factors: list[str] | None = None
    hazard_factors_status: OhHazardFactorsStatus | None = None
    notes: str | None = None


class OhPositionResponse(OhPositionBase):
    """岗位台账响应"""

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)
