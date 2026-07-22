"""swap product unique index from product_code to product_name

Revision ID: 79ae97a9950f
Revises: a79d16d56870
Create Date: 2026-07-15 18:04:38.423716
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '79ae97a9950f'
down_revision: Union[str, None] = 'a79d16d56870'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS production")
    # 删旧唯一索引 (product_code)
    op.drop_index(
        op.f('uq_production_products_code'),
        table_name='products',
        schema='production',
        postgresql_where='(is_deleted = false)',
    )
    # product_code → nullable
    op.alter_column(
        'products',
        'product_code',
        existing_type=sa.String(50),
        nullable=True,
        schema='production',
    )
    # 建新唯一索引 (product_name)
    op.create_index(
        'uq_production_products_name',
        'products',
        ['product_name'],
        unique=True,
        schema='production',
        postgresql_where=sa.text('is_deleted = false'),
    )


def downgrade() -> None:
    op.drop_index(
        'uq_production_products_name',
        table_name='products',
        schema='production',
        postgresql_where=sa.text('is_deleted = false'),
    )
    op.alter_column(
        'products',
        'product_code',
        existing_type=sa.String(50),
        nullable=False,
        schema='production',
    )
    op.create_index(
        op.f('uq_production_products_code'),
        'products',
        ['product_code'],
        unique=True,
        schema='production',
        postgresql_where='(is_deleted = false)',
    )
