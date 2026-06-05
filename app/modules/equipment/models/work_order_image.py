"""Work order image ORM model."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class WorkOrderImage(BaseModel):
    """工单图片表"""

    __tablename__ = "work_order_images"
    __table_args__ = {"schema": "equipment"}

    work_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment.work_orders.id"),
        comment="工单ID",
    )
    file_name: Mapped[str] = mapped_column(String(255), comment="原始文件名")
    file_path: Mapped[str] = mapped_column(String(500), comment="服务器文件路径")
    file_size: Mapped[int | None] = mapped_column(comment="文件大小（字节）")
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="上传时间",
    )
