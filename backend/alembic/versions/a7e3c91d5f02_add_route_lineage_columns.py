"""add route lineage columns (origin_route_id / origin_node_id)

工艺路线血缘：复刻来源记录，用于数据汇总跨版本合并批次数据。

Revision ID: a7e3c91d5f02
Revises: 4cb39e7a28c0
Create Date: 2026-09-03 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7e3c91d5f02'
down_revision: Union[str, None] = '4cb39e7a28c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 路线级血缘：复刻来源路线（逻辑引用 process_routes.id，不加外键约束）
    op.add_column(
        'process_routes',
        sa.Column(
            'origin_route_id',
            sa.UUID(),
            nullable=True,
            comment='复刻来源路线 id；数据汇总沿此链合并历代版本（祖先+自己）的批次数据',
        ),
        schema='production',
    )
    # 节点级血缘：克隆来源节点（逻辑引用 route_nodes.id）
    op.add_column(
        'route_nodes',
        sa.Column(
            'origin_node_id',
            sa.UUID(),
            nullable=True,
            comment='克隆来源节点 id；跨版本同工序对齐的精确指针（node_code 改名后仍可对齐）',
        ),
        schema='production',
    )


def downgrade() -> None:
    op.drop_column('route_nodes', 'origin_node_id', schema='production')
    op.drop_column('process_routes', 'origin_route_id', schema='production')
