"""add regulation_id and regulation_name to hazard_identifications

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-06-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'hazard_identifications',
        sa.Column('regulation_id', sa.Uuid(), nullable=True, comment='引用的安全操作规程 ID（替代附件上传）'),
        schema='safety',
    )
    op.add_column(
        'hazard_identifications',
        sa.Column('regulation_name', sa.String(255), nullable=True, comment='引用的安全操作规程名称'),
        schema='safety',
    )


def downgrade() -> None:
    op.drop_column('hazard_identifications', 'regulation_name', schema='safety')
    op.drop_column('hazard_identifications', 'regulation_id', schema='safety')
