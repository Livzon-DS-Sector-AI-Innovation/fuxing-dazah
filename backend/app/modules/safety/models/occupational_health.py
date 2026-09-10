"""Safety ORM models."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

# 枚举集中定义在 models/enums.py（保持单一定义点）
from app.modules.safety.models.enums import *  # noqa: F401,F403
from app.shared.base_model import BaseModel

# 业务表均软删除（is_deleted），唯一编号约束使用部分唯一索引
# (WHERE is_deleted = false)，避免「软删→重建同编号」触发约束冲突。
# 见 CLAUDE.md「软删除隐形 bug」注意事项。


# ==================== 职业健康管理（OH） ====================
# 数据源：飞书多维表格 Bitable 业务表（Bitable 镜像），safety schema。
# 软删除铁律：唯一约束全部使用部分唯一索引（WHERE is_deleted = false），
# 软删时清空唯一键字段 + 置 is_deleted=true（见 CLAUDE.md「软删除隐形 bug」注意事项）。
# 不建数据库级外键（CLAUDE.md 铁律），关联键以 UUID 列承载（无 FK）。


class OhPerson(BaseModel):
    """职业健康人员汇总台账（Bitable 镜像，一人一条）"""

    __tablename__ = "oh_persons"
    __table_args__ = (
        Index("uq_oh_persons_name_idcard", "name", "id_card_no",
              unique=True, postgresql_where=text("is_deleted = false AND id_card_no IS NOT NULL")),
        Index("uq_oh_persons_employee_no", "employee_no",
              unique=True, postgresql_where=text("is_deleted = false AND employee_no IS NOT NULL")),
        Index("ix_oh_persons_feishu", "feishu_record_id"),
        Index("ix_oh_persons_dept", "department"),
        {"schema": "safety", "comment": "职业健康人员汇总台账（Bitable 镜像）"},
    )

    # ── 同步标识 ──
    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Bitable 记录 ID（同步主键）"
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="bitable", server_default="bitable",
        comment="数据来源: bitable/manual"
    )

    # ── 人员信息 ──
    name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="员工姓名"
    )
    id_card_no: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="身份证号（关联键，98% 覆盖）"
    )
    employee_no: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="工号（业务键，43% 缺失）"
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="关联 identity.users.id（无 FK，可空）"
    )
    open_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="飞书 open_id（Bitable 人员字段解析）"
    )
    department: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="部门"
    )
    position: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="岗位"
    )
    gender: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="性别"
    )
    age: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="年龄（Bitable 公式同步）"
    )
    marital_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="婚姻状况"
    )
    phone: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="电话"
    )
    total_work_years: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="总工龄（年.月折算）"
    )
    hazard_exposure_years: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="接害工龄（年.月折算）"
    )

    # ── 危害因素与体检状态（平台回填）──
    hazard_factors: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="接触危害因素 [标准名]（按岗位从 oh_positions 同步）"
    )
    last_exam_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最后体检时间（平台回填）"
    )
    last_exam_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        comment="最后体检类别: pre_employment/periodic/post_employment/transfer/emergency"
    )
    last_exam_conclusion: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="最后体检结论（ai_conclusion 归一）"
    )
    last_exam_summary: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="最后体检摘要（AI summary_text）"
    )
    exam_record_ids: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="体检记录 ID 数组（对应 Bitable link 关联）"
    )
    safety_officer: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="部门安全员（与申请表对齐）"
    )
    work_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True,
        comment="在岗状态: on_post/off_post/pre_employment/transfer（原「最后体检状态」更名）"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class OhHealthExam(BaseModel):
    """职业健康体检记录（Bitable 镜像 + AI 解析字段）"""

    __tablename__ = "oh_health_exams"
    __table_args__ = (
        Index("uq_oh_health_exams_exam_no", "exam_no",
              unique=True, postgresql_where=text("is_deleted = false AND exam_no IS NOT NULL")),
        Index("uq_oh_health_exams_feishu", "feishu_record_id",
              unique=True, postgresql_where=text("is_deleted = false AND feishu_record_id IS NOT NULL")),
        Index("uq_oh_exams_source", "source_table", "source_record_id",
              unique=True,
              postgresql_where=text(
                  "is_deleted = false AND source_table IS NOT NULL AND source_record_id IS NOT NULL"
              )),
        Index("ix_oh_health_exams_person", "person_id"),
        Index("ix_oh_health_exams_status", "status"),
        Index("ix_oh_health_exams_exam_type", "exam_type"),
        {"schema": "safety", "comment": "职业健康体检记录（Bitable 镜像 + AI 解析字段）"},
    )

    # ── 同步标识 ──
    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Bitable 记录 ID"
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="bitable", server_default="bitable",
        comment="数据来源: bitable/manual"
    )
    exam_no: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="体检号（Bitable 自动编号字段）"
    )

    # ── 人员信息（冗余，便于查询）──
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="关联 oh_persons.id（无 FK）"
    )
    employee_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="员工姓名（冗余，便于查询）"
    )
    id_card_no: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="身份证号（关联键冗余）"
    )
    employee_no: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="工号（冗余）"
    )
    department: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="部门"
    )
    position: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="岗位（原 Bitable「工种」更名）"
    )
    gender: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="性别"
    )
    age: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="年龄（公式）"
    )
    marital_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="婚姻状况"
    )
    phone: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="电话"
    )

    # ── 体检信息 ──
    exam_type: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="体检类型: pre_employment/periodic/post_employment/transfer/emergency"
    )
    exam_agency: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="体检机构"
    )
    scheduled_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="登记时间（Bitable「登记时间」）"
    )
    exam_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="实际体检日期"
    )
    report_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="报告日期"
    )

    # ── 危害因素与工龄 ──
    hazard_factors: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="危害因素 [标准名]（多选）"
    )
    protection_measures: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="防护措施（Bitable 公式）"
    )
    total_work_years: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="总工龄"
    )
    hazard_exposure_years: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="接害工龄"
    )

    # ── 体检结果（AI 输入①）──
    exam_result: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="体检结果（大段文本，AI 输入①）"
    )
    exam_conclusion: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="检查结论（大段文本，AI 输入①）"
    )
    treatment_advice_raw: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="处理意见原文（AI 输入①）"
    )
    paper_report_kept: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="纸质报告留存: yes/no"
    )
    synced_to_summary: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, comment="是否已同步汇总表（平台回写 Bitable）"
    )
    source_table: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Bitable Source Table（推断 exam_type 用）"
    )
    source_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Bitable Source Record ID"
    )
    attachments: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="体检报告附件 [{name,file_token,url,...}]"
    )
    attachment_paths: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="附件本地路径 [string]"
    )

    # ── 机器状态（兼容旧前端）──
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending",
        comment="机器状态（兼容旧前端）: pending/scheduled/in_progress/completed/archived"
    )

    # ── AI 解析字段（平台独占，防止平台写回触发重新解析）──
    ai_parse_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending",
        comment="AI 解析状态: pending/parsing/parsed/failed"
    )
    ai_parse_error: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="解析失败原因"
    )
    ai_parse_result: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="OhExamReportParseOutput 全量（abnormal_indicators/conclusion_category/...）"
    )
    ai_interpretation: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="AI智能解读文本（回写 Bitable）"
    )
    ai_conclusion: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        comment="AI 结论分类: normal/abnormal_other/contraindicated/suspected_od/od_diagnosed/re_examination"
    )
    ai_contraindication_factors: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="AI 职业禁忌证涉及危害因素 [标准名]"
    )
    ai_fitness: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="AI 适配: fit/fit_with_restriction/unfit"
    )

    # ── 人工覆盖结论（留痕）──
    ai_override_notes: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="人工覆盖结论备注（留痕）"
    )
    override_conclusion: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="人工覆盖结论（非空表示已覆盖 AI）"
    )
    override_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="覆盖人 identity.users.id"
    )
    override_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="覆盖时间"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class OhPosition(BaseModel):
    """岗位危害因素台账（Bitable 镜像）"""

    __tablename__ = "oh_positions"
    __table_args__ = (
        Index("uq_oh_positions_dept_pos", "department", "position",
              unique=True, postgresql_where=text("is_deleted = false")),
        Index("ix_oh_positions_feishu", "feishu_record_id"),
        {"schema": "safety", "comment": "岗位危害因素台账（Bitable 镜像）"},
    )

    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Bitable 记录 ID"
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="bitable", server_default="bitable",
        comment="数据来源: bitable/manual"
    )
    department: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="部门"
    )
    position: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="岗位"
    )
    job_title: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="职务"
    )
    hazard_factors: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="危害因素 [标准名]（多选 43 项）"
    )
    hazard_factors_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="filled/empty/inferred（二期 AI 推断用）"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class OhHazardFactor(BaseModel):
    """危害因素 PPE 映射字典（Bitable 镜像）"""

    __tablename__ = "oh_hazard_factors"
    __table_args__ = (
        Index("uq_oh_hazard_factors_name", "factor_name",
              unique=True, postgresql_where=text("is_deleted = false")),
        Index("ix_oh_hazard_factors_feishu", "feishu_record_id"),
        {"schema": "safety", "comment": "危害因素 PPE 映射字典（Bitable 镜像）"},
    )

    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Bitable 记录 ID"
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="bitable", server_default="bitable",
        comment="数据来源: bitable/manual"
    )
    factor_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="危害因素标准名（43 项之一）"
    )
    ppe_respiratory: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="呼吸防护用品（半面罩/全面罩两档）"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class OhExamApplication(BaseModel):
    """职业健康体检申请（转岗/离岗审批流入口）"""

    __tablename__ = "oh_exam_applications"
    __table_args__ = (
        Index("uq_oh_exam_applications_no", "application_no",
              unique=True, postgresql_where=text("is_deleted = false AND application_no IS NOT NULL")),
        Index("uq_oh_exam_applications_feishu", "feishu_record_id",
              unique=True, postgresql_where=text("is_deleted = false AND feishu_record_id IS NOT NULL")),
        Index("ix_oh_exam_applications_status", "apply_status"),
        {"schema": "safety", "comment": "职业健康体检申请（转岗/离岗审批流入口）"},
    )

    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Bitable 记录 ID"
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="bitable", server_default="bitable",
        comment="数据来源: bitable/manual"
    )
    application_no: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="申请编号（文本/URL）"
    )
    apply_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True,
        comment="申请状态: 已通过/审批中/已拒绝/已取消/已终止/已撤回/已删除"
    )
    approval_flow: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="审批流程名称"
    )
    approval_node: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="当前审批节点"
    )
    current_handler: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="当前处理人"
    )
    initiator_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="发起人姓名"
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="发起时间"
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="完成时间"
    )
    transfer_type: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="transfer/post_employment（转岗/离岗）"
    )
    exam_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="体检类型: 离岗体检/转岗体检"
    )
    employee_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="员工姓名"
    )
    id_card_no: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="身份证号"
    )
    department: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="原部门"
    )
    position: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="原岗位"
    )
    new_department: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="转入部门"
    )
    new_position: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="转入岗位"
    )
    transfer_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="转岗日期"
    )
    leave_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="离岗日期"
    )
    dept_safety_officer: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="部门安全员"
    )
    applicant_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="申请人"
    )
    apply_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="申请日期"
    )

    # ── AI 差异分析（工作流②）──
    diff_analyze_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="none", server_default="none",
        comment="差异分析状态: none/parsing/analyzed/failed"
    )
    diff_analyze_error: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="差异分析失败原因"
    )
    diff_analyze_result: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="OhTransferDiffOutput 全量"
    )
    diff_summary: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="差异分析摘要（回写 Bitable「差异分析结论」）"
    )
    needs_exam: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, comment="是否需体检（AI 输出）"
    )
    exam_suggestion: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="建议体检类型: pre_employment/periodic/transfer"
    )
    created_exam_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="自动创建的体检登记 oh_health_exams.id（联动）"
    )
    bt_extra: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="Bitable 脏字段（备案残留等，镜像忽略主字段后兜底）"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class OhFollowup(BaseModel):
    """职业健康异常随访（平台侧新增，闭环管理）"""

    __tablename__ = "oh_followups"
    __table_args__ = (
        Index("uq_oh_followups_exam_indicator", "exam_id", "indicator_name",
              unique=True, postgresql_where=text("is_deleted = false AND exam_id IS NOT NULL")),
        Index("ix_oh_followups_person", "person_id"),
        Index("ix_oh_followups_status", "status"),
        Index("ix_oh_followups_due", "followup_date"),
        {"schema": "safety", "comment": "职业健康异常随访（平台侧新增，闭环管理）"},
    )

    exam_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="关联 oh_health_exams.id（无 FK）"
    )
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="关联 oh_persons.id（无 FK）"
    )
    person_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="人员姓名（冗余）"
    )
    indicator_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="异常指标名"
    )
    indicator_value: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="指标值（保留原文+单位）"
    )
    reference_range: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="参考范围"
    )
    abnormal_level: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="异常程度: mild/moderate/severe"
    )
    category: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="指标类别: lab/vision/hearing/physique/other"
    )
    followup_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        comment="随访类型: re_examination/specialist_referral/transfer_post/health_monitor"
    )
    followup_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="建议复查/处置日期（到期派生）"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open", server_default="open",
        comment="随访状态: open/followed/closed/expired"
    )
    action_taken: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="处置记录"
    )
    responsible: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="责任人"
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="关闭时间"
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ai", server_default="ai", comment="来源: ai/manual"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


