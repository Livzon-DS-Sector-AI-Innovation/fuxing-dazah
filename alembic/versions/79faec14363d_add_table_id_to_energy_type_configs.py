"""add table_id to energy_type_configs

Revision ID: 79faec14363d
Revises: 20fda41cfdd3
Create Date: 2026-07-15 11:15:35.192814
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '79faec14363d'
down_revision: Union[str, None] = '20fda41cfdd3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS energy")
    op.add_column(
        'energy_type_configs',
        sa.Column('table_id', sa.String(length=100), nullable=True, comment='飞书多维表格 Table ID'),
        schema='energy',
    )


def downgrade() -> None:
    op.drop_column('energy_type_configs', 'table_id', schema='energy')
