"""职业健康体检 schemas — Enum 化（Pydantic v2）。

对齐 backend-design.md §1.2 OhHealthExam 列定义：
exam_type/status/ai_parse_status/ai_conclusion/ai_fitness 全量 Enum 校验。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ── 枚举 ──


class OhExamType(str, Enum):
    """体检类型（5 标准枚举）"""

    PRE_EMPLOYMENT = "pre_employment"
    PERIODIC = "periodic"
    POST_EMPLOYMENT = "post_employment"
    TRANSFER = "transfer"
    EMERGENCY = "emergency"


OH_EXAM_TYPE_OPTIONS = [
    {"value": OhExamType.PRE_EMPLOYMENT, "label": "岗前"},
    {"value": OhExamType.PERIODIC, "label": "在岗期间"},
    {"value": OhExamType.POST_EMPLOYMENT, "label": "离岗"},
    {"value": OhExamType.TRANSFER, "label": "转岗"},
    {"value": OhExamType.EMERGENCY, "label": "应急"},
]


class OhAiConclusion(str, Enum):
    """AI 结论分类（6 标准枚举）"""

    NORMAL = "normal"
    ABNORMAL_OTHER = "abnormal_other"
    CONTRAINDICATED = "contraindicated"
    SUSPECTED_OD = "suspected_od"
    OD_DIAGNOSED = "od_diagnosed"
    RE_EXAMINATION = "re_examination"


OH_AI_CONCLUSION_OPTIONS = [
    {"value": OhAiConclusion.NORMAL, "label": "未见异常", "color": "green"},
    {"value": OhAiConclusion.ABNORMAL_OTHER, "label": "其他异常", "color": "orange"},
    {"value": OhAiConclusion.CONTRAINDICATED, "label": "职业禁忌证", "color": "red"},
    {"value": OhAiConclusion.SUSPECTED_OD, "label": "疑似职业病", "color": "red"},
    {"value": OhAiConclusion.OD_DIAGNOSED, "label": "职业病确诊", "color": "red"},
    {"value": OhAiConclusion.RE_EXAMINATION, "label": "复查", "color": "blue"},
]


class OhAiParseStatus(str, Enum):
    """AI 解析状态"""

    PENDING = "pending"
    PARSING = "parsing"
    PARSED = "parsed"
    FAILED = "failed"


OH_AI_PARSE_STATUS_OPTIONS = [
    {"value": OhAiParseStatus.PENDING, "label": "待解析", "color": "default"},
    {"value": OhAiParseStatus.PARSING, "label": "解析中", "color": "processing"},
    {"value": OhAiParseStatus.PARSED, "label": "已解析", "color": "green"},
    {"value": OhAiParseStatus.FAILED, "label": "解析失败", "color": "red"},
]


class OhFitness(str, Enum):
    """AI 适配判定"""

    FIT = "fit"
    FIT_WITH_RESTRICTION = "fit_with_restriction"
    UNFIT = "unfit"


OH_FITNESS_OPTIONS = [
    {"value": OhFitness.FIT, "label": "可从事", "color": "green"},
    {"value": OhFitness.FIT_WITH_RESTRICTION, "label": "限制从事", "color": "orange"},
    {"value": OhFitness.UNFIT, "label": "不可从事", "color": "red"},
]


class OhExamStatus(str, Enum):
    """机器状态（兼容旧前端，含 pending）"""

    PENDING = "pending"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ARCHIVED = "archived"


OH_EXAM_STATUS_OPTIONS = [
    {"value": OhExamStatus.PENDING, "label": "未体检", "color": "default"},
    {"value": OhExamStatus.SCHEDULED, "label": "已安排", "color": "default"},
    {"value": OhExamStatus.IN_PROGRESS, "label": "体检中", "color": "processing"},
    {"value": OhExamStatus.COMPLETED, "label": "已完成", "color": "green"},
    {"value": OhExamStatus.ARCHIVED, "label": "已归档", "color": "default"},
]


# ── 实体 ──


class OhHealthExamBase(BaseModel):
    """职业健康体检基础字段（对齐模型全列）"""

    model_config = ConfigDict(use_enum_values=True)

    feishu_record_id: str | None = Field(None, max_length=64, description="Bitable 记录 ID")
    source: str = Field("manual", max_length=16, description="数据来源: bitable/manual")
    exam_no: str | None = Field(None, max_length=64, description="体检号")
    person_id: uuid.UUID | None = Field(None, description="关联 oh_persons.id")
    employee_name: str = Field(..., max_length=100, description="员工姓名")
    id_card_no: str | None = Field(None, max_length=32, description="身份证号")
    employee_no: str | None = Field(None, max_length=64, description="工号")
    department: str | None = Field(None, max_length=100, description="部门")
    position: str | None = Field(None, max_length=100, description="岗位")
    gender: str | None = Field(None, max_length=16, description="性别")
    age: int | None = Field(None, description="年龄")
    marital_status: str | None = Field(None, max_length=16, description="婚姻状况")
    phone: str | None = Field(None, max_length=32, description="电话")
    exam_type: OhExamType = Field(..., description="体检类型")
    exam_agency: str | None = Field(None, max_length=255, description="体检机构")
    scheduled_date: datetime | None = Field(None, description="登记时间")
    exam_date: datetime | None = Field(None, description="实际体检日期")
    report_date: datetime | None = Field(None, description="报告日期")
    hazard_factors: list[str] | None = Field(None, description="危害因素 [标准名]")
    protection_measures: str | None = Field(None, description="防护措施")
    total_work_years: float | None = Field(None, description="总工龄")
    hazard_exposure_years: float | None = Field(None, description="接害工龄")
    exam_result: str | None = Field(None, description="体检结果（AI 输入①）")
    exam_conclusion: str | None = Field(None, description="检查结论（AI 输入①）")
    treatment_advice_raw: str | None = Field(None, description="处理意见原文")
    paper_report_kept: str | None = Field(None, max_length=16, description="纸质报告留存: yes/no")
    synced_to_summary: bool | None = Field(None, description="是否已同步汇总表")
    source_table: str | None = Field(None, max_length=64, description="Bitable Source Table")
    source_record_id: str | None = Field(None, max_length=64, description="Bitable Source Record ID")
    attachments: list[dict[str, Any]] | None = Field(None, description="体检报告附件")
    attachment_paths: list[str] | None = Field(None, description="附件本地路径")
    status: OhExamStatus = Field(OhExamStatus.PENDING, description="机器状态（兼容旧前端）")
    ai_parse_status: OhAiParseStatus = Field(OhAiParseStatus.PENDING, description="AI 解析状态")
    ai_parse_error: str | None = Field(None, description="解析失败原因")
    ai_parse_result: dict[str, Any] | None = Field(None, description="OhExamReportParseOutput 全量")
    ai_interpretation: str | None = Field(None, description="AI 智能解读文本")
    ai_conclusion: OhAiConclusion | None = Field(None, description="AI 结论分类")
    ai_contraindication_factors: list[str] | None = Field(None, description="职业禁忌证涉及危害因素")
    ai_fitness: OhFitness | None = Field(None, description="AI 适配判定")
    ai_override_notes: str | None = Field(None, description="人工覆盖结论备注（留痕）")
    override_conclusion: OhAiConclusion | None = Field(None, description="人工覆盖结论（非空表示已覆盖 AI）")
    override_by: uuid.UUID | None = Field(None, description="覆盖人")
    override_at: datetime | None = Field(None, description="覆盖时间")
    notes: str | None = Field(None, description="备注")


class OhHealthExamCreate(OhHealthExamBase):
    """创建职业健康体检"""

    pass


class OhHealthExamUpdate(BaseModel):
    """更新职业健康体检（所有字段可选）"""

    model_config = ConfigDict(use_enum_values=True)

    feishu_record_id: str | None = Field(None, max_length=64)
    exam_no: str | None = Field(None, max_length=64)
    person_id: uuid.UUID | None = None
    employee_name: str | None = Field(None, max_length=100)
    id_card_no: str | None = Field(None, max_length=32)
    employee_no: str | None = Field(None, max_length=64)
    department: str | None = Field(None, max_length=100)
    position: str | None = Field(None, max_length=100)
    gender: str | None = Field(None, max_length=16)
    age: int | None = None
    marital_status: str | None = Field(None, max_length=16)
    phone: str | None = Field(None, max_length=32)
    exam_type: OhExamType | None = None
    exam_agency: str | None = Field(None, max_length=255)
    scheduled_date: datetime | None = None
    exam_date: datetime | None = None
    report_date: datetime | None = None
    hazard_factors: list[str] | None = None
    protection_measures: str | None = None
    total_work_years: float | None = None
    hazard_exposure_years: float | None = None
    exam_result: str | None = None
    exam_conclusion: str | None = None
    treatment_advice_raw: str | None = None
    paper_report_kept: str | None = Field(None, max_length=16)
    synced_to_summary: bool | None = None
    source_table: str | None = Field(None, max_length=64)
    source_record_id: str | None = Field(None, max_length=64)
    attachments: list[dict[str, Any]] | None = None
    attachment_paths: list[str] | None = None
    status: OhExamStatus | None = None
    ai_parse_status: OhAiParseStatus | None = None
    ai_parse_error: str | None = None
    ai_parse_result: dict[str, Any] | None = None
    ai_interpretation: str | None = None
    ai_conclusion: OhAiConclusion | None = None
    ai_contraindication_factors: list[str] | None = None
    ai_fitness: OhFitness | None = None
    notes: str | None = None


class OhHealthExamResponse(OhHealthExamBase):
    """职业健康体检响应"""

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class OhHealthExamDetail(OhHealthExamResponse):
    """体检详情（含异常随访展开）"""

    followups: list[Any] = Field(default_factory=list, description="异常随访列表（OhFollowupResponse）")


class OverrideConclusionRequest(BaseModel):
    """人工覆盖体检结论请求"""

    override_conclusion: OhAiConclusion = Field(..., description="人工覆盖结论")
    notes: str | None = Field(None, description="覆盖说明（留痕）")


class SetExamConclusionRequest(BaseModel):
    """设置体检结论请求（旧端点兼容；ticket 05 重构该端点后移除）"""

    conclusion: str = Field(..., description="体检结论")
    remarks: str | None = Field(None, description="备注")


class OhStats(BaseModel):
    """体检统计"""

    total: int = Field(0, description="总数")
    abnormal: int = Field(0, description="异常数（有效结论 ∈ 异常集）")
    contraindicated: int = Field(0, description="职业禁忌证数")
    pending_parse: int = Field(0, description="待解析数")
    by_category: dict[str, int] = Field(default_factory=dict, description="按体检类型分布")
