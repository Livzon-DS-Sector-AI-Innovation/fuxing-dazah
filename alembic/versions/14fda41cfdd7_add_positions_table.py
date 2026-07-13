"""add positions table

Revision ID: 14fda41cfdd7
Revises: c259c81b2e9c
Create Date: 2026-07-09 19:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '14fda41cfdd7'
down_revision: Union[str, None] = 'c259c81b2e9c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('positions',
        sa.Column('department', sa.String(128), nullable=False, comment='部门名称'),
        sa.Column('name', sa.String(128), nullable=False, comment='职位名称'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0', comment='排序'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='hr'
    )
    op.create_index('ix_positions_department', 'positions', ['department'], schema='hr')


def downgrade() -> None:
    op.drop_table('positions', schema='hr')
