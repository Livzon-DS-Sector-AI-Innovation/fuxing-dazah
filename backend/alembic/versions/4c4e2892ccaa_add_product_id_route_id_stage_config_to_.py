"""add product_id route_id stage_config to plan_orders; add stage_durations to plan_items

Revision ID: 4c4e2892ccaa
Revises: d54a9f883c32
Create Date: 2026-07-28 10:26:46.610002
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '4c4e2892ccaa'
down_revision: str | None = 'd54a9f883c32'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('plan_items', sa.Column('stage_durations', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='工段时长覆盖'), schema='production')
    op.add_column('plan_orders', sa.Column('product_id', sa.Uuid(), nullable=True, comment='绑定的产品'), schema='production')
    op.add_column('plan_orders', sa.Column('route_id', sa.Uuid(), nullable=True, comment='绑定的工艺路线'), schema='production')
    op.add_column('plan_orders', sa.Column('stage_config', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='工段配置'), schema='production')


def downgrade() -> None:
    op.drop_column('plan_orders', 'stage_config', schema='production')
    op.drop_column('plan_orders', 'route_id', schema='production')
    op.drop_column('plan_orders', 'product_id', schema='production')
    op.drop_column('plan_items', 'stage_durations', schema='production')
