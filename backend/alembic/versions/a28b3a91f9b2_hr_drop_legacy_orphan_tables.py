"""hr drop legacy orphan tables

Revision ID: a28b3a91f9b2
Revises: 1405a17f040b
Create Date: 2026-08-25 14:17:55.958079
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a28b3a91f9b2'
down_revision: str | None = '1405a17f040b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 遗留孤儿表：ORM 模型已删除、无任何代码引用、均为 0 行
_ORPHAN_TABLES = [
    "offboarding_applications",
    "onboarding_applications",
    "offer_tokens",
    "probation_extensions",
    "training_assessments",
    "training_assessment_scores",
]


def upgrade() -> None:
    for table in _ORPHAN_TABLES:
        op.execute(f"DROP TABLE IF EXISTS hr.{table}")


def downgrade() -> None:
    # 孤儿表无模型可回建，降级时按空结构重建（占位）
    op.execute(
        "CREATE TABLE IF NOT EXISTS hr.offboarding_applications (id uuid PRIMARY KEY)"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS hr.onboarding_applications (id uuid PRIMARY KEY)"
    )
    op.execute("CREATE TABLE IF NOT EXISTS hr.offer_tokens (id uuid PRIMARY KEY)")
    op.execute(
        "CREATE TABLE IF NOT EXISTS hr.probation_extensions (id uuid PRIMARY KEY)"
    )
    op.execute("CREATE TABLE IF NOT EXISTS hr.training_assessments (id uuid PRIMARY KEY)")
    op.execute(
        "CREATE TABLE IF NOT EXISTS hr.training_assessment_scores (id uuid PRIMARY KEY)"
    )
