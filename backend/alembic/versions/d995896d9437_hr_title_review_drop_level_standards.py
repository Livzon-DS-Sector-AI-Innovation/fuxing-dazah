"""hr title review drop level standards

Revision ID: d995896d9437
Revises: 66fdc84a6341
Create Date: 2026-08-24 11:15:02.467402
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd995896d9437'
down_revision: str | None = '66fdc84a6341'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 仅职称评审模块：职级组删除评审标准文本与终审标记（v3 取消，只保留序列+职级名）
    for column in (
        'need_final_review',
        'review_points',
        'ability_requirements',
        'basic_conditions',
        'remark',
        'achievement_requirements',
    ):
        op.drop_column('title_review_levels', column, schema='hr')


def downgrade() -> None:
    op.add_column('title_review_levels', sa.Column('need_final_review', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False, comment='是否需要终审（分管领导）'), schema='hr')
    op.add_column('title_review_levels', sa.Column('review_points', sa.TEXT(), autoincrement=False, nullable=True, comment='评审要点'), schema='hr')
    op.add_column('title_review_levels', sa.Column('ability_requirements', sa.TEXT(), autoincrement=False, nullable=True, comment='专业能力要求'), schema='hr')
    op.add_column('title_review_levels', sa.Column('basic_conditions', sa.TEXT(), autoincrement=False, nullable=True, comment='基本条件'), schema='hr')
    op.add_column('title_review_levels', sa.Column('remark', sa.TEXT(), autoincrement=False, nullable=True, comment='备注说明'), schema='hr')
    op.add_column('title_review_levels', sa.Column('achievement_requirements', sa.TEXT(), autoincrement=False, nullable=True, comment='业绩成果要求'), schema='hr')
