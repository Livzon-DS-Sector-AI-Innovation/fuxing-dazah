"""add_missing_columns_to_transfer_records

Revision ID: 3cb8b3fa4e6d
Revises: 2afdfae4653f
Create Date: 2026-07-19 22:45:03.690674
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '3cb8b3fa4e6d'
down_revision: Union[str, None] = '2afdfae4653f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('transfer_records', sa.Column('created_by', sa.Uuid(), nullable=True, comment='创建人'), schema='hr')
    op.add_column('transfer_records', sa.Column('updated_by', sa.Uuid(), nullable=True, comment='更新人'), schema='hr')


def downgrade() -> None:
    op.drop_column('transfer_records', 'updated_by', schema='hr')
    op.drop_column('transfer_records', 'created_by', schema='hr')
