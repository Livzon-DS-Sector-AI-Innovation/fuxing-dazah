"""中间体台账 ORM —— 面向生产流程的产出物/中间体，非面向客户的产品。"""

import uuid

from sqlalchemy import CheckConstraint, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class IntermediateType(BaseModel):
    """中间体字典 —— 生产流程中的产出物/中间体（非面向客户的产品，产品见 Product 模型）。"""

    __tablename__ = "intermediate_types"
    __table_args__ = (
        Index(
            "uq_production_intermediate_types_code",
            "code",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "production"},
    )

    code: Mapped[str] = mapped_column(String(50), comment="中间体编码")
    name: Mapped[str] = mapped_column(String(200), comment="中间体名称")
    category: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="分类：发酵液/结晶粉/湿品等"
    )
    default_unit: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="默认单位"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="说明"
    )
    is_product: Mapped[bool] = mapped_column(default=False, comment="是否为成品")
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True, comment="关联的产品ID（可选）"
    )


class RouteNodeIntermediate(BaseModel):
    """节点-中间体绑定（模板层，属于路线图定义）"""

    __tablename__ = "route_node_intermediates"
    __table_args__ = (
        Index(
            "uq_production_node_intermediates",
            "node_id",
            "intermediate_type_id",
            "direction",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_production_node_intermediates_node", "node_id"),
        CheckConstraint(
            "direction IN ('output', 'input')",
            name="ck_production_node_intermediates_direction",
        ),
        {"schema": "production"},
    )

    node_id: Mapped[uuid.UUID] = mapped_column(comment="所属节点")
    intermediate_type_id: Mapped[uuid.UUID] = mapped_column(comment="中间体类型")
    direction: Mapped[str] = mapped_column(
        String(10), comment="产出(output) / 消耗(input)"
    )
    unit_override: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="覆盖默认单位"
    )
    required: Mapped[bool] = mapped_column(default=False, comment="是否必填")
    sort_order: Mapped[int] = mapped_column(default=0, comment="排序")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class BatchIntermediateOutput(BaseModel):
    """中间体产出记录（实例层，工序完成时写入）"""

    __tablename__ = "batch_intermediate_outputs"
    __table_args__ = (
        Index("ix_production_outputs_batch", "batch_id"),
        Index("ix_production_outputs_execution", "execution_id"),
        {"schema": "production"},
    )

    batch_id: Mapped[uuid.UUID] = mapped_column(comment="所属批次")
    execution_id: Mapped[uuid.UUID] = mapped_column(comment="产出所属执行")
    node_id: Mapped[uuid.UUID] = mapped_column(comment="产出节点")
    intermediate_type_id: Mapped[uuid.UUID] = mapped_column(comment="中间体类型")
    intermediate_batch_no: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="中间体批号，为空则默认用批次号"
    )
    quantity: Mapped[float] = mapped_column(comment="数量")
    unit: Mapped[str] = mapped_column(String(20), comment="单位")
    is_product: Mapped[bool] = mapped_column(default=False, comment="是否成品产出")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class BatchIntermediateConsumption(BaseModel):
    """中间体消耗记录（实例层，工序开始时写入，output_id 溯源）"""

    __tablename__ = "batch_intermediate_consumptions"
    __table_args__ = (
        Index("ix_production_consumptions_batch", "batch_id"),
        Index("ix_production_consumptions_execution", "execution_id"),
        Index("ix_production_consumptions_output", "output_id"),
        {"schema": "production"},
    )

    batch_id: Mapped[uuid.UUID] = mapped_column(comment="所属批次")
    execution_id: Mapped[uuid.UUID] = mapped_column(comment="消耗所属执行")
    node_id: Mapped[uuid.UUID] = mapped_column(comment="消耗节点")
    intermediate_type_id: Mapped[uuid.UUID] = mapped_column(comment="中间体类型")
    output_id: Mapped[uuid.UUID] = mapped_column(comment="引用的产出记录，溯源关键字段")
    quantity: Mapped[float] = mapped_column(comment="消耗数量")
    unit: Mapped[str] = mapped_column(String(20), comment="单位")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")
