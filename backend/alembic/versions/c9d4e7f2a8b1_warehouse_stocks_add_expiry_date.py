"""warehouse stocks add expiry_date

库存表新增批次效期列（可空）：入库登记时录入，随最近一次入库更新；
列表按临期程度着色。

Revision ID: c9d4e7f2a8b1
Revises: b3e8c2d1f4a6
Create Date: 2026-09-15
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c9d4e7f2a8b1'
down_revision: str | None = 'b3e8c2d1f4a6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'warehouse_stocks',
        sa.Column('expiry_date', sa.Date(), nullable=True, comment='批次效期（入库登记时录入，随入库更新）'),
        schema='warehouse',
    )


def downgrade() -> None:
    op.drop_column('warehouse_stocks', 'expiry_date', schema='warehouse')
