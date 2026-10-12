"""quality add material valid_months

Revision ID: c6648fa4d9d0
Revises: ad591ecaf043
Create Date: 2026-10-12 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c6648fa4d9d0'
down_revision: Union[str, None] = 'ad591ecaf043'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('quality_materials', sa.Column('valid_months', sa.Integer(), nullable=True, comment='效期月数（赋码时自动计算复验期=入库日期+N月，可手改）'), schema='quality')


def downgrade() -> None:
    op.drop_column('quality_materials', 'valid_months', schema='quality')
