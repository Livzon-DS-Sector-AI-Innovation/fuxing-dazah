"""quality add sop no to lc template configs

Revision ID: 459df173919d
Revises: 3f8915e11f07
Create Date: 2026-09-09 09:29:33.865747
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '459df173919d'
down_revision: Union[str, None] = '3f8915e11f07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS quality")
    op.add_column('quality_lc_template_configs',
                  sa.Column('sop_no', sa.String(length=64), nullable=True,
                            comment='表号对应的检测 SOP 号（一般 1:1 映射，例外清单另行整理）'),
                  schema='quality')


def downgrade() -> None:
    op.drop_column('quality_lc_template_configs', 'sop_no', schema='quality')
