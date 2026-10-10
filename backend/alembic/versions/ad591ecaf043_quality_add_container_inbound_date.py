"""quality add container inbound_date

Revision ID: ad591ecaf043
Revises: 01fb7635be41
Create Date: 2026-10-10 15:40:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'ad591ecaf043'
down_revision: Union[str, None] = '01fb7635be41'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('quality_material_containers', sa.Column('inbound_date', sa.String(length=32), nullable=True, comment='入库登记日期 YYYY-MM-DD（入库动作自动记录）'), schema='quality')


def downgrade() -> None:
    op.drop_column('quality_material_containers', 'inbound_date', schema='quality')
