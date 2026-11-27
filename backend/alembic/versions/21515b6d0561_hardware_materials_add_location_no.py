"""五金库物资目录加位号列（2026-11-25 清单翻新配套）

目录级"位号"=默认存放位（如 A-1），来自《五金库物资清单编码库位.xlsx》；
展示/检索用。批次级库位仍以入库上架（hardware_receipt_items.location_id）
为准，两套并行不冲突。

Revision ID: 21515b6d0561
Revises: 6fda99ea30dd
Create Date: 2026-11-25 15:27:39.538384
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "21515b6d0561"
down_revision: str | None = "6fda99ea30dd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "warehouse"
TABLE = "hardware_materials"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "location_no",
            sa.String(length=100),
            nullable=True,
            comment="位号（默认存放位，目录级展示/检索用；批次级库位仍以入库上架为准）",
        ),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column(TABLE, "location_no", schema=SCHEMA)
