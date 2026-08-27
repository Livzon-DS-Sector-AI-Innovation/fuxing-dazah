"""批次实例层 ORM：批次 / 谱系。"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class Batch(BaseModel):
    """生产批次。批号跟着批次段走，段边界由边定义"""

    __tablename__ = "batches"
    __table_args__ = (
        Index(
            "uq_production_batches_no",
            "batch_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_production_batches_product_status", "product_id", "status"),
        CheckConstraint(
            "status IN ('draft', 'scheduled', 'released', 'pending', 'in_progress', 'completed', 'cancelled')",
            name="ck_production_batches_status",
        ),
        CheckConstraint(
            "creation_type IN ('plan', 'rework', 'outsource', 'trial', 'direct')",
            name="ck_production_batches_creation_type",
        ),
        {"schema": "production"},
    )

    batch_no: Mapped[str] = mapped_column(String(50), comment="批号")
    product_id: Mapped[uuid.UUID] = mapped_column(comment="产品")
    route_id: Mapped[uuid.UUID] = mapped_column(comment="创建时锁定的路线版本")
    status: Mapped[str] = mapped_column(
        String(20), default="pending", comment="draft/scheduled/released/pending/in_progress/completed/cancelled"
    )
    quantity: Mapped[float | None] = mapped_column(nullable=True, comment="本批数量")
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="单位")
    entry_node_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True,
        comment="入口工序节点：derive/merge 产生的批次记录边界边的 to_node；根批次为空",
    )
    creation_type: Mapped[str] = mapped_column(
        String(20), default="direct", comment="plan/rework/outsource/trial/direct"
    )
    plan_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="由计划生成时记录所依据的计划版本"
    )
    first_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="首工序开始时间"
    )
    last_finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="末工序结束时间"
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True, comment="批次归属人，接收/开始工序时写入；空=无主共享"
    )
    owner_name: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="归属人姓名快照"
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class BatchLink(BaseModel):
    """批次谱系：一行 = 一条父子关系。分裂 1→N = N 行同 parent；合并 N→1 = N 行同 child"""

    __tablename__ = "batch_links"
    __table_args__ = (
        Index(
            "uq_production_batch_links",
            "parent_batch_id",
            "child_batch_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_production_batch_links_parent", "parent_batch_id"),
        Index("ix_production_batch_links_child", "child_batch_id"),
        {"schema": "production"},
    )

    parent_batch_id: Mapped[uuid.UUID] = mapped_column(comment="父批次")
    child_batch_id: Mapped[uuid.UUID] = mapped_column(comment="子批次")
    edge_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True, comment="走的哪条边界边；临时偏离时为空"
    )
    allocated_qty: Mapped[float | None] = mapped_column(
        nullable=True, comment="父批分给此子批的量"
    )
    is_deviation: Mapped[bool] = mapped_column(default=False, comment="未走预定义边界")
    deviation_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="偏离原因，偏离时必填"
    )
