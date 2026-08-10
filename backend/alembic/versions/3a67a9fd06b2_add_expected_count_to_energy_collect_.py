"""add expected_count to energy_collect_logs

Revision ID: 3a67a9fd06b2
Revises: b1c2d3e4f5a6
Create Date: 2026-08-07 15:52:18
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '3a67a9fd06b2'
down_revision: str | None = 'b1c2d3e4f5a6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'energy_collect_logs',
        sa.Column(
            'expected_count',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment='预期数据条数（daily设备为1/台，hourly为24/台）',
        ),
        schema='energy',
    )


def downgrade() -> None:
    op.drop_column('energy_collect_logs', 'expected_count', schema='energy')
