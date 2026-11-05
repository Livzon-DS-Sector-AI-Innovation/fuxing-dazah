"""五金库三期 M8 —— receipts 并存对账两列（reconcile_status + matched_receipt_id）

设计 docs/DESIGN-五金库系统原生模块-20261104.md §六：erp_import 单到达自动匹配
既有 OCR 入库单核对差异。OCR 单是库存权威（实物账），ERP 单=对账载体：
- reconcile_status（独立于 status 的匹配轴）：none/unmatched/matched/verified/
  discrepancy；
- matched_receipt_id 自引用：匹配对另一端单据（erp↔ocr 双向互指）。
verified 的 ERP 单禁止再入账（防双计——库存动账点只有 accepted 批次生成）。

Revision ID: b8c4d6e2f7a3
Revises: a7b3c9d1e2f4
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b8c4d6e2f7a3"
down_revision: str | None = "a7b3c9d1e2f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "warehouse"


def upgrade() -> None:
    op.add_column(
        "hardware_receipts",
        sa.Column("reconcile_status", sa.String(20), nullable=False,
                  server_default="none",
                  comment="OCR↔ERP 并存对账状态（M8）：none/unmatched/matched/"
                          "verified/discrepancy（独立于 status 的匹配轴）"),
        schema=SCHEMA,
    )
    op.add_column(
        "hardware_receipts",
        sa.Column("matched_receipt_id", sa.Uuid(), nullable=True,
                  comment="对账匹配对另一端单据 id（erp↔ocr 双向互指；无匹配=NULL）"),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_hardware_receipts_matched",
        "hardware_receipts",
        "hardware_receipts",
        ["matched_receipt_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
    )
    op.create_index(
        "ix_hardware_receipts_reconcile", "hardware_receipts", ["reconcile_status"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_hardware_receipts_reconcile", table_name="hardware_receipts", schema=SCHEMA)
    op.drop_constraint(
        "fk_hardware_receipts_matched", "hardware_receipts", type_="foreignkey", schema=SCHEMA,
    )
    op.drop_column("hardware_receipts", "matched_receipt_id", schema=SCHEMA)
    op.drop_column("hardware_receipts", "reconcile_status", schema=SCHEMA)
