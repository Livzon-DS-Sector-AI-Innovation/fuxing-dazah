"""系统反馈 ORM 模型。

反馈是平台级能力（与 audit/identity 同级），使用独立 ``feedback`` schema。
提交人姓名/部门冗余快照，避免用户改名/调岗后历史反馈失真；
处理人 ``handled_by`` 为逻辑引用（遵循项目「不加外键约束」的表设计约定）。
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class FeedbackType(enum.StrEnum):
    """反馈类型：缺陷 / 优化体验 / 新增功能。"""

    BUG = "bug"
    UX = "ux"
    FEATURE = "feature"


def _enum_sql_list(values: type[enum.StrEnum]) -> str:
    return ", ".join(f"'{member.value}'" for member in values)


class Feedback(BaseModel):
    """一条用户反馈；``created_by`` 即提交人，``is_handled`` 为管理员的「已处理」开关。"""

    __tablename__ = "feedbacks"
    __table_args__ = (
        CheckConstraint(
            f"type IN ({_enum_sql_list(FeedbackType)})",
            name="ck_feedback_feedbacks_type",
        ),
        Index("ix_feedback_feedbacks_created_at", "created_at"),
        Index("ix_feedback_feedbacks_created_by", "created_by"),
        Index("ix_feedback_feedbacks_handled_created", "is_handled", "created_at"),
        {"schema": "feedback"},
    )

    type: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    submitter_name: Mapped[str] = mapped_column(String(100), nullable=False)
    submitter_department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_handled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    handled_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    handled_by_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def submitter_id(self) -> uuid.UUID | None:
        """提交人用户 ID（created_by 的 API 视图别名）。"""
        return self.created_by


class FeedbackAttachment(BaseModel):
    """反馈截图：文件本体在对象存储（MinIO 或本地回退目录），这里只存元数据与校验和。"""

    __tablename__ = "feedback_attachments"
    __table_args__ = (
        Index("ix_feedback_attachments_feedback", "feedback_id"),
        {"schema": "feedback"},
    )

    feedback_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
