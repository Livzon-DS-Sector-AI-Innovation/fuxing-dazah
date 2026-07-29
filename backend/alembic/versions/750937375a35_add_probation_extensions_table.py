"""add probation extensions table

Revision ID: 750937375a35
Revises: 0ef534c0b182
Create Date: 2026-07-20 00:06:59.687730
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '750937375a35'
down_revision: Union[str, None] = '0ef534c0b182'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS hr")
    op.create_table('probation_extensions',
    sa.Column('employee_id', sa.Uuid(), nullable=False, comment='员工ID'),
    sa.Column('employee_number', sa.String(length=32), nullable=False, comment='工号'),
    sa.Column('employee_name', sa.String(length=64), nullable=False, comment='姓名'),
    sa.Column('old_date', sa.Date(), nullable=False, comment='原截止日'),
    sa.Column('new_date', sa.Date(), nullable=False, comment='新截止日'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='hr'
    )
    op.create_index('ix_probation_extensions_employee_id', 'probation_extensions', ['employee_id'], unique=False, schema='hr')


def downgrade() -> None:
    op.drop_index('ix_probation_extensions_employee_id', table_name='probation_extensions', schema='hr')
    op.drop_table('probation_extensions', schema='hr')
