"""hr title review application add profile

Revision ID: 66fdc84a6341
Revises: a169a1c2deaa
Create Date: 2026-08-23 23:08:48.987356
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '66fdc84a6341'
down_revision: str | None = 'a169a1c2deaa'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 仅职称评审模块：申报记录增加员工信息表自动带出的个人档案 JSON 列
    op.add_column(
        'title_review_applications',
        sa.Column(
            'profile',
            sa.JSON(),
            nullable=True,
            comment='员工信息表自动带出的个人档案 {学历/司龄/入职日期/性别/职务/岗位职级/毕业院校/专业/目前职级/近5年年终绩效考评结果/2026年最高可申报}',
        ),
        schema='hr',
    )


def downgrade() -> None:
    op.drop_column('title_review_applications', 'profile', schema='hr')
