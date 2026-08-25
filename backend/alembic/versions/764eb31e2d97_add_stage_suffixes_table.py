"""add stage_suffixes table

Revision ID: 764eb31e2d97
Revises: 1fdb06c8d7bb
Create Date: 2026-08-18 17:33:17.586490
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '764eb31e2d97'
down_revision: str | None = '1fdb06c8d7bb'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS production")

    op.create_table(
        'stage_suffixes',
        sa.Column('route_id', sa.Uuid(), nullable=False),
        sa.Column('stage_name', sa.String(length=100), nullable=False),
        sa.Column('suffix', sa.String(length=50), nullable=False, server_default='', comment='批次尾缀，空字符串=不追加'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='production',
    )
    op.create_index(
        'uq_production_stage_suffixes',
        'stage_suffixes',
        ['route_id', 'stage_name'],
        unique=True,
        schema='production',
        postgresql_where=sa.text('is_deleted = false'),
    )
    op.create_index('ix_production_stage_suffixes_route', 'stage_suffixes', ['route_id'], unique=False, schema='production')


def downgrade() -> None:
    op.drop_index('ix_production_stage_suffixes_route', table_name='stage_suffixes', schema='production')
    op.drop_index(
        'uq_production_stage_suffixes',
        table_name='stage_suffixes',
        schema='production',
        postgresql_where=sa.text('is_deleted = false'),
    )
    op.drop_table('stage_suffixes', schema='production')
