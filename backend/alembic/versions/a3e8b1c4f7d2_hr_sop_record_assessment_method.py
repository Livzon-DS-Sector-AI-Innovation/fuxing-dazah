"""SOP 培训登记表新增考核方式（阅读并理解/问答/笔试）

材料包按考核方式组卷：阅读并理解→通知+签到+评估；
问答→通知+签到+问答实操记录+评估；笔试→通知+签到+试卷（有题才含）+评估。
历史数据为空时按培训方式取默认（R=阅读并理解，T=问答）。

Revision ID: a3e8b1c4f7d2
Revises: c5f19a3d7e02
Create Date: 2026-11-26 15:00:00.000000
"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a3e8b1c4f7d2'
down_revision: str | None = 'c5f19a3d7e02'
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        'sop_training_records',
        sa.Column(
            'assessment_method',
            sa.String(length=16),
            nullable=True,
            comment='考核方式：阅读并理解/问答/笔试（空=按培训方式取默认）',
        ),
        schema='hr',
    )


def downgrade() -> None:
    op.drop_column('sop_training_records', 'assessment_method', schema='hr')
