"""职业健康异常随访 schemas — Enum 化（Pydantic v2）。

对齐 backend-design.md §1.6 OhFollowup 列定义 + 状态机 open→followed→closed。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class OhFollowupStatus(StrEnum):
    """随访状态（状态机: open→followed→closed；expired 二期派生）"""

    OPEN = "open"
    FOLLOWED = "followed"
    CLOSED = "closed"
    EXPIRED = "expired"


OH_FOLLOWUP_STATUS_OPTIONS = [
    {"value": OhFollowupStatus.OPEN, "label": "待处置", "color": "red"},
    {"value": OhFollowupStatus.FOLLOWED, "label": "已处置待闭环", "color": "orange"},
    {"value": OhFollowupStatus.CLOSED, "label": "已关闭", "color": "green"},
    {"value": OhFollowupStatus.EXPIRED, "label": "已逾期", "color": "default"},
]


class OhFollowupType(StrEnum):
    """随访类型"""

    RE_EXAMINATION = "re_examination"
    SPECIALIST_REFERRAL = "specialist_referral"
    TRANSFER_POST = "transfer_post"
    HEALTH_MONITOR = "health_monitor"


OH_FOLLOWUP_TYPE_OPTIONS = [
    {"value": OhFollowupType.RE_EXAMINATION, "label": "复查"},
    {"value": OhFollowupType.SPECIALIST_REFERRAL, "label": "专科转诊"},
    {"value": OhFollowupType.TRANSFER_POST, "label": "调离岗位"},
    {"value": OhFollowupType.HEALTH_MONITOR, "label": "健康监护"},
]


class OhFollowupCategory(StrEnum):
    """异常指标类别"""

    LAB = "lab"
    VISION = "vision"
    HEARING = "hearing"
    PHYSIQUE = "physique"
    OTHER = "other"


OH_FOLLOWUP_CATEGORY_OPTIONS = [
    {"value": OhFollowupCategory.LAB, "label": "检验"},
    {"value": OhFollowupCategory.VISION, "label": "视力"},
    {"value": OhFollowupCategory.HEARING, "label": "听力"},
    {"value": OhFollowupCategory.PHYSIQUE, "label": "体格"},
    {"value": OhFollowupCategory.OTHER, "label": "其他"},
]


class OhAbnormalLevel(StrEnum):
    """异常程度"""

    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"


OH_ABNORMAL_LEVEL_OPTIONS = [
    {"value": OhAbnormalLevel.MILD, "label": "轻度", "color": "blue"},
    {"value": OhAbnormalLevel.MODERATE, "label": "中度", "color": "orange"},
    {"value": OhAbnormalLevel.SEVERE, "label": "重度", "color": "red"},
]


class OhFollowupBase(BaseModel):
    """异常随访基础字段"""

    model_config = ConfigDict(use_enum_values=True)

    exam_id: uuid.UUID | None = Field(None, description="关联 oh_health_exams.id")
    person_id: uuid.UUID | None = Field(None, description="关联 oh_persons.id")
    person_name: str | None = Field(None, max_length=100, description="人员姓名（冗余）")
    indicator_name: str | None = Field(None, max_length=100, description="异常指标名")
    indicator_value: str | None = Field(None, max_length=100, description="指标值")
    reference_range: str | None = Field(None, max_length=100, description="参考范围")
    abnormal_level: OhAbnormalLevel | None = Field(None, description="异常程度")
    category: OhFollowupCategory | None = Field(None, description="指标类别")
    followup_type: OhFollowupType | None = Field(None, description="随访类型")
    followup_date: date | None = Field(None, description="建议复查/处置日期")
    status: OhFollowupStatus = Field(OhFollowupStatus.OPEN, description="随访状态")
    action_taken: str | None = Field(None, description="处置记录")
    responsible: str | None = Field(None, max_length=100, description="责任人")
    closed_at: datetime | None = Field(None, description="关闭时间")
    source: str = Field("ai", max_length=16, description="来源: ai/manual")
    notes: str | None = Field(None, description="备注")


class OhFollowupCreate(OhFollowupBase):
    """创建随访（手动补录）"""

    pass


class OhFollowupUpdate(BaseModel):
    """更新随访（所有字段可选）"""

    model_config = ConfigDict(use_enum_values=True)

    indicator_name: str | None = Field(None, max_length=100)
    indicator_value: str | None = Field(None, max_length=100)
    reference_range: str | None = Field(None, max_length=100)
    abnormal_level: OhAbnormalLevel | None = None
    category: OhFollowupCategory | None = None
    followup_type: OhFollowupType | None = None
    followup_date: date | None = None
    status: OhFollowupStatus | None = None
    action_taken: str | None = None
    responsible: str | None = Field(None, max_length=100)
    closed_at: datetime | None = None
    notes: str | None = None


class OhFollowupResponse(OhFollowupBase):
    """异常随访响应"""

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class CloseFollowupRequest(BaseModel):
    """关闭随访请求"""

    action_taken: str = Field(..., description="处置记录")
