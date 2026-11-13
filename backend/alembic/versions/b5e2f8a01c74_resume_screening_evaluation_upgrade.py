"""hr: AI 简历筛选评价体系升级（对齐飞书 AI 直聘筛选表）。

新增：核心评价一句话 / 人才分类 A-B-C / 候选人信息卡片结构化解析 /
四组能力维度逐项论述 / 拼装完成的候选人匹配度报告全文。
score_table 行内 group 字段随 JSON 列自携带，无需改库。

Revision ID: b5e2f8a01c74
Revises: c3f8a1d94b02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b5e2f8a01c74"
down_revision: str | None = "c3f8a1d94b02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "resume_screening_results"
_SCHEMA = "hr"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column("core_evaluation", sa.String(512), nullable=True,
                  comment="核心评价一句话：优势+但书+待确认点（对齐 AI 直聘表）"),
        schema=_SCHEMA,
    )
    op.add_column(
        _TABLE,
        sa.Column("talent_category", sa.String(2), nullable=True,
                  comment="人才分类：A-关键人才/B-潜力人才/C-普通简历"),
        schema=_SCHEMA,
    )
    op.add_column(
        _TABLE,
        sa.Column("candidate_profile", sa.JSON(), nullable=True,
                  comment="候选人信息卡片（AI 结构化解析）"),
        schema=_SCHEMA,
    )
    op.add_column(
        _TABLE,
        sa.Column("dimension_assessment", sa.JSON(), nullable=True,
                  comment="能力维度评估：{组: [{label, text}]}，四组固定（专业能力/基础匹配/发展潜力/软实力）"),
        schema=_SCHEMA,
    )
    op.add_column(
        _TABLE,
        sa.Column("match_report", sa.Text(), nullable=True,
                  comment="候选人匹配度报告全文（结构化字段拼装，可直接转发）"),
        schema=_SCHEMA,
    )
    op.add_column(
        _TABLE,
        sa.Column("candidate_id", sa.Uuid(), nullable=True,
                  comment="关联的候选人（岗位侧直接初筛时回写）"),
        schema=_SCHEMA,
    )
    op.create_index("ix_rsr_candidate", _TABLE, ["candidate_id"], schema=_SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_rsr_candidate", table_name=_TABLE, schema=_SCHEMA)
    op.drop_column(_TABLE, "candidate_id", schema=_SCHEMA)
    op.drop_column(_TABLE, "match_report", schema=_SCHEMA)
    op.drop_column(_TABLE, "dimension_assessment", schema=_SCHEMA)
    op.drop_column(_TABLE, "candidate_profile", schema=_SCHEMA)
    op.drop_column(_TABLE, "talent_category", schema=_SCHEMA)
    op.drop_column(_TABLE, "core_evaluation", schema=_SCHEMA)
