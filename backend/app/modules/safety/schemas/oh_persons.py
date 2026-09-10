"""职业健康人员汇总台账 schemas — Enum 化（Pydantic v2）。

对齐 backend-design.md §1.1 OhPerson 列定义。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.modules.safety.schemas.oh_health_exams import OhAiConclusion, OhExamType


class OhWorkStatus(str, Enum):
    """在岗状态（原「最后体检状态」更名，D6）"""

    ON_POST = "on_post"
    OFF_POST = "off_post"
    PRE_EMPLOYMENT = "pre_employment"
    TRANSFER = "transfer"


OH_WORK_STATUS_OPTIONS = [
    {"value": OhWorkStatus.ON_POST, "label": "在岗"},
    {"value": OhWorkStatus.OFF_POST, "label": "离岗"},
    {"value": OhWorkStatus.PRE_EMPLOYMENT, "label": "岗前"},
    {"value": OhWorkStatus.TRANSFER, "label": "转岗"},
]


class OhPersonBase(BaseModel):
    """人员汇总台账基础字段"""

    model_config = ConfigDict(use_enum_values=True)

    feishu_record_id: str | None = Field(None, max_length=64, description="Bitable 记录 ID")
    source: str = Field("manual", max_length=16, description="数据来源: bitable/manual")
    name: str = Field(..., max_length=100, description="员工姓名")
    id_card_no: str | None = Field(None, max_length=32, description="身份证号（关联键）")
    employee_no: str | None = Field(None, max_length=64, description="工号")
    user_id: uuid.UUID | None = Field(None, description="关联 identity.users.id")
    open_id: str | None = Field(None, max_length=64, description="飞书 open_id")
    department: str | None = Field(None, max_length=100, description="部门")
    position: str | None = Field(None, max_length=100, description="岗位")
    gender: str | None = Field(None, max_length=16, description="性别")
    age: int | None = Field(None, description="年龄")
    marital_status: str | None = Field(None, max_length=16, description="婚姻状况")
    phone: str | None = Field(None, max_length=32, description="电话")
    total_work_years: float | None = Field(None, description="总工龄（年.月折算）")
    hazard_exposure_years: float | None = Field(None, description="接害工龄（年.月折算）")
    hazard_factors: list[str] | None = Field(None, description="接触危害因素 [标准名]")
    last_exam_at: datetime | None = Field(None, description="最后体检时间（平台回填）")
    last_exam_type: OhExamType | None = Field(None, description="最后体检类别")
    last_exam_conclusion: OhAiConclusion | None = Field(None, description="最后体检结论（ai_conclusion 归一）")
    last_exam_summary: str | None = Field(None, description="最后体检摘要")
    exam_record_ids: list[str] | None = Field(None, description="体检记录 ID 数组")
    safety_officer: str | None = Field(None, max_length=100, description="部门安全员")
    work_status: OhWorkStatus | None = Field(None, description="在岗状态")
    notes: str | None = Field(None, description="备注")


class OhPersonCreate(OhPersonBase):
    """创建人员台账"""

    pass


class OhPersonUpdate(BaseModel):
    """更新人员台账（所有字段可选）"""

    model_config = ConfigDict(use_enum_values=True)

    feishu_record_id: str | None = Field(None, max_length=64)
    name: str | None = Field(None, max_length=100)
    id_card_no: str | None = Field(None, max_length=32)
    employee_no: str | None = Field(None, max_length=64)
    user_id: uuid.UUID | None = None
    open_id: str | None = Field(None, max_length=64)
    department: str | None = Field(None, max_length=100)
    position: str | None = Field(None, max_length=100)
    gender: str | None = Field(None, max_length=16)
    age: int | None = None
    marital_status: str | None = Field(None, max_length=16)
    phone: str | None = Field(None, max_length=32)
    total_work_years: float | None = None
    hazard_exposure_years: float | None = None
    hazard_factors: list[str] | None = None
    last_exam_at: datetime | None = None
    last_exam_type: OhExamType | None = None
    last_exam_conclusion: OhAiConclusion | None = None
    last_exam_summary: str | None = None
    exam_record_ids: list[str] | None = None
    safety_officer: str | None = Field(None, max_length=100)
    work_status: OhWorkStatus | None = None
    notes: str | None = None


class OhPersonResponse(OhPersonBase):
    """人员台账响应"""

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class OhPersonDetail(OhPersonResponse):
    """人员详情（含体检历史 + 异常随访展开）"""

    exams: list[Any] = Field(default_factory=list, description="体检记录链（OhHealthExamResponse）")
    followups: list[Any] = Field(default_factory=list, description="异常随访（OhFollowupResponse）")


class OhPersonStats(BaseModel):
    """人员台账统计"""

    total: int = Field(0, description="总人数")
    hazard_exposed: int = Field(0, description="接触危害人数")
    by_department: dict[str, int] = Field(default_factory=dict, description="按部门分布")
    by_position: dict[str, int] = Field(default_factory=dict, description="按岗位分布")
    by_work_status: dict[str, int] = Field(default_factory=dict, description="按在岗状态分布")
    by_last_exam_conclusion: dict[str, int] = Field(default_factory=dict, description="按最后体检结论分布")
