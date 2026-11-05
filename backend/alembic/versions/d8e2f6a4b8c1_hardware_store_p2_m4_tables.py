"""五金库二期 M4 —— 盘点/退库三表 + receipts.source 枚举扩展

设计 docs/DESIGN-五金库系统原生模块-20261104.md §2.6：
- hardware_stocktakes(+items)：盘点单（book 快照 vs 实盘直填，人确认才 ADJ 入账）
- hardware_returns：退库单（验收/不合格拒退/批次回加）
- hardware_receipts.source CheckConstraint 扩 'stocktake'/'return'——系统单据
  载体（盘点盘盈批次/退库回加批次），纯加值，存量数据不动。

Revision ID: d8e2f6a4b8c1
Revises: c4a8e2f6b0d3
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "d8e2f6a4b8c1"
down_revision: str | None = "c4a8e2f6b0d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "warehouse"

_COMMON_COLUMNS = [
    sa.Column("id", UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.Column("created_by", UUID(), nullable=True),
    sa.Column("updated_by", UUID(), nullable=True),
    sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
]


def upgrade() -> None:
    # receipts.source 纯加值（stocktake/return 系统单据载体）
    op.drop_constraint("ck_hardware_receipts_source", "hardware_receipts", schema=SCHEMA)
    op.create_check_constraint(
        "ck_hardware_receipts_source",
        "hardware_receipts",
        "source IN ('ocr', 'manual', 'erp_import', 'stocktake', 'return')",
        schema=SCHEMA,
    )

    op.create_table(
        "hardware_stocktakes",
        *_COMMON_COLUMNS,
        sa.Column("take_no", sa.String(50), nullable=False, comment="盘点单号 WJK-PD-YYMMDD-序号"),
        sa.Column("take_type", sa.String(20), nullable=False, server_default="monthly",
                  comment="monthly/annual/special/calibration（期初校准）"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft",
                  comment="draft/counting/reviewed/confirmed/cancelled"),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=True, comment="book 快照时间"),
        sa.Column("summary_note", sa.Text(), nullable=True, comment="盘点总结说明"),
        sa.Column("diff_surplus_items", sa.Integer(), nullable=True, comment="盘盈行数"),
        sa.Column("diff_deficit_items", sa.Integer(), nullable=True, comment="盘亏行数"),
        sa.Column("diff_total_amount", sa.Numeric(18, 2), nullable=True, comment="差异金额合计"),
        sa.Column("explained_by", sa.String(100), nullable=True, comment="差异说明填写人"),
        sa.Column("explained_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by", sa.String(100), nullable=True, comment="确认人（Web 确认门）"),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "take_type IN ('monthly', 'annual', 'special', 'calibration')",
            name="ck_hardware_stocktakes_type",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'counting', 'reviewed', 'confirmed', 'cancelled')",
            name="ck_hardware_stocktakes_status",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_hardware_stocktakes_no", "hardware_stocktakes", ["take_no"], unique=True,
        postgresql_where=sa.text("is_deleted = false"), schema=SCHEMA,
    )
    op.create_index("ix_hardware_stocktakes_status", "hardware_stocktakes", ["status"], schema=SCHEMA)

    op.create_table(
        "hardware_stocktake_items",
        *_COMMON_COLUMNS,
        sa.Column("stocktake_id", UUID(), nullable=False),
        sa.Column("material_id", UUID(), nullable=False),
        sa.Column("code", sa.String(50), nullable=True, comment="物料编码快照"),
        sa.Column("name", sa.String(200), nullable=False, comment="品名快照"),
        sa.Column("spec", sa.String(200), nullable=True),
        sa.Column("unit", sa.String(20), nullable=True),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=True, comment="单价快照"),
        sa.Column("book_qty", sa.Numeric(18, 3), nullable=False, comment="账存（批次余额合计）"),
        sa.Column("actual_qty", sa.Numeric(18, 3), nullable=True, comment="实盘（NULL=未盘）"),
        sa.Column("diff_qty", sa.Numeric(18, 3), nullable=True, comment="差异=实盘−账存"),
        sa.Column("diff_amount", sa.Numeric(18, 4), nullable=True, comment="差异金额"),
        sa.Column("explanation", sa.String(500), nullable=True, comment="差异说明（行级）"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("book_qty >= 0", name="ck_hardware_stocktake_items_book"),
        sa.CheckConstraint(
            "actual_qty IS NULL OR actual_qty >= 0", name="ck_hardware_stocktake_items_actual",
        ),
        sa.ForeignKeyConstraint(["stocktake_id"], ["warehouse.hardware_stocktakes.id"]),
        sa.ForeignKeyConstraint(["material_id"], ["warehouse.hardware_materials.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_hardware_stocktake_items_take", "hardware_stocktake_items", ["stocktake_id"], schema=SCHEMA,
    )
    op.create_index(
        "ix_hardware_stocktake_items_material", "hardware_stocktake_items", ["material_id"], schema=SCHEMA,
    )

    op.create_table(
        "hardware_returns",
        *_COMMON_COLUMNS,
        sa.Column("return_no", sa.String(50), nullable=False, comment="退库单号 WJK-TK-YYMMDD-序号"),
        sa.Column("dept_name", sa.String(100), nullable=False, comment="退库部门"),
        sa.Column("returned_by", sa.String(100), nullable=False, comment="退库人"),
        sa.Column("returned_by_open_id", sa.String(100), nullable=True, comment="退库人 open_id"),
        sa.Column("items", JSONB(), nullable=False,
                  comment="明细行 JSON [{material_id,code,name,spec,unit,quantity,preferred_lot_id}]"),
        sa.Column("leader_signed", sa.Boolean(), nullable=False, server_default=sa.text("false"),
                  comment="部门负责人已签"),
        sa.Column("leader_signed_by", sa.String(100), nullable=True),
        sa.Column("leader_signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft",
                  comment="draft/accepted/rejected"),
        sa.Column("accepted_by", sa.String(100), nullable=True, comment="验收仓管员"),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_reason", sa.String(500), nullable=True, comment="不合格拒退原因"),
        sa.Column("lot_adjustments", JSONB(), nullable=True, comment="批次回加结果"),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('draft', 'accepted', 'rejected')", name="ck_hardware_returns_status",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_hardware_returns_no", "hardware_returns", ["return_no"], unique=True,
        postgresql_where=sa.text("is_deleted = false"), schema=SCHEMA,
    )
    op.create_index("ix_hardware_returns_status", "hardware_returns", ["status"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_hardware_returns_status", table_name="hardware_returns", schema=SCHEMA)
    op.drop_index("uq_hardware_returns_no", table_name="hardware_returns", schema=SCHEMA)
    op.drop_table("hardware_returns")

    op.drop_index(
        "ix_hardware_stocktake_items_material", table_name="hardware_stocktake_items", schema=SCHEMA,
    )
    op.drop_index("ix_hardware_stocktake_items_take", table_name="hardware_stocktake_items", schema=SCHEMA)
    op.drop_table("hardware_stocktake_items")

    op.drop_index("ix_hardware_stocktakes_status", table_name="hardware_stocktakes", schema=SCHEMA)
    op.drop_index("uq_hardware_stocktakes_no", table_name="hardware_stocktakes", schema=SCHEMA)
    op.drop_table("hardware_stocktakes")

    op.drop_constraint("ck_hardware_receipts_source", "hardware_receipts", schema=SCHEMA)
    op.create_check_constraint(
        "ck_hardware_receipts_source",
        "hardware_receipts",
        "source IN ('ocr', 'manual', 'erp_import')",
        schema=SCHEMA,
    )
