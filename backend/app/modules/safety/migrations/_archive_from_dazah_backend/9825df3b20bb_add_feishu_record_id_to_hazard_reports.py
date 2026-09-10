"""add feishu_record_id to hazard_reports

Revision ID: 9825df3b20bb
Revises: 68024feea3d7
Create Date: 2026-06-17 15:19:28.582787
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9825df3b20bb'
down_revision: Union[str, None] = '68024feea3d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'hazard_reports',
        sa.Column(
            'feishu_record_id',
            sa.String(length=64),
            nullable=True,
            comment='飞书多维表格记录 ID，双向同步关联',
        ),
        schema='safety',
    )


def downgrade() -> None:
    op.drop_column('hazard_reports', 'feishu_record_id', schema='safety')
