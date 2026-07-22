"""节点执行实例层 ORM：执行 / 设备快照 / 字段值。"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class NodeExecution(BaseModel):
    """节点执行：车间每开始一次工序 = 一行。回流重做时同节点 execution_seq +1"""

    __tablename__ = "node_executions"
    __table_args__ = (
        Index(
            "uq_production_node_executions_seq",
            "batch_id",
            "node_id",
            "execution_seq",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_production_node_executions_batch", "batch_id"),
        Index("ix_production_node_executions_node", "node_id"),
        CheckConstraint(
            "status IN ('in_progress', 'completed', 'aborted')",
            name="ck_production_node_executions_status",
        ),
        {"schema": "production"},
    )

    batch_id: Mapped[uuid.UUID] = mapped_column(comment="批次")
    node_id: Mapped[uuid.UUID] = mapped_column(comment="工序节点")
    execution_seq: Mapped[int] = mapped_column(
        default=1, comment="同批次同节点第几次执行"
    )
    status: Mapped[str] = mapped_column(
        String(20), default="in_progress", comment="in_progress/completed/aborted"
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True, comment="工序负责人，逻辑引用 identity.users.id"
    )
    owner_name: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="负责人姓名快照"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), comment="开始时间"
    )
    started_by: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True, comment="开始提交人"
    )
    started_by_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="结束时间"
    )
    finished_by: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True, comment="结束提交人"
    )
    finished_by_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_deviation: Mapped[bool] = mapped_column(
        default=False, comment="流转未在路线中定义"
    )
    deviation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class NodeExecutionEquipment(BaseModel):
    """执行-设备关联（快照）。未来物料消耗关联表按同一模式复制"""

    __tablename__ = "node_execution_equipments"
    __table_args__ = (
        Index("ix_production_exec_equipments_exec", "execution_id"),
        {"schema": "production"},
    )

    execution_id: Mapped[uuid.UUID] = mapped_column(comment="所属执行")
    equipment_id: Mapped[uuid.UUID] = mapped_column(
        comment="设备，逻辑引用 equipment.equipments.id"
    )
    equipment_no: Mapped[str] = mapped_column(String(50), comment="设备编号快照")
    equipment_name: Mapped[str] = mapped_column(String(200), comment="设备名称快照")


class NodeFieldValue(BaseModel):
    """字段值（动态表单的值半边）。key/label/unit/phase 为提交时快照"""

    __tablename__ = "node_field_values"
    __table_args__ = (
        Index(
            "uq_production_node_field_values",
            "execution_id",
            "field_def_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_production_node_field_values_exec", "execution_id"),
        {"schema": "production"},
    )

    execution_id: Mapped[uuid.UUID] = mapped_column(comment="所属执行")
    field_def_id: Mapped[uuid.UUID] = mapped_column(comment="对应字段定义")
    field_key: Mapped[str] = mapped_column(String(50), comment="快照")
    field_label: Mapped[str] = mapped_column(String(100), comment="快照")
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="快照")
    phase: Mapped[str] = mapped_column(String(10), comment="快照 start/end")
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_numeric: Mapped[float | None] = mapped_column(nullable=True)
    value_bool: Mapped[bool | None] = mapped_column(nullable=True)
    is_abnormal: Mapped[bool] = mapped_column(
        default=False, comment="numeric 超出 min/max 自动判定"
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
