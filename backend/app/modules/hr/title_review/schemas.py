"""职称评审 API 契约（v2 投票制多级评审）。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ─── 活动与职级组 ───

class TitleReviewLevelIn(BaseModel):
    sequence: str = Field(..., max_length=32, description="序列：技术职级/职业技能")
    level_name: str = Field(..., max_length=32, description="职级名")


class TitleReviewActivityCreate(BaseModel):
    name: str = Field(..., max_length=128, description="活动名称，如：2026年度技术职级评定")
    apply_deadline: datetime | None = Field(None, description="申报截止时间")
    review_deadline: datetime | None = Field(None, description="评审截止时间")
    pass_ratio: float = Field(2 / 3, gt=0, le=1, description="通过比例（默认三分之二）")
    feishu_app_token: str | None = Field(None, max_length=64, description="绑定飞书多维表格 app_token")
    apply_table_id: str | None = Field(None, max_length=64, description="申报表 table_id")
    vote_table_id: str | None = Field(None, max_length=64, description="投票表 table_id")
    approval_code: str | None = Field(None, max_length=64, description="飞书审批定义编码（审批先行模式）")
    levels: list[TitleReviewLevelIn] | None = Field(None, description="职级组（缺省用 10 条默认模板）")


class TitleReviewActivityUpdate(BaseModel):
    name: str | None = Field(None, max_length=128)
    apply_deadline: datetime | None = Field(None, description="申报截止时间（传 null 清空）")
    review_deadline: datetime | None = Field(None, description="评审截止时间（传 null 清空）")
    pass_ratio: float | None = Field(None, gt=0, le=1)
    feishu_app_token: str | None = Field(None, max_length=64)
    apply_table_id: str | None = Field(None, max_length=64)
    vote_table_id: str | None = Field(None, max_length=64)
    approval_code: str | None = Field(None, max_length=64, description="飞书审批定义编码")
    levels: list[TitleReviewLevelIn] | None = Field(None, description="职级组全量替换（仅 draft）")


class TitleReviewLevelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    activity_id: UUID
    sequence: str
    level_name: str
    sort_order: int


class TitleReviewDimensionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    activity_id: UUID
    name: str
    feishu_field_name: str
    feishu_field_id: str | None
    sort_order: int


class TitleReviewActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    status: str
    apply_deadline: datetime | None
    review_deadline: datetime | None
    pass_ratio: float
    feishu_app_token: str | None
    apply_table_id: str | None
    vote_table_id: str | None
    feishu_folder_token: str | None
    approval_code: str | None
    created_at: datetime | None = None
    levels: list[TitleReviewLevelOut] = []


class TitleReviewActivityListOut(TitleReviewActivityOut):
    application_count: int = 0
    voted_judge_count: int = 0
    total_judge_count: int = 0


# ─── 部门评审组 ───

class TitleReviewCommitteeMemberIn(BaseModel):
    employee_id: UUID = Field(..., description="hr.employees.id")
    name: str = Field(..., max_length=64)
    employee_no: str | None = Field(None, max_length=32)


class TitleReviewDeptCommitteeIn(BaseModel):
    department: str = Field(..., max_length=64, description="部门名称")
    manager_employee_id: UUID | None = Field(None, description="部门负责人（初审人）")
    manager_name: str | None = Field(None, max_length=64)
    leader_employee_id: UUID | None = Field(None, description="分管领导（终审人）")
    leader_name: str | None = Field(None, max_length=64)
    committee_members: list[TitleReviewCommitteeMemberIn] = Field(default_factory=list)


class TitleReviewDeptCommitteeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    department: str
    manager_employee_id: UUID | None
    manager_name: str | None
    leader_employee_id: UUID | None
    leader_name: str | None
    committee_members: list[dict[str, Any]] | None


# ─── 申报 ───

class TitleReviewApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    activity_id: UUID
    employee_id: UUID | None
    employee_no: str
    name: str
    department: str | None
    sequence: str | None
    tech_domain: str | None
    apply_level: str | None
    current_level: str | None
    is_exception: bool
    exception_reason: str | None
    tenure_start: datetime | None
    tenure_end: datetime | None
    self_evaluations: dict[str, Any] | None
    work_statements: dict[str, Any] | None
    attachments: dict[str, Any] | None
    profile: dict[str, Any] | None
    feishu_record_id: str | None
    approval_instance_code: str | None
    status: str
    agree_votes: int
    oppose_votes: int
    abstain_votes: int
    final_result: str | None
    final_opinion: str | None
    result_notified_at: datetime | None
    created_at: datetime | None = None


# ─── 评委 ───

class TitleReviewJudgeAssignItemIn(BaseModel):
    employee_id: UUID = Field(..., description="hr.employees.id")
    role: str = Field("技术专家", max_length=32, description="评审人角色")


class TitleReviewJudgeAssignIn(BaseModel):
    judges: list[TitleReviewJudgeAssignItemIn] = Field(..., min_length=1)


class TitleReviewJudgeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    application_id: UUID
    judge_employee_id: UUID
    judge_name: str
    judge_employee_no: str | None
    judge_code: str
    judge_role: str | None
    feishu_record_id: str | None
    vote_result: str | None
    comprehensive_grade: str | None
    review_comment: str | None
    voted_at: datetime | None




class TitleReviewJudgeVoteIn(BaseModel):
    vote_result: str | None = Field(None, description="（废弃）投票结果由 7 维评价自动计算")
    comprehensive_grade: str | None = Field(None, description="（废弃）综合等级由 7 维评价自动计算")
    dimension_grades: dict[str, str] = Field(default_factory=dict, description="7 维评价 {维度名: 优秀/合格/不合格}")
    review_comment: str | None = Field(None, description="评审意见")


class TitleReviewJudgeTaskOut(BaseModel):
    """评委视角的投票任务（不含其他评委信息）。"""

    judge_id: UUID
    judge_code: str
    status: str
    vote_result: str | None
    comprehensive_grade: str | None
    review_comment: str | None
    voted_at: datetime | None
    dimension_grades: dict[str, str | None] = {}
    application: TitleReviewApplicationOut


# ─── 评审结果（scores:read 权限才可见） ───

class TitleReviewScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    judge_id: UUID
    dimension_id: UUID
    dimension_name: str
    grade: str | None
    voted_at: datetime | None


class TitleReviewJudgeScoreOut(TitleReviewJudgeOut):
    scores: list[TitleReviewScoreOut] = []


class TitleReviewResultRow(BaseModel):
    application: TitleReviewApplicationOut
    judges: list[TitleReviewJudgeScoreOut] = []
    vote_ratio: float | None = None  # 同意÷(同意+不同意)
    need_final_review: bool = False


# ─── 对账 ───

class TitleReviewReconcileOut(BaseModel):
    activity_id: UUID
    applications_created: int = 0
    applications_removed: int = 0
    votes_updated: int = 0
    errors: list[str] = []
