"""工艺路线模板层 ORM：路线 / 节点 / 边 / 字段定义。"""

import uuid

from sqlalchemy import JSON, CheckConstraint, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class ProcessRoute(BaseModel):
    """工艺路线（一个产品多个版本，published 后图冻结）"""

    __tablename__ = "process_routes"
    __table_args__ = (
        Index(
            "uq_production_routes_product_version",
            "product_id",
            "version",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_production_routes_product", "product_id"),
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_production_routes_status",
        ),
        {"schema": "production"},
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        comment="产品ID，逻辑引用 production.products.id"
    )
    version: Mapped[int] = mapped_column(comment="版本号，同产品内递增")
    name: Mapped[str] = mapped_column(String(200), comment="路线名称")
    status: Mapped[str] = mapped_column(
        String(20), default="draft", comment="draft/published/archived"
    )


class RouteNode(BaseModel):
    """工序节点"""

    __tablename__ = "route_nodes"
    __table_args__ = (
        Index(
            "uq_production_route_nodes_code",
            "route_id",
            "node_code",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_production_route_nodes_route", "route_id"),
        {"schema": "production"},
    )

    route_id: Mapped[uuid.UUID] = mapped_column(comment="所属路线")
    node_code: Mapped[str] = mapped_column(String(50), comment="节点编码，路线内唯一")
    name: Mapped[str] = mapped_column(String(200), comment="工序名称")
    stage_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="工段分组标签（发酵/提炼/精制），纯展示"
    )
    node_type: Mapped[str] = mapped_column(
        String(20), default="process", comment="节点类型，现阶段恒为 process，预留扩展"
    )
    sort_order: Mapped[int] = mapped_column(default=0, comment="排序")


class RouteEdge(BaseModel):
    """流转边。批次边界（批号切换/分裂/合并）只发生在 is_batch_boundary 的边上"""

    __tablename__ = "route_edges"
    __table_args__ = (
        Index(
            "uq_production_route_edges",
            "route_id",
            "from_node_id",
            "to_node_id",
            "edge_type",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_production_route_edges_route", "route_id"),
        CheckConstraint(
            "edge_type IN ('normal', 'rework')",
            name="ck_production_route_edges_type",
        ),
        # 硬规则：回流边禁止标批次边界
        CheckConstraint(
            "NOT (edge_type = 'rework' AND is_batch_boundary)",
            name="ck_production_route_edges_rework_boundary",
        ),
        {"schema": "production"},
    )

    route_id: Mapped[uuid.UUID] = mapped_column(comment="所属路线")
    from_node_id: Mapped[uuid.UUID] = mapped_column(comment="起始节点")
    to_node_id: Mapped[uuid.UUID] = mapped_column(comment="目标节点")
    edge_type: Mapped[str] = mapped_column(
        String(20), default="normal", comment="normal/rework"
    )
    is_batch_boundary: Mapped[bool] = mapped_column(
        default=False, comment="是否批次边界"
    )
    remark: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="备注，如：不合格时"
    )
    allow_overlap: Mapped[bool] = mapped_column(
        default=False, comment="允许前道工序未完成时开始本工序（流水线模式）"
    )


class NodeFieldDef(BaseModel):
    """节点字段定义（动态表单的定义半边）"""

    __tablename__ = "node_field_defs"
    __table_args__ = (
        Index(
            "uq_production_node_field_defs",
            "node_id",
            "field_key",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_production_node_field_defs_node", "node_id"),
        CheckConstraint(
            "phase IN ('start', 'end')", name="ck_production_field_defs_phase"
        ),
        CheckConstraint(
            "data_type IN ('numeric', 'text', 'boolean', 'select')",
            name="ck_production_field_defs_data_type",
        ),
        {"schema": "production"},
    )

    node_id: Mapped[uuid.UUID] = mapped_column(comment="所属节点")
    field_key: Mapped[str] = mapped_column(String(50), comment="字段键，节点内唯一")
    field_label: Mapped[str] = mapped_column(String(100), comment="显示名")
    field_group: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="分组标签：过程检测/产出物/物料消耗（未来）"
    )
    phase: Mapped[str] = mapped_column(
        String(10), comment="start=开始工序时填 / end=结束工序时填"
    )
    data_type: Mapped[str] = mapped_column(
        String(20), comment="numeric/text/boolean/select"
    )
    options: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True, comment="select 选项列表"
    )
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="单位")
    required: Mapped[bool] = mapped_column(default=False, comment="必填")
    min_value: Mapped[float | None] = mapped_column(
        nullable=True, comment="numeric 下限，超出判 is_abnormal"
    )
    max_value: Mapped[float | None] = mapped_column(
        nullable=True, comment="numeric 上限，超出判 is_abnormal"
    )
    sort_order: Mapped[int] = mapped_column(default=0, comment="排序")
