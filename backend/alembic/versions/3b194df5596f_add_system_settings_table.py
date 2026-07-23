"""add system settings table

Revision ID: 3b194df5596f
Revises: 7f04ac1de356
Create Date: 2026-07-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '3b194df5596f'
down_revision: Union[str, None] = '7f04ac1de356'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS hr")
    op.create_table('system_settings',
    sa.Column('key', sa.String(length=64), nullable=False, comment='配置键'),
    sa.Column('value', sa.Text(), server_default='', nullable=False, comment='配置值'),
    sa.Column('description', sa.String(length=256), nullable=True, comment='说明'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key'),
    schema='hr'
    )
    op.create_index('ix_system_settings_key', 'system_settings', ['key'], unique=True, schema='hr')


def downgrade() -> None:
    op.drop_index('ix_system_settings_key', table_name='system_settings', schema='hr')
    op.drop_table('system_settings', schema='hr')
