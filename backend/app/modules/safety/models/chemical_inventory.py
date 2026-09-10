"""Safety ORM models."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

# 枚举集中定义在 models/enums.py（保持单一定义点）
from app.modules.safety.models.enums import *  # noqa: F401,F403
from app.shared.base_model import BaseModel

# 业务表均软删除（is_deleted），唯一编号约束使用部分唯一索引
# (WHERE is_deleted = false)，避免「软删→重建同编号」触发约束冲突。
# 见 CLAUDE.md「软删除隐形 bug」注意事项。


# ==================== 危化品库存管理 Enums ====================


class ChemicalDepartmentType(str, PyEnum):
    """危化品库存部门枚举（14 部门 + 其他）。"""

    WAREHOUSE = "warehouse"              # 仓储部
    EXTRACTION_1 = "extraction_1"        # 提炼一部
    EXTRACTION_2 = "extraction_2"        # 提炼二期
    EXTRACTION_2B = "extraction_2b"      # 提炼二部
    FERMENTATION_1 = "fermentation_1"    # 发酵一部
    FERMENTATION_2 = "fermentation_2"    # 发酵二部
    STRAIN = "strain"                    # 菌种中心
    QC = "qc"                            # QC
    ENV = "env"                          # 环保
    PURIFICATION = "purification"        # 精制
    SEMI_SYNTHESIS = "semi_synth"        # 提炼半合成工程中心
    TECH_REFINEMENT = "tech_refine"      # 提炼技术精进中心
    OTHER = "other"


class ChemicalUnitType(str, PyEnum):
    """危化品库存单位枚举。"""

    KG = "kg"
    G = "g"
    T = "T"
    L = "L"
    ML = "ml"
    BOTTLE = "bottle"


class HazardClassType(str, PyEnum):
    """危险性类别（多选）。"""

    FLAMMABLE = "flammable"                        # 易燃
    EXPLOSIVE = "explosive"                        # 易爆
    PRECURSOR_DRUG = "precursor_drug"              # 易制毒
    PRECURSOR_EXPLOSIVE = "precursor_explosive"    # 易制爆
    CORROSIVE = "corrosive"                        # 腐蚀
    TOXIC = "toxic"                                # 毒性
    OXIDIZER = "oxidizer"                          # 氧化剂
    IRRITANT = "irritant"                          # 刺激性


class RiskFlagType(str, PyEnum):
    """库存记录风险标记（系统回填，二元：正常/预警）。"""

    NORMAL = "normal"
    WARN = "warn"


# ==================== 危化品库存管理 Models ====================


class ChemicalInventoryRecord(BaseModel):
    """危化品库存记录（「危化品库存总表」Bitable 镜像）。"""

    __tablename__ = "chemical_inventory_records"
    __table_args__ = (
        Index("idx_cir_feishu_record", "feishu_record_id"),
        Index("idx_cir_dept_loc", "department", "storage_location"),
        Index(
            "uq_cir_feishu_record",
            "feishu_record_id",
            unique=True,
            postgresql_where=text("feishu_record_id IS NOT NULL AND is_deleted = false"),
        ),
        Index(
            "uq_cir_dept_loc_name",
            "department", "storage_location", "material_name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "safety"},
    )

    feishu_record_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Bitable 记录 ID"
    )
    department: Mapped[str] = mapped_column(String(32), nullable=False, comment="部门")
    storage_location: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="存放部位"
    )
    material_name: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="物料名称"
    )
    package_spec: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="包装规格"
    )
    quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 4), nullable=True, comment="库存数量"
    )
    unit: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="单位")
    total_quantity_t: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 4), nullable=True, comment="现场物料总量(T)"
    )
    max_limit: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 4), nullable=True, comment="库存上限"
    )
    max_limit_unit: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="上限单位"
    )
    hazard_classes: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="危险性(多选)"
    )
    category: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="品类")
    last_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最后更新时间（Bitable 系统字段）"
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")
    risk_flag: Mapped[str] = mapped_column(
        String(16), nullable=False, default="normal", server_default="normal",
        comment="风险标记(正常/预警)"
    )
    risk_note: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True, comment="风险说明(预警类型多选)"
    )


class ChemicalInventorySnapshot(BaseModel):
    """危化品库存快照（每周/每日落一份，用于周趋势与每日环比分析）。"""

    __tablename__ = "chemical_inventory_snapshots"
    __table_args__ = (
        Index("idx_cisnap_date_dept", "snapshot_date", "department"),
        Index(
            "uq_cisnap_key",
            "snapshot_date", "snapshot_kind", "department", "storage_location", "material_name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "safety"},
    )

    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, comment="快照日期")
    snapshot_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="weekly", server_default="weekly",
        comment="快照类型(daily/weekly)",
    )
    department: Mapped[str] = mapped_column(String(32), nullable=False, comment="部门")
    storage_location: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="存放部位"
    )
    material_name: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="物料名称"
    )
    quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 4), nullable=True, comment="库存数量"
    )
    unit: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="单位")
    total_quantity_t: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 4), nullable=True, comment="现场物料总量(T)"
    )
    risk_flag: Mapped[str] = mapped_column(
        String(16), nullable=False, default="normal", server_default="normal",
        comment="风险标记(正常/预警)"
    )

