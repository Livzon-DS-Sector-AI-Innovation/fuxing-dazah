"""add training_evaluations table

Revision ID: 20fda41cfdd3
Revises: 19fda41cfdd2
Create Date: 2026-07-13 18:30:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = '20fda41cfdd3'
down_revision: Union[str, None] = '19fda41cfdd2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS hr.training_evaluations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            training_content TEXT,
            training_date DATE,
            trainer TEXT,
            department TEXT,
            training_method VARCHAR(64),
            trainer_name VARCHAR(128),
            assessment_method VARCHAR(64),
            expected_count INT DEFAULT 0,
            actual_count INT DEFAULT 0,
            excellent_count INT DEFAULT 0,
            qualified_count INT DEFAULT 0,
            unqualified_count INT DEFAULT 0,
            is_deleted BOOLEAN DEFAULT false,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hr.training_evaluations")
