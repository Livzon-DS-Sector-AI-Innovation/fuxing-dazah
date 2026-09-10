"""add snapshot_kind to chemical_inventory_snapshots

每日分析日报需要每日一份快照与每周快照并存（周五同日期会冲突），
增加 snapshot_kind(daily/weekly) 并把唯一索引纳入该字段。

Revision ID: c9d8e7f6a5b4
Revises: ai_scenario001b2c3d4e5
Create Date: 2026-08-31 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9d8e7f6a5b4"
down_revision: str | None = "ai_scenario001b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chemical_inventory_snapshots",
        sa.Column(
            "snapshot_kind",
            sa.String(16),
            nullable=False,
            server_default="weekly",
            comment="快照类型(daily/weekly)",
        ),
        schema="safety",
    )
    op.drop_index("uq_cisnap_key", table_name="chemical_inventory_snapshots", schema="safety")
    op.create_index(
        "uq_cisnap_key",
        "chemical_inventory_snapshots",
        ["snapshot_date", "snapshot_kind", "department", "storage_location", "material_name"],
        unique=True,
        schema="safety",
        postgresql_where=sa.text("is_deleted = false"),
    )


def downgrade() -> None:
    op.drop_index("uq_cisnap_key", table_name="chemical_inventory_snapshots", schema="safety")
    op.create_index(
        "uq_cisnap_key",
        "chemical_inventory_snapshots",
        ["snapshot_date", "department", "storage_location", "material_name"],
        unique=True,
        schema="safety",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_column("chemical_inventory_snapshots", "snapshot_kind", schema="safety")
