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
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

# 枚举集中定义在 models/enums.py（保持单一定义点）
from app.modules.safety.models.enums import *  # noqa: F401,F403
from app.shared.base_model import BaseModel

# 业务表均软删除（is_deleted），唯一编号约束使用部分唯一索引
# (WHERE is_deleted = false)，避免「软删→重建同编号」触发约束冲突。
# 见 CLAUDE.md「软删除隐形 bug」注意事项。


# ==================== 特殊作业人员资质 ====================


class SpecialOperationPersonnel(BaseModel):
    """特殊作业人员资质表"""

    __tablename__ = "special_operation_personnel"
    __table_args__ = (
        Index("uq_special_op_personnel_no", "personnel_no", unique=True, postgresql_where=text("is_deleted = false")),
        {"schema": "safety"},
    )

    personnel_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="人员编号")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="姓名")
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="所属部门")
    certificate_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="证书类型（对应8种特殊作业）"
    )
    certificate_number: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="证书编号"
    )
    issuing_authority: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="发证机关"
    )
    issue_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="发证日期"
    )
    expiry_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="有效期至"
    )
    certificate_file_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="证书文件路径"
    )
    qualification_scope: Mapped[str | None] = mapped_column(Text, nullable=True, comment="资质范围")
    status: Mapped[str] = mapped_column(
        String(32), default="active", server_default="active", nullable=False,
        comment="状态: active/expired/revoked"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


# ==================== 特殊作业票 ====================


class SpecialOperationPermit(BaseModel):
    """特殊作业票表"""

    __tablename__ = "special_operation_permits"
    __table_args__ = (
        Index("uq_special_op_permits_permit_no", "permit_no", unique=True, postgresql_where=text("is_deleted = false")),
        {"schema": "safety"},
    )

    permit_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="作业票编号")
    operation_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="作业类型（8种）"
    )
    operation_level: Mapped[str] = mapped_column(
        String(16), nullable=False, default="grade2", server_default="grade2",
        comment="作业级别: special/grade1/grade2"
    )
    location: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="作业地点")
    equipment_tag: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="设备位号"
    )
    work_description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="作业内容描述")
    planned_start_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="计划开始时间"
    )
    planned_end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="计划结束时间"
    )
    actual_start_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="实际开始时间"
    )
    actual_end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="实际结束时间"
    )
    applicant_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="申请人姓名"
    )
    work_leader_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="作业负责人姓名"
    )
    operator_names: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="作业人员姓名（逗号分隔）"
    )
    guardian_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="监护人姓名"
    )
    approver_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="审批人姓名"
    )
    safety_measures: Mapped[str | None] = mapped_column(Text, nullable=True, comment="安全措施")
    emergency_equipment: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="应急消防器材"
    )
    gas_analysis: Mapped[str | None] = mapped_column(Text, nullable=True, comment="气体分析结果")
    risk_assessment: Mapped[str | None] = mapped_column(Text, nullable=True, comment="风险评估")
    safety_briefing_confirmed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", comment="安全交底确认"
    )
    safety_briefing_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="安全交底时间"
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True, comment="驳回原因")
    completion_method: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="完工方式: normal/early_termination"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="draft", server_default="draft", nullable=False, comment="状态"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


# ==================== 风险作业报备 ====================


class SpecialOperationReport(BaseModel):
    """八大特殊作业报备表"""

    __tablename__ = "special_operation_reports"
    __table_args__ = (
        Index("uq_special_operation_reports_no", "report_no", unique=True, postgresql_where=text("is_deleted = false")),
        {"schema": "safety"},
    )

    report_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="报备编号")
    permit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("safety.special_operation_permits.id"),
        nullable=True,
        comment="关联作业票ID",
    )
    operation_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="作业类型（8种）"
    )
    operation_level: Mapped[str] = mapped_column(
        String(16), nullable=False, default="grade2", server_default="grade2",
        comment="作业级别: special/grade1/grade2"
    )
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="报备部门")
    location: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="作业地点")
    equipment_tag: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="设备位号"
    )
    work_description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="作业内容描述")
    planned_start_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="计划开始时间"
    )
    planned_end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="计划结束时间"
    )
    work_leader_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="作业负责人姓名"
    )
    operator_names: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="作业人员姓名（逗号分隔）"
    )
    guardian_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="监护人姓名"
    )
    risk_level: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="风险等级: level_1/level_2/level_3/level_4"
    )
    safety_measures: Mapped[str | None] = mapped_column(Text, nullable=True, comment="安全措施")
    emergency_equipment: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="应急消防器材"
    )
    gas_analysis: Mapped[str | None] = mapped_column(Text, nullable=True, comment="气体分析结果")
    risk_assessment: Mapped[str | None] = mapped_column(Text, nullable=True, comment="风险评估描述")
    applicant_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="报备申请人姓名"
    )
    approver_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="审批人姓名"
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="审批时间"
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True, comment="驳回原因")
    status: Mapped[str] = mapped_column(
        String(32), default="draft", server_default="draft", nullable=False,
        comment="状态: draft/submitted/approved/rejected"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")
    is_critical: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
        comment="是否关键作业（AI自动判定+可手动修改）"
    )
    is_critical_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="关键作业判定理由"
    )
    is_critical_updated_by: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="手动修改关键作业标记的操作人"
    )

    # ── Bitable 同步字段 ──

    source: Mapped[str] = mapped_column(
        String(16), default="manual", server_default="manual", nullable=False,
        comment="数据来源: manual(手动)/bitable(飞书同步)"
    )
    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="飞书 Bitable 记录 ID（同步主键）"
    )
    personnel_type: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="作业人员类型: 公司人员/非公司人员/其他相关方"
    )
    work_duration_hours: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="作业时长（小时）"
    )
    has_other_operations: Mapped[str | None] = mapped_column(
        String(4), nullable=True, comment="是否涉及其他特殊作业: 是/否"
    )
    other_operation_types: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="涉及特殊作业类型列表"
    )
    is_weekend_holiday: Mapped[str | None] = mapped_column(
        String(4), nullable=True, comment="周末节假日/非上班时段: 是/否"
    )
    is_national_holiday: Mapped[str | None] = mapped_column(
        String(4), nullable=True, comment="是否国家法定节假日: 是/否"
    )
    holiday_period: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="非上班时间段/节假日"
    )
    report_type: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="报备类型: planned/unplanned"
    )
    initiator_department: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="发起人部门"
    )
    initiator_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="发起人姓名"
    )
    approver_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="作业票审批人类型"
    )
    safety_approver_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="安全工程中心审批人姓名"
    )
    approval_no: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="飞书申请编号（审批 URL）"
    )
    work_plan_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="作业计划 URL"
    )
    work_scheme_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="作业方案 URL"
    )
    approved_permit_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="已签批的特殊作业票及关联票 URL"
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="发起时间"
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="完成时间"
    )
    approval_node: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="当前审批节点"
    )

    # ── V3.5 新增字段（Bitable 同步）──

    fire_work_method: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="动火方式: 电焊/气割/氩弧焊/切割机/电钻/塑料焊/其他"
    )
    height_work_method: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="高处作业方式（多选）"
    )
    work_height: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="作业高度(米)"
    )
    lifting_weight: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="吊物质量(吨)"
    )
    contractor_name: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="施工单位"
    )

    # ── 日报分析字段 ──

    daily_risk_level: Mapped[str | None] = mapped_column(
        String(8), nullable=True, comment="日报风险等级: high/medium/low"
    )
    daily_risk_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="日报风险判定依据"
    )
    inferred_operation_types: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="AI 推断的额外特殊作业类型"
    )
    inferred_operation_detail: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="AI 类型推断说明"
    )
    is_excluded: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
        comment="是否被日报排除规则过滤"
    )
    exclusion_reason: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="日报排除原因"
    )
    daily_report_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="所属日报日期"
    )

    # 关系
    permit: Mapped["SpecialOperationPermit | None"] = relationship(
        "SpecialOperationPermit", foreign_keys=[permit_id]
    )


class KeyRiskOperationReport(BaseModel):
    """每日关键风险操作预报备表（飞书 Bitable 同步，只读）。

    数据源: 飞书多维表格「每日关键风险操作预报备（审批）」
    base: LTZ1buQJaaLMxKsNcF2c13QPnrh / 表: tblEnatX5fxfwMlI
    同步以 feishu_record_id 为主键 upsert，平台侧只读展示，不提供审批。
    """

    __tablename__ = "key_risk_operation_reports"
    __table_args__ = (
        Index(
            "uq_key_risk_operation_reports_no", "report_no",
            unique=True, postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "ix_key_risk_op_feishu_record_id", "feishu_record_id",
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "safety"},
    )

    # ── 来源与主键 ──
    report_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="申请编号文本（如 202511280372）")
    approval_no_url: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="申请编号链接")
    source: Mapped[str] = mapped_column(
        String(16), default="bitable", server_default="bitable", nullable=False,
        comment="数据来源: bitable(飞书同步)",
    )
    feishu_record_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="飞书 Bitable 记录 ID（同步主键）")

    # ── 审批字段 ──
    apply_status: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="申请状态: 已通过/审批中/已拒绝/已取消/已终止/已撤回")
    approval_node: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="审批节点")
    approval_flow: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="审批流程名称")
    current_handler: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="当前处理人")
    initiator_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="发起人姓名")
    initiator_department: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="发起人部门")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="发起时间")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="完成时间")

    # ── 作业主信息 ──
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="部门")
    area: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="区域")
    operation_content: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="作业内容")
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="作业开始时间")
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="作业结束时间")
    duration_hours: Mapped[float | None] = mapped_column(Float, nullable=True, comment="作业时长（小时）")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    # ── 安全措施（主作业）──
    personal_protection: Mapped[str | None] = mapped_column(Text, nullable=True, comment="个人防护")
    preparation_measures: Mapped[str | None] = mapped_column(Text, nullable=True, comment="准备措施")
    operation_precautions: Mapped[str | None] = mapped_column(Text, nullable=True, comment="操作注意事项")
    emergency_measures: Mapped[str | None] = mapped_column(Text, nullable=True, comment="应急措施")
    guardian: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="现场作业监护人")
    site_guardian: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="现场监护人（User）")
    dept_safety_officer: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="部门安全员（User）")

    # ── 多作业块（xxx1/xxx2 → 最多 2 条附加作业）──
    operations: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True, comment="附加作业块数组[{department,area,operation_content,personal_protection,preparation_measures,operation_precautions,emergency_measures,guardian,time_slot}]")

    # ── 三阶段现场确认 ──
    phase_before: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, comment="作业前现场确认 {date,photo_url,issue_desc}")
    phase_ongoing: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, comment="作业中现场确认 {date,photo_url,issue_desc}")
    phase_after: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, comment="作业后现场确认 {date,photo_url,issue_desc}")

    source_id: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="飞书 SourceID")


