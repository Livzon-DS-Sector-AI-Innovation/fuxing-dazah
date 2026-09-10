"""alter ehs_changes change_type/change_duration to nullable

Bitable「变更验收」表没有变更分类/变更时效列，同步进平台的记录这两列为空。
将两列改为可空，避免 NOT NULL 约束失败。

Revision ID: e5f6a7b8c9d0
Revises: c7e9f1a3b5d7
Create Date: 2026-08-03
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: str | None = 'c7e9f1a3b5d7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        'ehs_changes',
        'change_type',
        existing_type=sa.String(length=32),
        nullable=True,
        schema='safety',
    )
    op.alter_column(
        'ehs_changes',
        'change_duration',
        existing_type=sa.String(length=16),
        nullable=True,
        schema='safety',
    )


def downgrade() -> None:
    op.alter_column(
        'ehs_changes',
        'change_duration',
        existing_type=sa.String(length=16),
        nullable=False,
        existing_server_default=sa.text("'permanent'"),
        schema='safety',
    )
    op.alter_column(
        'ehs_changes',
        'change_type',
        existing_type=sa.String(length=32),
        nullable=False,
        schema='safety',
    )
