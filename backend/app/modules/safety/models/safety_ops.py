"""Safety ORM models — 事故/安全检查/每日风险作业报备/职业危害因素监测。"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

# 枚举集中定义在 models/enums.py（保持单一定义点）
from app.modules.safety.models.enums import *  # noqa: F401,F403
from app.shared.base_model import BaseModel

if TYPE_CHECKING:
    # 关系目标模型经字符串注解/registry 解析（模型间互引，运行时不可显式导入）；
    # 显式导入仅为类型检查可解析（消除 F405 星号导入歧义）
    from app.modules.safety.models.hazard_identifications import HazardIdentification
    from app.modules.safety.models.hazard_reports import HazardReport

# 业务表均软删除（is_deleted），唯一编号约束使用部分唯一索引
# (WHERE is_deleted = false)，避免「软删→重建同编号」触发约束冲突。
# 见 CLAUDE.md「软删除隐形 bug」注意事项。


# ==================== 事故管理 ====================


class Accident(BaseModel):
    """事故登记表"""

    __tablename__ = "accidents"
    __table_args__ = (
        Index("uq_accidents_accident_no", "accident_no", unique=True, postgresql_where=text("is_deleted = false")),
        {"schema": "safety"},
    )

    accident_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="事故编号")
    accident_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="事故类型")
    accident_level: Mapped[str] = mapped_column(
        String(32), nullable=False, default="general", comment="事故等级"
    )
    happened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="发生时间"
    )
    location: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="发生地点")
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="发生部门")
    description: Mapped[str] = mapped_column(Text, nullable=False, comment="事故描述")
    casualties: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="伤亡情况汇总")
    property_damage: Mapped[float | None] = mapped_column(Float, nullable=True, comment="财产损失(元)")
    loss_work_days: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="损失工作日")
    # ── 伤员详情 ──
    injury_details: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="伤员详情 JSON [{\"name\",\"position\",\"injury_part\",\"severity\",\"hospital\"}]"
    )
    # ── 调查信息 ──
    investigation_team: Mapped[list | None] = mapped_column(
        JSON, nullable=True, comment="调查组 JSON [{\"name\",\"role\"}]"
    )
    investigation_method: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="调查方法: 5-Why/FTA/Event Tree/BowTie等"
    )
    investigation_findings: Mapped[str | None] = mapped_column(Text, nullable=True, comment="调查发现")
    investigation_report_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="调查报告文件路径"
    )
    direct_cause: Mapped[str | None] = mapped_column(Text, nullable=True, comment="直接原因")
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True, comment="根本原因")
    handling_measures: Mapped[str | None] = mapped_column(Text, nullable=True, comment="处理措施")
    corrective_actions: Mapped[str | None] = mapped_column(Text, nullable=True, comment="纠正预防措施")
    # ── CAPA 跟踪 ──
    corrective_action_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="CAPA截止日期"
    )
    corrective_action_responsible: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="CAPA责任人"
    )
    corrective_action_status: Mapped[str | None] = mapped_column(
        String(32), default="pending", nullable=True, comment="CAPA状态: pending/in_progress/completed/verified"
    )
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True, comment="CAPA验证人"
    )
    verified_by_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="验证人姓名")
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="验证时间"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="reported", server_default="reported", nullable=False,
        comment="状态: reported/investigating/investigated/capa_in_progress/closed"
    )
    reported_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True, comment="报告人"
    )
    reported_by_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="报告人姓名")
    reported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="报告时间"
    )
    investigator: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True, comment="调查人"
    )
    investigator_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="调查人姓名")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


# ==================== 安全检查 ====================


class SafetyCheck(BaseModel):
    """安全检查表"""

    __tablename__ = "safety_checks"
    __table_args__ = (
        Index("uq_safety_checks_check_no", "check_no", unique=True, postgresql_where=text("is_deleted = false")),
        {"schema": "safety"},
    )

    check_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="检查编号")
    check_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="daily", server_default="daily", comment="检查类型"
    )
    check_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="检查日期"
    )
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="检查部门")
    inspector: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True, comment="检查人"
    )
    inspector_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="检查人姓名")
    location: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="检查地点")
    findings: Mapped[str | None] = mapped_column(Text, nullable=True, comment="检查发现")
    result: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="检查结果: qualified/unqualified/need_rectification"
    )
    rectification_required: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否需要整改")
    rectification_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="整改期限"
    )
    rectification_status: Mapped[str | None] = mapped_column(
        String(32), default="pending", nullable=True, comment="整改进度"
    )
    inspector_confirmed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", comment="检查人员确认"
    )
    safety_officer_confirmed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", comment="安全办确认"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="draft", server_default="draft", nullable=False, comment="状态"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    # 关系
    hazards: Mapped[list["HazardReport"]] = relationship(
        "HazardReport", back_populates="safety_check", lazy="selectin"
    )


# ==================== 每日风险作业报备 ====================


class DailyRiskReport(BaseModel):
    """每日风险作业报备表"""

    __tablename__ = "daily_risk_reports"
    __table_args__ = (
        Index("uq_daily_risk_reports_no", "report_no", unique=True, postgresql_where=text("is_deleted = false")),
        {"schema": "safety"},
    )

    report_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="报备编号")
    report_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="报备作业日期"
    )
    report_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="regular", server_default="regular",
        comment="报备类型: regular(常规作业) / non_regular(非常规作业)"
    )
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="报备部门")
    hazard_identification_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("safety.hazard_identifications.id"),
        nullable=True,
        comment="关联危险源辨识ID",
    )
    operation_description: Mapped[str] = mapped_column(
        Text, nullable=False, comment="风险作业描述"
    )
    operation_steps: Mapped[str | None] = mapped_column(Text, nullable=True, comment="作业步骤")
    hazard_factors: Mapped[str | None] = mapped_column(Text, nullable=True, comment="危险因素")
    risk_level: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="风险等级: level_1/level_2/level_3/level_4"
    )
    control_measures: Mapped[str | None] = mapped_column(Text, nullable=True, comment="控制措施")
    responsible_person: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="作业负责人"
    )
    operator_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="作业人数")
    location: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="作业地点")
    planned_start_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="计划开始时间"
    )
    planned_end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="计划结束时间"
    )
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

    # 关系
    hazard_identification: Mapped["HazardIdentification | None"] = relationship(
        "HazardIdentification", foreign_keys=[hazard_identification_id]
    )


# ==================== 职业危害因素监测 ====================


class OhHazardMonitor(BaseModel):
    """职业危害因素监测 / Occupational Hazard Factor Monitoring（基于 GBZ 159, GBZ 2.1/2.2）"""

    __tablename__ = "oh_hazard_monitors"
    __table_args__ = (
        Index("uq_oh_hazard_monitors_monitor_no", "monitor_no", unique=True, postgresql_where=text("is_deleted = false")),
        {"schema": "safety", "comment": "职业危害因素监测表"},
    )

    # ── 核心标识 ──
    monitor_no: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="监测编号"
    )

    # ── 监测点信息 ──
    workplace: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="监测场所/车间"
    )
    location: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="具体监测点位"
    )
    equipment_info: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="关联设备/岗位"
    )

    # ── 检测信息 ──
    detection_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="检测类型: regular/commissioned/evaluation/accident"
    )
    detection_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="检测日期"
    )
    detection_agency: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="检测机构"
    )

    # ── 状态 ──
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft", server_default="draft", comment="状态"
    )

    # ── 责任人 ──
    inspector_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="检测人员"
    )
    verifier_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="验证人员"
    )

    # ── JSON 子记录：检测结果数组 ──
    detection_results: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="检测结果 JSON数组 [{factor_name, factor_category, detection_value, unit, oel_limit, compliance_status, sampling_method, standard_ref}]"
    )

    # ── JSON：异常处置记录 ──
    abnormality_records: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="异常处置记录 JSON数组 [{abnormality_desc, corrective_action, responsible_person, deadline, status, completed_at, remarks}]"
    )

    # ── JSON：附件 ──
    attachments: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="附件列表 JSON数组 [{name, path}]"
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")
