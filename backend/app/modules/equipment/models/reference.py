"""设备跨模块引用授权模型。"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class EquipmentReferenceGrant(BaseModel):
    """设备向业务模块公开最小摘要的授权记录。

    设备授权不是设备详情权限。记录保留在设备 schema 中，目标模块只通过
    ``public_api`` 读取摘要。撤销采用 ``revoked_at``，而不是删除记录，便于
    明确阻断“用户仍在自己数据范围内”时的绕过路径。
    """

    __tablename__ = "equipment_reference_grants"
    __table_args__ = (
        UniqueConstraint(
            "equipment_id",
            "target_module",
            name="uq_equipment_reference_grants_equipment_module",
        ),
        Index(
            "ix_equipment_reference_grants_module_active",
            "target_module",
            "revoked_at",
            postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "ix_equipment_reference_grants_equipment",
            "equipment_id",
        ),
        {"schema": "equipment"},
    )

    equipment_id: Mapped[uuid.UUID] = mapped_column(
        nullable=False,
        comment="设备ID，逻辑引用 equipment.equipments.id",
    )
    target_module: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="目标业务模块编码",
    )
    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="manual",
        server_default="manual",
        comment="授权来源：manual/auto_association",
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True,
        comment="授权操作人ID，逻辑引用 identity.users.id",
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="授权时间",
    )
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True,
        comment="撤销操作人ID，逻辑引用 identity.users.id",
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="撤销时间；为空表示当前授权有效",
    )
    remark: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="授权备注",
    )

    @property
    def is_active(self) -> bool:
        """当前授权是否有效（设备自身状态需由引用查询另行判断）。"""
        return not self.is_deleted and self.revoked_at is None


__all__ = ["EquipmentReferenceGrant"]
