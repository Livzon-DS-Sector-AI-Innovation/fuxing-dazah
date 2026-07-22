"""add position_name to sop_catalog

Revision ID: 16fda41cfdd9
Revises: 15fda41cfdd8
Create Date: 2026-07-10 11:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '16fda41cfdd9'
down_revision: Union[str, None] = '15fda41cfdd8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sop_catalog', sa.Column('position_name', sa.String(128), nullable=True, comment='适用岗位'), schema='hr')
    op.create_index('ix_sop_catalog_position', 'sop_catalog', ['position_name'], schema='hr')


def downgrade() -> None:
    op.drop_index('ix_sop_catalog_position', table_name='sop_catalog', schema='hr')
    op.drop_column('sop_catalog', 'position_name', schema='hr')
