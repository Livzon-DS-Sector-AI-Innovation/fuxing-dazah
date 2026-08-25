"""hr title review add profile refreshed at

Revision ID: 1405a17f040b
Revises: 9add14ff9b5e
Create Date: 2026-08-25 11:51:53.810159
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '1405a17f040b'
down_revision: str | None = '9add14ff9b5e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 仅职称评审模块：申报记录增加个人档案刷新时间列（对账超过 6 小时自动重拉）
    op.add_column(
        'title_review_applications',
        sa.Column(
            'profile_refreshed_at',
            sa.DateTime(timezone=True),
            nullable=True,
            comment='个人档案最近刷新时间（对账时超过 6 小时自动重拉）',
        ),
        schema='hr',
    )


def downgrade() -> None:
    op.drop_column('title_review_applications', 'profile_refreshed_at', schema='hr')
