"""add stage_assignments and node_assignments tables

Revision ID: 63a79de496da
Revises: 9741f88ac586
Create Date: 2026-07-21 15:07:25.125312
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '63a79de496da'
down_revision: Union[str, None] = '9741f88ac586'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS production")

    op.create_table('node_assignments',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('node_id', sa.Uuid(), nullable=False),
        sa.Column('route_id', sa.Uuid(), nullable=False),
        sa.Column('assigned_by', sa.Uuid(), nullable=False),
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
        'ix_production_node_assignments_node',
        'node_assignments', ['node_id'], unique=False, schema='production',
    )
    op.create_index(
        'ix_production_node_assignments_user',
        'node_assignments', ['user_id'], unique=False, schema='production',
    )
    op.create_index(
        'uq_production_node_assignments',
        'node_assignments', ['user_id', 'node_id'],
        unique=True, schema='production',
        postgresql_where=sa.text('is_deleted = false'),
    )

    op.create_table('stage_assignments',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('stage_name', sa.String(length=100), nullable=False),
        sa.Column('route_id', sa.Uuid(), nullable=False),
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
        'ix_production_stage_assignments_route',
        'stage_assignments', ['route_id'], unique=False, schema='production',
    )
    op.create_index(
        'ix_production_stage_assignments_user',
        'stage_assignments', ['user_id'], unique=False, schema='production',
    )
    op.create_index(
        'uq_production_stage_assignments',
        'stage_assignments', ['user_id', 'stage_name', 'route_id'],
        unique=True, schema='production',
        postgresql_where=sa.text('is_deleted = false'),
    )


def downgrade() -> None:
    op.drop_index(
        'uq_production_stage_assignments',
        table_name='stage_assignments', schema='production',
        postgresql_where=sa.text('is_deleted = false'),
    )
    op.drop_index(
        'ix_production_stage_assignments_user',
        table_name='stage_assignments', schema='production',
    )
    op.drop_index(
        'ix_production_stage_assignments_route',
        table_name='stage_assignments', schema='production',
    )
    op.drop_table('stage_assignments', schema='production')

    op.drop_index(
        'uq_production_node_assignments',
        table_name='node_assignments', schema='production',
        postgresql_where=sa.text('is_deleted = false'),
    )
    op.drop_index(
        'ix_production_node_assignments_user',
        table_name='node_assignments', schema='production',
    )
    op.drop_index(
        'ix_production_node_assignments_node',
        table_name='node_assignments', schema='production',
    )
    op.drop_table('node_assignments', schema='production')
