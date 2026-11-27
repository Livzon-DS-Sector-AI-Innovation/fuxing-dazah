"""quality add stocktake anomaly_count

Revision ID: 52e2fb013544
Revises: 82d08bacd627
Create Date: 2026-10-12 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '52e2fb013544'
down_revision: Union[str, None] = '82d08bacd627'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('quality_stocktake_sheets', sa.Column('anomaly_count', sa.Integer(), nullable=False, server_default='0', comment='异常（扫到系统不存在的容器号，疑似贴错/外购未赋码）'), schema='quality')


def downgrade() -> None:
    op.drop_column('quality_stocktake_sheets', 'anomaly_count', schema='quality')
