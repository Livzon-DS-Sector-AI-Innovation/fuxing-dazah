"""职称评审 ORM 模型（hr schema）——v2 投票制多级评审。

七张表：活动、职级组、评价项、申报、评委、评价明细、部门评审组。
全部无外键约束、软删除，业务唯一约束用 postgresql_where=text("is_deleted = false")
部分唯一索引，避免"重复添加→删除→再添加"触发唯一键冲突。
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel

# ─── 活动状态机 ───
ACTIVITY_DRAFT = "draft"          # 配置中
ACTIVITY_OPEN = "open"            # 申报中
ACTIVITY_REVIEWING = "reviewing"  # 评审中
ACTIVITY_CLOSED = "closed"        # 已结束

# ─── 申报流程状态机（v3：飞书审批前置，无部门初审/终审环节） ───
APPLICATION_SUBMITTED = "submitted"        # 审批通过已落库，待评审
APPLICATION_VOTING = "voting"              # 评审期投票中
APPLICATION_PASSED = "passed"              # 投票通过
APPLICATION_FAILED = "failed"              # 投票未通过
APPLICATION_FINAL_PASSED = "final_passed"  # 终审通过（v3 不再产生，保留兼容）
APPLICATION_FINAL_FAILED = "final_failed"  # 终审驳回（v3 不再产生，保留兼容）
APPLICATION_INVALID = "invalid"            # 姓名工号校验失败，待 HR 处理

# ─── 序列常量 ───
SEQUENCE_TECH = "技术职级"
SEQUENCE_SKILL = "职业技能"

# ─── 默认职级组模板（10 条；技术助理已取消，评审标准文本与终审 v3 取消） ───
DEFAULT_LEVEL_TEMPLATE: list[dict[str, Any]] = [
    {"sequence": SEQUENCE_TECH, "level_name": "技术员"},
    {"sequence": SEQUENCE_TECH, "level_name": "助理工程师"},
    {"sequence": SEQUENCE_TECH, "level_name": "工程师"},
    {"sequence": SEQUENCE_TECH, "level_name": "高级工程师"},
    {"sequence": SEQUENCE_TECH, "level_name": "专家"},
    {"sequence": SEQUENCE_SKILL, "level_name": "初级工"},
    {"sequence": SEQUENCE_SKILL, "level_name": "中级工"},
    {"sequence": SEQUENCE_SKILL, "level_name": "高级工"},
    {"sequence": SEQUENCE_SKILL, "level_name": "技师"},
    {"sequence": SEQUENCE_SKILL, "level_name": "高级技师"},
]

# ─── 固定 7 个评价项（《办法》附表5 综合评价表，名称按表10对齐） ───
DEFAULT_DIMENSION_NAMES = [
    "工作思想表现",
    "完成本职工作情况",
    "完成科技经济研究项目",
    "组织协调能力",
    "开拓创新能力",
    "撰写专利、论文、著作、总结、报告",
    "培养指导技术人员",
]

# ─── 附表5（表11）分级合格标准：按申报职级分两档 ───
# 高档：工程师/技师职级及以上；低档：助理工程师/高级工及以下（含技术员/中级工）
HIGH_TIER_LEVELS = {"工程师", "高级工程师", "专家", "技师", "高级技师"}
DIMENSION_GRADE_STANDARDS: dict[str, dict[str, str]] = {
    "high": {
        "工作思想表现": "正确贯彻、执行公司及上级领导的方针政策并能宣传、表现突出",
        "完成本职工作情况": "本职工作任务圆满完成、质量效益好",
        "完成科技经济研究项目": "参与项目、科研并获得地厅级以上有关奖项者",
        "组织协调能力": "独立组织、协调处理技术/管理项目2项以上",
        "开拓创新能力": "提出一项以上合理化建议并被采纳",
        "撰写专利、论文、著作、总结、报告": "发明专利授权1项及以上（第一、二发明人）或实用新型专利授权2项及以上或撰写论文1篇及以上（第一、二作者）并在省（初级职称者在地厅级）以上刊物发表",
        "培养指导技术人员": "培养指导低一级技术人员2名",
    },
    "low": {
        "工作思想表现": "自觉贯彻、执行各项政策",
        "完成本职工作情况": "一般",
        "完成科技经济研究项目": "参与并获单位认可",
        "组织协调能力": "组织、协调处理技术/管理项目1项以上",
        "开拓创新能力": "提出建议但未被采纳",
        "撰写专利、论文、著作、总结、报告": "申请发明专利1项及以上（第一、二发明人）但未授权或实用新型专利授权1项或有论文撰写但未发表",
        "培养指导技术人员": "1名",
    },
}

# ─── 投票相关常量 ───
VOTE_AGREE = "同意"
VOTE_OPPOSE = "不同意"
VOTE_ABSTAIN = "弃权"
GRADE_OPTIONS = ["合格", "不合格"]
DEFAULT_PASS_RATIO = 2 / 3  # 三分之二同意通过


class TitleReviewActivity(BaseModel):
    """年度评定活动（多序列多职级并行，绑定飞书申报表/投票表）。"""

    __tablename__ = "title_review_activities"
    __table_args__ = (
        Index("ix_tract_status", "status"),
        Index("ix_tract_feishu_app", "feishu_app_token"),
        {"schema": "hr"},
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="活动名称")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="draft", comment="draft/open/reviewing/closed"
    )
    apply_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="申报截止时间"
    )
    review_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="评审截止时间"
    )
    pass_ratio: Mapped[float] = mapped_column(
        Float, nullable=False, default=DEFAULT_PASS_RATIO, server_default="0.6666666666666667",
        comment="通过比例：同意÷(同意+不同意) ≥ 此值（默认三分之二）",
    )
    feishu_app_token: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="飞书多维表格 app_token（绑定现有表）"
    )
    apply_table_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="申报表 table_id"
    )
    vote_table_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="投票表 table_id"
    )
    approval_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="飞书审批定义编码（申报先过审批，通过后自动同步）"
    )


class TitleReviewLevel(BaseModel):
    """职级组（活动子表）：序列×职级（v3 评审标准文本与终审已取消）。"""

    __tablename__ = "title_review_levels"
    __table_args__ = (
        Index("ix_tlvl_activity", "activity_id"),
        Index(
            "uq_tlvl_activity_level", "activity_id", "sequence", "level_name", unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "hr"},
    )

    activity_id: Mapped[UUID] = mapped_column(nullable=False, comment="所属活动")
    sequence: Mapped[str] = mapped_column(String(32), nullable=False, comment="序列：技术职级/职业技能")
    level_name: Mapped[str] = mapped_column(String(32), nullable=False, comment="职级名")
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="排序"
    )


class TitleReviewDimension(BaseModel):
    """评价项（活动子表，固定 7 项，对应投票表评价列）。"""

    __tablename__ = "title_review_dimensions"
    __table_args__ = (
        Index("ix_tdim_activity", "activity_id"),
        Index(
            "uq_tdim_activity_field", "activity_id", "feishu_field_name", unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "hr"},
    )

    activity_id: Mapped[UUID] = mapped_column(nullable=False, comment="所属活动")
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="评价项名称")
    feishu_field_name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="投票表列名"
    )
    feishu_field_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="投票表 field_id（事件映射用，绑定后回写）"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="排序"
    )


class TitleReviewApplication(BaseModel):
    """申报记录（飞书申报表行镜像 + 流程状态 + 票数）。"""

    __tablename__ = "title_review_applications"
    __table_args__ = (
        Index("ix_tapp_activity_status", "activity_id", "status"),
        Index(
            "uq_tapp_activity_employee", "activity_id", "employee_id", unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "uq_tapp_activity_record", "activity_id", "feishu_record_id", unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "uq_tapp_approval_instance", "approval_instance_code", unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "hr"},
    )

    activity_id: Mapped[UUID] = mapped_column(nullable=False, comment="所属活动")
    employee_id: Mapped[UUID | None] = mapped_column(nullable=True, comment="hr.employees.id")
    employee_no: Mapped[str] = mapped_column(String(32), nullable=False, comment="工号快照")
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="姓名快照")
    department: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="部门快照")
    sequence: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="申报序列")
    tech_domain: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="技术领域：研发/生产技术类、技术服务类（技术职级适用）"
    )
    apply_level: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="申报职级")
    current_level: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="现任职级")
    is_exception: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", comment="是否破格申报"
    )
    exception_reason: Mapped[str | None] = mapped_column(Text, nullable=True, comment="破格申报理由")
    tenure_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="任现职开始时间"
    )
    tenure_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="任现职结束时间"
    )
    self_evaluations: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="7 项自我评价 {维度名: 合格/不合格}"
    )
    work_statements: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="业绩陈述文本 {字段名: 文本}"
    )
    attachments: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="4 类附件元数据 {类别: [{file_token,name,size}]}"
    )
    profile: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="员工信息表自动带出的个人档案 {学历/司龄/入职日期/性别/职务/岗位职级/毕业院校/专业/目前职级/近5年年终绩效考评结果/2026年最高可申报}"
    )
    profile_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="个人档案最近刷新时间（对账时超过 6 小时自动重拉）"
    )
    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="申报表记录 id"
    )
    approval_instance_code: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="飞书审批实例编码，重复提交时逗号累积（审批先行模式，防重复同步）"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="submitted",
        comment="submitted/dept_rejected/voting/passed/failed/final_passed/final_failed/invalid",
    )
    agree_votes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="同意票数"
    )
    oppose_votes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="不同意票数"
    )
    abstain_votes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="弃权票数"
    )
    final_result: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="判定结果 passed/failed"
    )
    final_opinion: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="附件4评审综合意见（终审意见）"
    )
    result_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="结果已通知申报人时间"
    )


class TitleReviewJudge(BaseModel):
    """评委（申报人 × 评委），对应飞书投票表一行，投票表侧用匿名编号。"""

    __tablename__ = "title_review_judges"
    __table_args__ = (
        Index("ix_tjud_application", "application_id"),
        Index("ix_tjud_activity", "activity_id"),
        Index(
            "uq_tjud_app_judge", "application_id", "judge_employee_id", unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "hr"},
    )

    activity_id: Mapped[UUID] = mapped_column(nullable=False, comment="所属活动")
    application_id: Mapped[UUID] = mapped_column(nullable=False, comment="所属申报")
    judge_employee_id: Mapped[UUID] = mapped_column(nullable=False, comment="hr.employees.id")
    judge_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="评委姓名（仅内网）")
    judge_employee_no: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="评委工号（仅内网）"
    )
    judge_code: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="评审人编号（匿名，写入投票表）"
    )
    judge_role: Mapped[str] = mapped_column(
        String(32), nullable=True, comment="评审人角色：评委/部门经理/人力资源"
    )
    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="投票表行 id（批量写行后回写）"
    )
    vote_result: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="投票结果：同意/不同意/弃权"
    )
    comprehensive_grade: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="综合等级：合格/不合格（附表5：≥5项合格=合格，>2项不合格=不合格）"
    )
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True, comment="评审意见")
    voted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="投票时间"
    )


class TitleReviewScore(BaseModel):
    """评价明细（评委 × 申报人 × 评价项），存等级快照防历史漂移。"""

    __tablename__ = "title_review_scores"
    __table_args__ = (
        Index("ix_tscore_judge", "judge_id"),
        Index(
            "uq_tscore_judge_dim", "judge_id", "dimension_id", unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "hr"},
    )

    activity_id: Mapped[UUID] = mapped_column(nullable=False, comment="所属活动")
    application_id: Mapped[UUID] = mapped_column(nullable=False, comment="所属申报")
    judge_id: Mapped[UUID] = mapped_column(nullable=False, comment="关联 title_review_judges.id")
    dimension_id: Mapped[UUID] = mapped_column(nullable=False, comment="关联评价项")
    dimension_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="评价项名快照")
    grade: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="评价等级：合格/不合格"
    )
    voted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="评价时间"
    )


class TitleReviewDeptCommittee(BaseModel):
    """部门评审组：部门初审人（负责人）、终审人（分管领导）、默认评委（评定小组）。"""

    __tablename__ = "title_review_dept_committees"
    __table_args__ = (
        Index(
            "uq_tdc_department", "department", unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "hr"},
    )

    department: Mapped[str] = mapped_column(String(64), nullable=False, comment="部门名称")
    manager_employee_id: Mapped[UUID | None] = mapped_column(
        nullable=True, comment="部门负责人（初审人） hr.employees.id"
    )
    manager_name: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="负责人姓名")
    leader_employee_id: Mapped[UUID | None] = mapped_column(
        nullable=True, comment="分管领导（终审人） hr.employees.id"
    )
    leader_name: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="分管领导姓名")
    committee_members: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True, comment="职级评定小组成员 [{employee_id,name,employee_no}]"
    )
