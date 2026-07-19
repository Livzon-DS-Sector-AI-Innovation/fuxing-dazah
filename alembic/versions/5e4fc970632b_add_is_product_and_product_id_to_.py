"""add is_product and product_id to intermediate_types, remove is_product from route_node_intermediates

Revision ID: 5e4fc970632b
Revises: 137c5228d679
Create Date: 2026-07-19 15:41:13.135743
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5e4fc970632b'
down_revision: Union[str, None] = '137c5228d679'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS production")
    # intermediate_types: 新增 is_product 和 product_id
    op.add_column(
        'intermediate_types',
        sa.Column('is_product', sa.Boolean(), nullable=False, server_default=sa.text('false'),
                  comment='是否为成品'),
        schema='production',
    )
    op.add_column(
        'intermediate_types',
        sa.Column('product_id', sa.Uuid(), nullable=True,
                  comment='关联的产品ID（可选）'),
        schema='production',
    )
    # 回填已有数据：若 route_node_intermediates 中任一绑定标记为成品，则对应类型也标记为成品
    op.execute("""
        UPDATE production.intermediate_types it
        SET is_product = true
        WHERE it.id IN (
            SELECT DISTINCT rni.intermediate_type_id
            FROM production.route_node_intermediates rni
            WHERE rni.is_product = true
        )
    """)
    # route_node_intermediates: 移除 is_product（成品标记从类型层读取）
    op.drop_column('route_node_intermediates', 'is_product', schema='production')


def downgrade() -> None:
    # 恢复 route_node_intermediates.is_product
    op.add_column(
        'route_node_intermediates',
        sa.Column('is_product', sa.Boolean(), server_default=sa.text('false'),
                  nullable=False, comment='产出方向时标记为成品'),
        schema='production',
    )
    # 移除 intermediate_types 新增列
    op.drop_column('intermediate_types', 'product_id', schema='production')
    op.drop_column('intermediate_types', 'is_product', schema='production')
