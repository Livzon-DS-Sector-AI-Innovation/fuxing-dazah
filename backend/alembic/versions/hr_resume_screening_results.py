"""hr: AI 简历筛选结果表（按岗位需求对 PDF 简历打分排名）。

输出结构对齐培训管理的《岗位适配度分析+复试推荐意见》范例：
优势分析 / 核心硬伤（分节论述）+ 按岗位定制的胜任度打分表 + 最终推荐意见。

Revision ID: hr_resume_screening_001
Revises: 237db0962d16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.schema import SchemaItem

from alembic import op

revision: str = "hr_resume_screening_001"
down_revision: str | None = "237db0962d16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base_columns() -> list[SchemaItem]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
    ]


def upgrade() -> None:
    op.create_table(
        "resume_screening_results",
        *_base_columns(),
        sa.Column("job_requirement_id", sa.Uuid(), nullable=False, comment="筛选时依据的岗位需求"),
        sa.Column("jd_snapshot", sa.Text(), nullable=False, comment="筛选时的岗位要求文本快照"),
        sa.Column("file_name", sa.String(256), nullable=False, comment="简历文件名"),
        sa.Column("resume_file_path", sa.String(512), nullable=True, comment="简历 PDF 存储路径"),
        sa.Column("candidate_name", sa.String(64), nullable=True, comment="AI 从简历中识别的姓名"),
        sa.Column("total_score", sa.Integer(), nullable=False, comment="综合胜任度总分 0-100"),
        sa.Column("recommendation", sa.String(16), nullable=False, comment="推荐档位：推荐/待定/不推荐"),
        # ── 适配度分析报告（对齐范例文档结构）──
        sa.Column("advantages", sa.JSON(), nullable=True, comment="优势分析：[{title, detail}]"),
        sa.Column("flaws", sa.JSON(), nullable=True, comment="核心硬伤：[{title, detail}]"),
        sa.Column("score_table", sa.JSON(), nullable=True, comment="胜任度打分表：[{dimension, score, comment}]（维度按岗位定制）"),
        sa.Column("final_verdict", sa.Text(), nullable=True, comment="最终推荐意见结论（一句话）"),
        sa.Column("final_reasons", sa.JSON(), nullable=True, comment="最终推荐意见支撑理由：[string]"),
        sa.Column("resume_excerpt", sa.Text(), nullable=True, comment="简历全文开头摘录（回看/复筛用）"),
        sa.Column("model_version", sa.String(64), nullable=True, comment="AI 模型版本"),
        sa.Column("created_by_name", sa.String(64), nullable=True, comment="筛选操作人"),
        sa.PrimaryKeyConstraint("id"),
        schema="hr",
    )
    op.create_index("ix_rsr_job_requirement", "resume_screening_results", ["job_requirement_id"], schema="hr")
    op.create_index("ix_rsr_total_score", "resume_screening_results", ["total_score"], schema="hr")


def downgrade() -> None:
    op.drop_index("ix_rsr_total_score", table_name="resume_screening_results", schema="hr")
    op.drop_index("ix_rsr_job_requirement", table_name="resume_screening_results", schema="hr")
    op.drop_table("resume_screening_results", schema="hr")
