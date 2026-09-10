"""Safety ORM models."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
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


# ==================== 安全培训 ====================


class SafetyTraining(BaseModel):
    """安全培训表"""

    __tablename__ = "safety_trainings"
    __table_args__ = (
        Index("uq_safety_trainings_training_no", "training_no", unique=True, postgresql_where=text("is_deleted = false")),
        {"schema": "safety"},
    )

    training_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="培训编号")
    training_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="培训名称")
    training_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="annual", comment="培训类型"
    )
    training_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="offline", comment="培训方式"
    )
    training_level: Mapped[str] = mapped_column(
        String(32), nullable=False, default="dept", server_default="dept", comment="培训级别: company/dept/team"
    )
    trainer: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True, comment="培训讲师"
    )
    trainer_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="讲师姓名")
    training_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="培训日期"
    )
    duration_hours: Mapped[float | None] = mapped_column(Float, nullable=True, comment="培训时长(小时)")
    location: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="培训地点")
    content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="培训内容")
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="培训部门")
    exam_passing_score: Mapped[float | None] = mapped_column(
        Float, default=60, server_default="60", nullable=True, comment="及格分数线"
    )
    course_material_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="课程资料路径"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="draft", server_default="draft", nullable=False, comment="状态"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    # 关系
    records: Mapped[list["TrainingRecord"]] = relationship(
        "TrainingRecord", back_populates="training", lazy="selectin"
    )


class TrainingRecord(BaseModel):
    """培训记录（签到/考核）子表"""

    __tablename__ = "training_records"
    __table_args__ = {"schema": "safety"}

    training_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("safety.safety_trainings.id"),
        nullable=False,
        comment="培训ID",
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=True, comment="员工ID"
    )
    employee_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="员工姓名")
    department: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="部门")
    position: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="岗位")
    attendance: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否出席")
    score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="考核成绩")
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True, comment="是否合格")
    certificate_no: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="证书编号")
    certificate_expiry: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="证书有效期至"
    )
    certificate_status: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="证书状态: valid/expiring/expired"
    )
    certificate_file_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="证书文件路径"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    # 关系
    training: Mapped["SafetyTraining"] = relationship("SafetyTraining", back_populates="records")


