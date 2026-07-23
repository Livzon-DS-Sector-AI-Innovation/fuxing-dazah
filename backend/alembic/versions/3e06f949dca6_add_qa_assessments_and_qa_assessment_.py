"""add qa_assessments and qa_assessment_scores tables

Revision ID: 3e06f949dca6
Revises: 99581c9282e4
Create Date: 2026-07-23 01:54:30.492350
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3e06f949dca6'
down_revision: Union[str, None] = '99581c9282e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS hr")
    op.create_table(
        "qa_assessments",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("subject", sa.String(256), nullable=False),
        sa.Column("department", sa.String(128), nullable=True),
        sa.Column("training_date", sa.Date(), nullable=True),
        sa.Column("training_method", sa.String(32), nullable=True),
        sa.Column("assessment_method", sa.String(16), nullable=False, server_default="问答"),
        sa.Column("trainer", sa.String(128), nullable=True),
        sa.Column("questions", sa.JSON(), nullable=True, comment="题目快照"),
        sa.Column("question_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("full_score", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("excellent_line", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("pass_line", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("trainee_names", sa.JSON(), nullable=True, comment="受训人员名单"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
        schema="hr",
    )
    op.create_table(
        "qa_assessment_scores",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("employee_name", sa.String(64), nullable=False),
        sa.Column("employee_number", sa.String(32), nullable=True),
        sa.Column("wrong_questions", sa.JSON(), nullable=True, comment="错题索引"),
        sa.Column("total_score", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("grade", sa.String(16), nullable=True),
        sa.Column("result_text", sa.String(16), nullable=True),
        sa.Column("assessed_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
        schema="hr",
    )


def downgrade() -> None:
    op.drop_table("qa_assessment_scores", schema="hr")
    op.drop_table("qa_assessments", schema="hr")
