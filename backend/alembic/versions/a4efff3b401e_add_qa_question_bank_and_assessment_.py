"""add_qa_question_bank_and_assessment_tables

Revision ID: a4efff3b401e
Revises: 0dd6e73589c0
Create Date: 2026-08-13 11:48:57.004406

补充 hr.question_bank / hr.qa_assessments / hr.qa_assessment_scores 三张表的迁移。
开发库中这三张表已手工存在，因此使用 IF NOT EXISTS 保证幂等；
全新环境按本迁移建表。
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'a4efff3b401e'
down_revision: Union[str, None] = '0dd6e73589c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS hr")

    # ── 共享题库 ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS hr.question_bank (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            file_no varchar(128),
            question text NOT NULL,
            answer text,
            score integer DEFAULT 10,
            source varchar(64),
            subject varchar(256),
            usage_count integer NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            created_by uuid,
            updated_by uuid,
            is_deleted boolean NOT NULL DEFAULT false
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_question_bank_file_no ON hr.question_bank (file_no)")

    # ── 问答考核场次 ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS hr.qa_assessments (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            subject varchar(256) NOT NULL,
            department varchar(128),
            training_date date,
            training_method varchar(64),
            assessment_method varchar(32),
            trainer varchar(64),
            questions json,
            question_count integer NOT NULL DEFAULT 0,
            full_score integer NOT NULL DEFAULT 100,
            excellent_line integer NOT NULL DEFAULT 90,
            pass_line integer NOT NULL DEFAULT 80,
            trainee_names json,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            created_by uuid,
            updated_by uuid,
            is_deleted boolean NOT NULL DEFAULT false
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_qa_assessments_department ON hr.qa_assessments (department)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_qa_assessments_subject ON hr.qa_assessments (subject)")

    # ── 问答考核成绩 ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS hr.qa_assessment_scores (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            assessment_id uuid NOT NULL,
            employee_name varchar(64) NOT NULL,
            employee_number varchar(32),
            wrong_questions json,
            total_score integer NOT NULL DEFAULT 100,
            grade varchar(16),
            result_text varchar(16),
            assessed_date date,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            created_by uuid,
            updated_by uuid,
            is_deleted boolean NOT NULL DEFAULT false
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_qa_scores_assessment ON hr.qa_assessment_scores (assessment_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_qa_scores_employee ON hr.qa_assessment_scores (employee_name)")

    # 存量手工建表（开发库）可能缺少审计列，幂等补齐，保证与 ORM 模型一致
    for table in ("hr.question_bank", "hr.qa_assessments", "hr.qa_assessment_scores"):
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS created_by uuid")
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS updated_by uuid")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hr.qa_assessment_scores")
    op.execute("DROP TABLE IF EXISTS hr.qa_assessments")
    op.execute("DROP TABLE IF EXISTS hr.question_bank")
