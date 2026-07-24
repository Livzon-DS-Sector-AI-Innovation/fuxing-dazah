"""add concurrent_variety and certificates to employees

Revision ID: 3128a2a1e622
Revises: b4f717ac6a45
Create Date: 2026-07-24 15:45:36.191750
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '3128a2a1e622'
down_revision: Union[str, None] = 'b4f717ac6a45'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('employees', sa.Column('concurrent_variety', sa.String(length=256), nullable=True, comment='兼任品种'), schema='hr')
    op.add_column('employees', sa.Column('certificates', sa.String(length=512), nullable=True, comment='证书'), schema='hr')


def downgrade() -> None:
    op.drop_column('employees', 'certificates', schema='hr')
    op.drop_column('employees', 'concurrent_variety', schema='hr')
