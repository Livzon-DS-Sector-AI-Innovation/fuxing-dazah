"""add_employee_tags

Revision ID: 9b36fb027df9
Revises: 9eed3bb4dbfb
Create Date: 2026-08-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9b36fb027df9'
down_revision: Union[str, None] = '9eed3bb4dbfb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS hr")
    op.create_table(
        'employee_tags',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('employee_number', sa.String(32), nullable=False, comment='员工工号'),
        sa.Column('tag_name', sa.String(64), nullable=False, comment='标签名称'),
        sa.Column('created_by', sa.String(64), nullable=False, comment='创建人'),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        schema='hr',
    )
    op.create_index('ix_employee_tags_employee', 'employee_tags', ['employee_number'], schema='hr')
    op.create_index('ix_employee_tags_creator', 'employee_tags', ['created_by'], schema='hr')


def downgrade() -> None:
    op.drop_table('employee_tags', schema='hr')
