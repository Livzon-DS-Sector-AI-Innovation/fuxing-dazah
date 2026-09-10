"""Safety ORM models."""

import uuid
from typing import Any

from sqlalchemy import (
    JSON,
    Index,
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


# ==================== 危险源辨识 ====================


class HazardIdentification(BaseModel):
    """危险源辨识与评价表"""

    __tablename__ = "hazard_identifications"
    __table_args__ = (
        Index("uq_hazard_identifications_no", "hazard_id_no", unique=True, postgresql_where=text("is_deleted = false")),
        Index("uq_hazard_identifications_feishu_id", "feishu_record_id", unique=True, postgresql_where=text("feishu_record_id IS NOT NULL AND is_deleted = false")),
        Index("ix_hazard_identifications_regulation_batch", "regulation_id", "batch_id"),
        {"schema": "safety"},
    )

    # ── 基础信息（人工输入） ──
    hazard_id_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="危险源编号")
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="部门（Bitable 无此字段，镜像时从提交人员派生）")
    position: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="岗位")
    production_step: Mapped[str | None] = mapped_column(Text, nullable=True, comment="生产步骤")
    attachment_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="岗位资料附件路径"
    )
    attachment_original_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="附件原始文件名"
    )
    regulation_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True, comment="引用的安全操作规程 ID（替代附件上传）"
    )
    regulation_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="引用的安全操作规程名称"
    )

    # ── 多工段辨识（batch / per-stage）──
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True, comment="批次ID，同一regulation多工段同时创建时共享"
    )
    stage_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="工艺阶段名称（Chapter 7 H2 标题）"
    )
    chapter7_context: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="该工段对应的 Chapter 7 节选 Markdown（供Script 1使用）"
    )

    # ── 脚本1 输出：附件解析（AI → 人工审核） ──
    specific_activity: Mapped[str | None] = mapped_column(Text, nullable=True, comment="具体作业活动")
    equipment_facilities: Mapped[str | None] = mapped_column(Text, nullable=True, comment="设备设施")
    raw_auxiliary_materials: Mapped[str | None] = mapped_column(Text, nullable=True, comment="原辅料")
    operation_frequency: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="作业频次"
    )
    operator_count: Mapped[int | None] = mapped_column(nullable=True, comment="操作人数")

    # ── 脚本2 输出：AI危险源辨识（AI → 人工审核） ──
    hazard_type: Mapped[str | None] = mapped_column(Text, nullable=True, comment="危险类型（人机料法环）")
    possible_accident: Mapped[str | None] = mapped_column(Text, nullable=True, comment="可能导致事故")
    unsafe_behavior: Mapped[str | None] = mapped_column(Text, nullable=True, comment="不规范作业行为表现")

    # ── 脚本3 输出：固有风险 LEC（AI → 人工审核） ──
    l_inherent: Mapped[float | None] = mapped_column(nullable=True, comment="可能性L（固有）")
    e_inherent: Mapped[float | None] = mapped_column(nullable=True, comment="暴露频率E（固有）")
    c_inherent: Mapped[float | None] = mapped_column(nullable=True, comment="严重性C（固有）")
    d_inherent: Mapped[float | None] = mapped_column(nullable=True, comment="风险值D（固有）")
    inherent_risk_level: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="固有风险等级"
    )
    inherent_risk_label: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="固有风险等级中文名"
    )

    # ── 脚本3.5 输出：福建固有风险等级（脚本3 附属，不进状态机/审核） ──
    inherent_risk_level_fj: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="固有风险等级（福建）"
    )

    # ── 脚本4 输出：现有控制措施（AI → 人工审核） ──
    existing_engineering_controls: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="现有工程控制措施"
    )
    existing_management_controls: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="现有管理控制措施"
    )
    existing_ppe: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="现有个人防护措施"
    )
    existing_emergency_measures: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="现有应急措施"
    )

    # ── 脚本5 输出：残余风险（AI → 人工审核） ──
    l_residual: Mapped[float | None] = mapped_column(nullable=True, comment="可能性L（残余）")
    e_residual: Mapped[float | None] = mapped_column(nullable=True, comment="暴露频率E（残余）")
    c_residual: Mapped[float | None] = mapped_column(nullable=True, comment="严重性C（残余）")
    d_residual: Mapped[float | None] = mapped_column(nullable=True, comment="风险值D（残余）")
    residual_risk_level: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="残余风险等级"
    )
    residual_risk_label: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="残余风险等级中文名"
    )

    # ── 脚本6 输出：建议措施（AI → 人工审核） ──
    needs_recommendation: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="是否需提出建议措施（是/否/待人工确认）"
    )
    recommendation_type: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="建议措施类型"
    )
    recommendation_content: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="建议措施内容"
    )
    recommendation_priority: Mapped[str | None] = mapped_column(
        String(10), nullable=True, comment="建议措施优先级（高/中/低）"
    )

    # ── 脚本7 输出：建议措施后风险（AI → 人工审核） ──
    l_post: Mapped[float | None] = mapped_column(nullable=True, comment="可能性L（建议措施后）")
    e_post: Mapped[float | None] = mapped_column(nullable=True, comment="暴露频率E（建议措施后）")
    c_post: Mapped[float | None] = mapped_column(nullable=True, comment="严重性C（建议措施后）")
    d_post: Mapped[float | None] = mapped_column(nullable=True, comment="风险值D（建议措施后）")
    post_risk_level: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="建议措施后风险等级"
    )
    post_risk_label: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="建议措施后风险等级中文名"
    )

    # ── 管控层级（根据风险等级自动填充） ──
    control_level: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="管控层级（公司级/部门级/班组级）"
    )
    responsible_person: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="责任人"
    )

    # ── AI 流程状态 ──
    ai_node_progress: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending_input",
        server_default="pending_input",
        comment="AI流程节点进度",
    )
    ai_error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="AI 脚本执行错误信息"
    )
    overall_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default="draft",
        comment="整体状态（draft/in_progress/completed/cancelled）",
    )

    # ── 各脚本人工审核状态 ──
    script1_review_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", comment="脚本1审核状态"
    )
    script2_review_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", comment="脚本2审核状态"
    )
    script3_review_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", comment="脚本3审核状态"
    )
    script4_review_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", comment="脚本4审核状态"
    )
    script5_review_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", comment="脚本5审核状态"
    )
    script6_review_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", comment="脚本6审核状态"
    )
    script7_review_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", comment="脚本7审核状态"
    )

    # ── Bitable 镜像同步（危险源辨识自动化多维表格）──
    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="飞书 Bitable 记录 ID（同步主键）"
    )
    feishu_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="飞书 Bitable 记录 URL"
    )
    feishu_table_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="飞书 Bitable 表 ID"
    )
    submitter_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="提交人员姓名"
    )
    submitter_feishu_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="提交人员飞书 ID"
    )
    reviewer_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="审核人员姓名"
    )
    reviewer_feishu_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="审核人员飞书 ID"
    )
    # ── 脚本8：四类排查内容（AI 生成 + 人工审核 各一列）──
    engineering_check_items_ai: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="工程措施排查内容（AI）"
    )
    engineering_check_items_manual: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="工程措施排查内容（人工）"
    )
    management_check_items_ai: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="管理措施排查内容（AI）"
    )
    management_check_items_manual: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="管理措施排查内容（人工）"
    )
    ppe_check_items_ai: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="个人防护措施排查内容（AI）"
    )
    ppe_check_items_manual: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="个人防护措施排查内容（人工）"
    )
    emergency_check_items_ai: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="应急措施排查内容（AI）"
    )
    emergency_check_items_manual: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="应急措施排查内容（人工）"
    )
    bitable_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="Bitable 完整字段快照（AI/人工双份 + 公式结果）"
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


