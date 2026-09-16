"""warehouse locations add zone/aisle/row/level

库位层级列（均可空）：zone 库区、aisle 巷道、shelf_row 货架行、shelf_level 货架层。
支持库位地图 CSS Grid 格子图按层级分组渲染。

Revision ID: k6e9f1a3b7c4
Revises: j5d2e8f3a6b9
Create Date: 2026-09-16
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'k6e9f1a3b7c4'
down_revision: str | None = 'j5d2e8f3a6b9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('warehouse_locations',
        sa.Column('zone', sa.String(length=32), nullable=True, comment='库区'), schema='warehouse')
    op.add_column('warehouse_locations',
        sa.Column('aisle', sa.String(length=32), nullable=True, comment='巷道/排'), schema='warehouse')
    op.add_column('warehouse_locations',
        sa.Column('shelf_row', sa.String(length=32), nullable=True, comment='货架行'), schema='warehouse')
    op.add_column('warehouse_locations',
        sa.Column('shelf_level', sa.String(length=32), nullable=True, comment='货架层'), schema='warehouse')


def downgrade() -> None:
    op.drop_column('warehouse_locations', 'shelf_level', schema='warehouse')
    op.drop_column('warehouse_locations', 'shelf_row', schema='warehouse')
    op.drop_column('warehouse_locations', 'aisle', schema='warehouse')
    op.drop_column('warehouse_locations', 'zone', schema='warehouse')
