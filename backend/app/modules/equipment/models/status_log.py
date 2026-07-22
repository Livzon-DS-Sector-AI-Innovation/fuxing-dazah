"""设备状态变更日志 ORM 模型。"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class EquipmentStatusLog(BaseModel):
    """设备状态变更日志表：记录每次状态切换的时间点，用于计算时间开动率"""

    __tablename__ = "equipment_status_logs"
    __table_args__ = (
        Index(
            "ix_equipment_status_logs_eq_time",
            "equipment_id",
            "changed_at",
        ),
        {"schema": "equipment"},
    )

    equipment_id: Mapped[uuid.UUID] = mapped_column(
        comment="设备ID，逻辑引用 equipment.equipments.id"
    )
    log_type: Mapped[str] = mapped_column(
        String(10),
        default="status",
        comment="日志类型：status(设备状态)/running(运行状态)",
    )
    old_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="变更前状态；基线记录为空"
    )
    new_status: Mapped[str] = mapped_column(
        String(20),
        comment="变更后状态：status 类为 完好/备用/故障待检/维修中/报废；running 类为 开机/停机",
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), comment="变更时间"
    )
    source: Mapped[str] = mapped_column(
        String(20),
        default="manual",
        comment="来源：init(基线)/create(新建)/manual(台账编辑)/work_order(工单联动)/import(Excel导入)",
    )
