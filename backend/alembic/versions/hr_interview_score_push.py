"""hr: 面试官评分卡推送记录（interviews 加两列）。

面试安排/逐字稿上传后，HR 可将评分表单卡私发给面试官本人，
面试官在飞书内提交四维打分+结论，回调直接 upsert 人工面试评价。
score_push_open_id 同时作为回调防代填依据（提交者 open_id 必须一致）。

Revision ID: hr_iv_score_push_001
Revises: a7c3d91e4f20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "hr_iv_score_push_001"
down_revision: str | None = "a7c3d91e4f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS hr")
    op.add_column(
        "interviews",
        sa.Column("score_push_open_id", sa.String(64), nullable=True, comment="最近一次评分卡推送的面试官 open_id"),
        schema="hr",
    )
    op.add_column(
        "interviews",
        sa.Column("score_pushed_at", sa.DateTime(timezone=True), nullable=True, comment="最近一次评分卡推送时间"),
        schema="hr",
    )


def downgrade() -> None:
    op.drop_column("interviews", "score_pushed_at", schema="hr")
    op.drop_column("interviews", "score_push_open_id", schema="hr")
