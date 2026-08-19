"""add production lines and line_id

Revision ID: 1fdb06c8d7bb
Revises: 4757c6cb0533
Create Date: 2026-08-18 16:21:54.753038
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '1fdb06c8d7bb'
down_revision: str | None = '4757c6cb0533'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS production")

    op.create_table(
        'lines',
        sa.Column('name', sa.String(length=200), nullable=False, comment='产线名称'),
        sa.Column('remark', sa.Text(), nullable=True, comment='备注'),
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
        'uq_production_lines_name',
        'lines',
        ['name'],
        unique=True,
        schema='production',
        postgresql_where=sa.text('is_deleted = false'),
    )

    op.create_table(
        'line_assignments',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('line_id', sa.Uuid(), nullable=False),
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
        'uq_production_line_assignments',
        'line_assignments',
        ['user_id', 'line_id'],
        unique=True,
        schema='production',
        postgresql_where=sa.text('is_deleted = false'),
    )
    op.create_index('ix_production_line_assignments_user', 'line_assignments', ['user_id'], unique=False, schema='production')
    op.create_index('ix_production_line_assignments_line', 'line_assignments', ['line_id'], unique=False, schema='production')

    op.add_column(
        'batch_intermediate_outputs',
        sa.Column('line_id', sa.Uuid(), nullable=True, comment='产出落地的产线（历史数据为空）'),
        schema='production',
    )


def downgrade() -> None:
    op.drop_column('batch_intermediate_outputs', 'line_id', schema='production')

    op.drop_index('ix_production_line_assignments_line', table_name='line_assignments', schema='production')
    op.drop_index('ix_production_line_assignments_user', table_name='line_assignments', schema='production')
    op.drop_index(
        'uq_production_line_assignments',
        table_name='line_assignments',
        schema='production',
        postgresql_where=sa.text('is_deleted = false'),
    )
    op.drop_table('line_assignments', schema='production')

    op.drop_index(
        'uq_production_lines_name',
        table_name='lines',
        schema='production',
        postgresql_where=sa.text('is_deleted = false'),
    )
    op.drop_table('lines', schema='production')
