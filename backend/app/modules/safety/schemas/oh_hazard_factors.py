"""职业健康危害因素 PPE 字典 schemas — Enum 化（Pydantic v2）。

对齐 backend-design.md §1.4 OhHazardFactor 列定义。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OhHazardFactorBase(BaseModel):
    """危害因素 PPE 映射字典基础字段"""

    model_config = ConfigDict(use_enum_values=True)

    feishu_record_id: str | None = Field(None, max_length=64, description="Bitable 记录 ID")
    source: str = Field("manual", max_length=16, description="数据来源: bitable/manual")
    factor_name: str = Field(..., max_length=100, description="危害因素标准名")
    ppe_respiratory: str | None = Field(None, description="呼吸防护用品")
    notes: str | None = Field(None, description="备注")


class OhHazardFactorCreate(OhHazardFactorBase):
    """创建危害因素字典项"""

    pass


class OhHazardFactorUpdate(BaseModel):
    """更新危害因素字典项（所有字段可选）"""

    feishu_record_id: str | None = Field(None, max_length=64)
    factor_name: str | None = Field(None, max_length=100)
    ppe_respiratory: str | None = None
    notes: str | None = None


class OhHazardFactorResponse(OhHazardFactorBase):
    """危害因素字典项响应"""

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)
