"""remove parent_code from energy_type_configs

Revision ID: d0370703ae72
Revises: b095f9be5e5b
Create Date: 2026-08-10 10:54:59.274301
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd0370703ae72'
down_revision: Union[str, None] = 'b095f9be5e5b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('energy_type_configs', 'parent_code', schema='energy')


def downgrade() -> None:
    op.add_column(
        'energy_type_configs',
        sa.Column('parent_code', sa.String(length=50), nullable=True, comment='父级编码，顶层分类为 NULL'),
        schema='energy',
    )
