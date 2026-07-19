"""add is_product to intermediate tables

Revision ID: 137c5228d679
Revises: cf35485d0c6b
Create Date: 2026-07-17 15:00:23.097361
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '137c5228d679'
down_revision: Union[str, None] = 'cf35485d0c6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为中间体台账相关表增加 is_product 成品标记字段。"""
    op.add_column(
        'batch_intermediate_outputs',
        sa.Column('is_product', sa.Boolean(), nullable=False,
                  server_default=sa.text('false'), comment='是否成品产出'),
        schema='production',
    )
    op.add_column(
        'route_node_intermediates',
        sa.Column('is_product', sa.Boolean(), nullable=False,
                  server_default=sa.text('false'), comment='产出方向时标记为成品'),
        schema='production',
    )


def downgrade() -> None:
    op.drop_column('route_node_intermediates', 'is_product', schema='production')
    op.drop_column('batch_intermediate_outputs', 'is_product', schema='production')
