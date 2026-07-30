"""add exclude_from_stats to energy_device_configs

Revision ID: 393e668958f2
Revises: e00e006eea52
Create Date: 2026-07-30 15:44:23.835699
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '393e668958f2'
down_revision: Union[str, None] = 'e00e006eea52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'energy_device_configs',
        sa.Column(
            'exclude_from_stats',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
            comment='是否不参与能源总耗统计与可视化',
        ),
        schema='energy',
    )


def downgrade() -> None:
    op.drop_column('energy_device_configs', 'exclude_from_stats', schema='energy')
