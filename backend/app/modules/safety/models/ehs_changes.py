"""Safety ORM models."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
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
from app.platform.identity.models import User
from app.shared.base_model import BaseModel

# 业务表均软删除（is_deleted），唯一编号约束使用部分唯一索引
# (WHERE is_deleted = false)，避免「软删→重建同编号」触发约束冲突。
# 见 CLAUDE.md「软删除隐形 bug」注意事项。


# ==================== EHS变更管理 (MOC) ====================


class EhsChange(BaseModel):
    """EHS变更管理 / Management of Change（基于 T/CCSAS 007-2020）"""

    __tablename__ = "ehs_changes"
    __table_args__ = (
        Index("uq_ehs_changes_change_no", "change_no", unique=True, postgresql_where=text("is_deleted = false")),
        Index("uq_ehs_changes_feishu_record_id", "feishu_record_id", unique=True, postgresql_where=text("is_deleted = false AND feishu_record_id IS NOT NULL")),
        {"schema": "safety", "comment": "EHS变更管理表"},
    )

    # ── 核心标识 ──
    change_no: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="变更编号"
    )

    # ── 基础信息 ──
    title: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="变更标题"
    )
    change_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="变更类型: process_tech/equipment_facility/management（Bitable 验收表无此列可为空）"
    )
    change_grade: Mapped[str] = mapped_column(
        String(16), nullable=False, default="general", server_default="general", comment="变更等级: major/general"
    )
    change_duration: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="变更期限: permanent/temporary/emergency（Bitable 验收表无此列可为空）"
    )
    department: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="申请部门"
    )
    location_unit: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="所在单元/装置"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="变更描述（变更前/变更后对比）"
    )
    technical_basis: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="变更技术依据"
    )
    expected_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="预期开始日期"
    )
    expected_completion: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="预期完成日期"
    )
    actual_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="实际开始日期"
    )
    actual_completion: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="实际完成日期"
    )
    expected_effect: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="预期效果"
    )

    # ── 状态与申请人 ──
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft", server_default="draft", comment="状态"
    )
    applicant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True, comment="申请人ID"
    )
    applicant_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="申请人姓名"
    )

    # ── JSON 辅助字段 ──
    equipment_tags: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="关联设备位号 JSON数组"
    )
    documents_to_update: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="需更新的文件清单 JSON数组 [{name, number}]"
    )
    attachments: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="附件列表 JSON数组 [{name, path}]"
    )

    # ── JSON 子记录 ──
    risk_assessments: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="风险评估 JSON数组 [{method, severity, likelihood, risk_level, description, control_measures, assessed_by, assessed_date, participants}]"
    )
    approval_chain: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="审批链 JSON数组 [{level, approver_role, approver, decision, comments, decided_at}]"
    )
    action_items: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="行动项 JSON数组 [{task, owner, due_date, status, completed_at}]"
    )
    pssr_checklist: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="PSSR清单 JSON数组 [{item, result, checked_by, checked_at, remarks}]"
    )
    verification: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="变更验证 {expected_effect_achieved, comments, psi_updated, documents_updated, accepted_by, accepted_date}"
    )
    closure: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="变更关闭 {closed_by, closed_date, temp_expiry_date, restored_date}"
    )

    # ── 关联 ──
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    # ── Bitable 同步字段 ──
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="manual", server_default="manual",
        comment="数据来源: manual(手动)/bitable(飞书同步)",
    )
    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="飞书 Bitable 记录 ID（同步主键）"
    )
    feishu_table_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="飞书表类型: approval(变更审批)/acceptance(变更验收)"
    )
    bt_change_no: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Bitable 变更申请编号/变更编号（展示用）"
    )
    bt_change_status: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Bitable 变更状态（待安装/问题整改中等，审批表专用）"
    )
    bt_plan_content: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Bitable 变更计划内容（审批表专用）"
    )
    bt_risk_measures: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Bitable 变更风险评估及建议措施（审批表专用）"
    )
    bt_acceptance_comment: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Bitable 验收意见（验收表专用，可另附验收报告）"
    )
    bt_extra: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="Bitable 其他字段 JSONB（can_reflect/gmp_change_no/current_handler/approval_node/source_id/related_approval/approval_flow/acceptance_date）"
    )
    ai_review_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="none", server_default="none",
        comment="AI审核状态: none/completed（审批表专用）",
    )
    ai_review_result: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="AI审核结果 JSONB（审批表四维度）{reason:{conclusion,report}, plan:{...}, effect:{...}, risk:{...}, pre_review:..., regulations:[...]}"
    )
    ai_error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="AI审核失败信息（failed 时记录，completed 时清空）"
    )

    # ── 关系 ──
    applicant: Mapped["User | None"] = relationship(
        "app.platform.identity.models.User", foreign_keys=[applicant_id]
    )


