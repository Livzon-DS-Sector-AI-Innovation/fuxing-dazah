"""物料容器二维码赋码模型：物料字典、容器台账、进出库流水。"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class QualityMaterial(BaseModel):
    """物料主数据字典（轻量版）：赋码下拉与采购清单的基础。

    后续 01 方案物料标准库落地后，标准按「物料+供应商」挂在本表之下。
    """

    __tablename__ = "quality_materials"
    __table_args__ = (
        Index(
            "uq_quality_material_code",
            "code",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_quality_material_name", "name"),
        {"schema": "quality"},
    )

    code: Mapped[str] = mapped_column(String(100), comment="物料代码（容器号中段）")
    name: Mapped[str] = mapped_column(String(200), comment="物料名称")
    category: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="类别：原料/辅料/包材/溶剂"
    )
    vendor_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="默认供应商名称")
    pack_spec: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="包装规格，如 5kg/听")
    min_stock: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="安全库存阈值（瓶/桶数），采购建议依据"
    )
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")


class QualityMaterialContainer(BaseModel):
    """物料容器（每瓶/桶一个唯一容器号，二维码赋码）。

    status 流转：labeled 已赋码 → in_warehouse 在库待验 → qualified 合格
    → issued 已领出 / returned 退库；void 作废。阶段1为人工流转，
    后续接入请验/放行链路后自动联动（见质量设计文档 06）。
    """

    __tablename__ = "quality_material_containers"
    __table_args__ = (
        Index(
            "uq_quality_container_no",
            "container_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_quality_container_batch", "inbound_batch_no"),
        Index("ix_quality_container_status", "status"),
        {"schema": "quality"},
    )

    container_no: Mapped[str] = mapped_column(String(100), comment="容器号，如 MC-VAN-20261010-0001")
    material_code: Mapped[str] = mapped_column(String(100), comment="物料代码")
    material_name: Mapped[str] = mapped_column(String(200), comment="物料名称")
    vendor_code: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="供应商代码"
    )
    inbound_batch_no: Mapped[str] = mapped_column(String(100), comment="进厂批号")
    expiry_date: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="复验期 YYYY-MM-DD（过期拦截用，阶段3）"
    )
    seq: Mapped[int] = mapped_column(comment="该批第几瓶（容器号末段流水）")
    status: Mapped[str] = mapped_column(
        String(32), default="labeled", comment="labeled/in_warehouse/qualified/issued/returned/void"
    )
    qr_issued_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True, comment="赋码人")


class QualityContainerMovement(BaseModel):
    """容器进出库流水（操作日志，供台账审计）。"""

    __tablename__ = "quality_container_movements"
    __table_args__ = (
        Index("ix_quality_container_mv_container", "container_id"),
        {"schema": "quality"},
    )

    container_id: Mapped[uuid.UUID] = mapped_column(
        comment="逻辑引用 quality.quality_material_containers.id（无 FK）"
    )
    container_no: Mapped[str] = mapped_column(String(100), comment="操作时容器号快照")
    op_type: Mapped[str] = mapped_column(String(16), comment="in 入库登记 / out 领料出库 / status 人工流转")
    from_status: Mapped[str] = mapped_column(String(32), comment="操作前状态")
    to_status: Mapped[str] = mapped_column(String(32), comment="操作后状态")
    operator: Mapped[uuid.UUID | None] = mapped_column(nullable=True, comment="操作人")
    op_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now, comment="操作时间")
    related_doc: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="关联单据号（领料单等）"
    )
    remark: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="备注")
