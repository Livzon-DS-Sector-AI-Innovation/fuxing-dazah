"""plan_allocations.allocated_quantity 改为可空 — 计划数量不填不阻塞下达

Revision ID: e01f2e3d4c5a
Revises: e00e006eea52
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e01f2e3d4c5a"
down_revision: str | None = "e00e006eea52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "plan_allocations",
        "allocated_quantity",
        existing_type=sa.Float(),
        nullable=True,
        schema="production",
    )


def downgrade() -> None:
    op.alter_column(
        "plan_allocations",
        "allocated_quantity",
        existing_type=sa.Float(),
        nullable=False,
        schema="production",
    )
