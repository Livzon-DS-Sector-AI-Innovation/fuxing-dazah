"""五金库入库 Excel 方式② —— receipts.source 加 'excel' 值

入库登记新增 Excel 解析方式（excel_io.parse_receipt_excel → source=excel
落草稿），DB CHECK 约束同步放行（P1 建 'ocr/manual/erp_import'，M4 加
'stocktake/return'，本迁移加 'excel'）。

Revision ID: g5b7d9f1e3c4
Revises: f4a6c8e0d2b3
Create Date: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "g5b7d9f1e3c4"
down_revision: str | None = "f4a6c8e0d2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "warehouse"


def upgrade() -> None:
    op.drop_constraint("ck_hardware_receipts_source", "hardware_receipts", schema=SCHEMA)
    op.create_check_constraint(
        "ck_hardware_receipts_source",
        "hardware_receipts",
        "source IN ('ocr', 'manual', 'excel', 'erp_import', 'stocktake', 'return')",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint("ck_hardware_receipts_source", "hardware_receipts", schema=SCHEMA)
    op.create_check_constraint(
        "ck_hardware_receipts_source",
        "hardware_receipts",
        "source IN ('ocr', 'manual', 'erp_import', 'stocktake', 'return')",
        schema=SCHEMA,
    )
