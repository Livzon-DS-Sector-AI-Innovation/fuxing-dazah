"""Safety ORM models."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
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


# ==================== 隐患排查 ====================


class HazardReport(BaseModel):
    """隐患报告表"""

    __tablename__ = "hazard_reports"
    __table_args__ = (
        Index("uq_hazard_reports_hazard_no", "hazard_no", unique=True, postgresql_where=text("is_deleted = false")),
        Index(
            "uq_hazard_reports_feishu_record_id",
            "feishu_record_id",
            unique=True,
            postgresql_where=text("is_deleted = false AND feishu_record_id IS NOT NULL"),
        ),
        {"schema": "safety"},
    )

    hazard_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="隐患编号")
    inspection_category: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="检查类别（Bitable 多选，逗号分隔，如「月度安全检查, 周检」）"
    )
    hazard_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="隐患分类（AI）：人的不安全行为/物的不安全状态/环境的不安全因素/管理的缺陷"
    )
    hazard_level: Mapped[str] = mapped_column(
        String(16), nullable=False, default="general", comment="隐患等级（AI）：一般隐患/较大隐患/重大隐患"
    )
    hazard_level_manual: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="隐患等级（人工）：一般隐患/较大隐患/重大隐患（Bitable 隐患级别字段同步，督办判定以此为准）"
    )
    hazard_category: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="隐患类别（AI）：设备设施/危化储存/仪表+电气/…（13种）"
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, comment="隐患描述")
    discovered_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True, comment="发现人"
    )
    discovered_by_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="检查人员姓名")
    inspector_department: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="检查人员部门（Bitable 多选，逗号分隔，如「EHS部, 生产部」）"
    )
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=None, nullable=False, comment="检查日期"
    )
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="责任部门")
    major_hazard_basis: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="隐患判定依据（AI）"
    )
    key_defect: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="隐患描述（AI）"
    )
    defect_substance: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        comment="缺陷实质评估: substantive / procedural / uncertain"
    )
    defect_substance_reasoning: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="缺陷实质评估理由"
    )
    defect_photos: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="缺陷图片JSON数组"
    )
    rectification_responsible_person: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True, comment="整改责任人（FK → identity.users）"
    )
    rectification_responsible_person_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="整改责任人姓名（Bitable「责任人」）"
    )
    corrective_preventive_measures: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="AI整改建议"
    )
    rectification_reply: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="整改回复内容"
    )
    deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="整改期限"
    )
    actual_completion_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="整改完成时间"
    )
    rectification_photos: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="整改后图片JSON数组"
    )
    rectification_status: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending", nullable=False, comment="整改进度"
    )
    # ── 三级复核 ──
    verify_level_1_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", nullable=False,
        comment="部门负责人复核状态 (Bitable「部门负责人复核」): pending/approved/rejected"
    )
    verify_level_2_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", nullable=False,
        comment="分管领导复核状态 (Bitable「分管领导复核」): pending/approved/rejected/no_review_needed"
    )
    verify_level_3_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", nullable=False,
        comment="检查人员复核状态 (Bitable「检查人员复核」): pending/approved/rejected"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="open", server_default="open", nullable=False, comment="状态"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    # ── AI 流程状态 ──
    ai_node_progress: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending_input",
        server_default="pending_input",
        comment="AI流程节点进度(pending_input/pending_script1/review_script1/pending_script2/review_script2/completed)",
    )
    overall_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default="draft",
        comment="整体状态(draft/ai_processing/completed/cancelled)",
    )
    ai_error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="AI 脚本执行错误信息"
    )
    script1_review_status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        server_default="pending",
        comment="AI隐患识别审核状态(pending/approved/rejected)",
    )
    script2_review_status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        server_default="pending",
        comment="AI整改建议审核状态(pending/approved/rejected)",
    )
    ai_generated: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        comment="是否AI生成",
    )
    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="飞书多维表格记录 ID，双向同步关联"
    )

    # ── AI 整改初审 ──
    ai_review_result: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="AI 整改初审结果 JSON（RectificationReviewOutput 完整输出）"
    )
    ai_review_status: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending", nullable=False,
        comment="AI 初审状态: pending / processing / completed / failed"
    )
    ai_review_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="AI 初审完成时间"
    )

    # ── 飞书通知追踪 ──
    rectification_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="整改通知最近发送时间"
    )
    rectification_notify_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="整改通知状态: success / failed"
    )
    rectification_notify_error: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="整改通知失败原因"
    )
    review_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="复核通知最近发送时间"
    )
    review_notified_level: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="复核通知级别: 1/2/3"
    )
    review_notify_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="复核通知状态: success / failed"
    )
    review_notify_error: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="复核通知失败原因"
    )

    # ── 督办等级 ──
    supervision_level: Mapped[str | None] = mapped_column(
        String(16), nullable=True,
        comment="督办等级: 红色预警 / 一般预警 / closed(已关闭)"
    )

    # ── 督办进展监控（「未更新进展」机制）──
    progress_note: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="目前进展（Bitable「目前进展」字段同步，责任人填写的整改进展）"
    )
    progress_note_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="目前进展最后更新时间（Bitable 同步落库时刻，进展内容变化时记录）"
    )
    supervision_progress_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True,
        comment="督办进展状态: 未更新进展 / NULL(正常)"
    )



# ==================== 安全检查 ====================


# ==================== 事故管理 ====================


