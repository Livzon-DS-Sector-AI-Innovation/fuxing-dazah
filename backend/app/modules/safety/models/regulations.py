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
from app.modules.safety.models.enums import RegulationStatus  # noqa: F811
from app.shared.base_model import BaseModel

# 业务表均软删除（is_deleted），唯一编号约束使用部分唯一索引
# (WHERE is_deleted = false)，避免「软删→重建同编号」触发约束冲突。
# 见 CLAUDE.md「软删除隐形 bug」注意事项。


# ==================== 安全操作规程 ====================


class OperationRegulation(BaseModel):
    """安全操作规程表 - 操规文档管理主表"""

    __tablename__ = "operation_regulations"
    __table_args__ = (
        Index("uq_operation_regulations_no", "regulation_no", unique=True, postgresql_where=text("is_deleted = false")),
        {"schema": "safety"},
    )

    regulation_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="操规编号")
    regulation_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="操规名称")
    document_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="操规文档路径（当前最新版本）"
    )
    document_original_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="文档原始文件名"
    )
    position: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="岗位（达托/达巴，逗号分隔）"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    # ── 标准化生成字段 ──
    content: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="标准化 Markdown 内容（9 章完整操规）"
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=RegulationStatus.DRAFT.value,
        server_default="draft",
        nullable=False,
        comment="操规状态: draft/generated/reviewed/exported",
    )
    source_document_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="原始上传的旧版操规文件路径"
    )

    # ── AI 审核字段（生成后对照源文档审核，落库审核状态与说明）──
    ai_review_status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        server_default="pending",
        nullable=False,
        comment="AI 审核状态: pending/reviewing/completed/failed",
    )
    ai_review_note: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        comment="AI 审核说明 {summary, dimensions, chapter_fixes, reviewed_at}",
    )

    # 关系
    revisions: Mapped[list["RegulationRevision"]] = relationship(
        "RegulationRevision", back_populates="regulation", lazy="selectin"
    )


# ==================== 操规修订记录 ====================


class RegulationRevision(BaseModel):
    """修订记录表 - 修订流程记录"""

    __tablename__ = "regulation_revisions"
    __table_args__ = (
        Index("uq_regulation_revisions_no", "revision_no", unique=True, postgresql_where=text("is_deleted = false")),
        {"schema": "safety"},
    )

    revision_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="修订编号")
    regulation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("safety.operation_regulations.id"),
        nullable=False,
        comment="关联操规ID",
    )
    regulation_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="安全操规名称")
    old_document_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="旧文档路径"
    )
    reviser: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True, comment="修订人"
    )
    reviser_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="修订人姓名")
    revision_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="修订时间"
    )
    revision_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="manual", server_default="manual", comment="修订类型: manual/ai"
    )
    revision_opinion: Mapped[str | None] = mapped_column(Text, nullable=True, comment="修订意见/内容")
    revision_scope: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="修订范围（逗号分隔: process/safety_requirement）"
    )
    review_opinion: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending", nullable=False, comment="审核意见: pending/approved"
    )
    new_document_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="新文档路径"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    # 关系
    regulation: Mapped["OperationRegulation"] = relationship(
        "OperationRegulation", back_populates="revisions"
    )


