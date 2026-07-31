"""add quality product standards table

Revision ID: c9d2f8a3e5b1
Revises: b3c8d7e1f2a4
Create Date: 2026-07-28 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9d2f8a3e5b1'
down_revision: Union[str, None] = 'b3c8d7e1f2a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建产品标准配置表。"""
    op.execute("CREATE SCHEMA IF NOT EXISTS quality")
    op.create_table('product_standards',
        sa.Column('product_name', sa.String(length=200), nullable=False, comment='产品名称'),
        sa.Column('standard_type', sa.String(length=20), nullable=True, comment='标准类型'),
        sa.Column('item_name', sa.String(length=100), nullable=False, comment='指标名称'),
        sa.Column('operator', sa.String(length=10), server_default='≤', nullable=False, comment='比较运算符'),
        sa.Column('limit_value', sa.Float(), nullable=True, comment='合格限度值'),
        sa.Column('oot_haf', sa.Float(), nullable=True, comment='OOT阈值HAF'),
        sa.Column('oot_haa', sa.Float(), nullable=True, comment='OOT阈值HAA'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='quality'
    )
    op.create_index('uq_quality_product_standards_item', 'product_standards',
                    ['product_name', 'item_name'],
                    unique=True, schema='quality',
                    postgresql_where=sa.text('is_deleted = false'))


def downgrade() -> None:
    """删除产品标准配置表。"""
    op.drop_table('product_standards', schema='quality')
