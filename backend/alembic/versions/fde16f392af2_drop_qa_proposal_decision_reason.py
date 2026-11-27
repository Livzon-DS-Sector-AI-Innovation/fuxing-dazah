"""drop qa proposal decision reason.

拒绝主数据提案改为直接软删除，提案箱不再收集和保留拒绝原因。

Revision ID: fde16f392af2
Revises: qa_ai_native_pipeline_001
Create Date: 2026-09-21 11:32:13.524534
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fde16f392af2"
down_revision: str | None = "qa_ai_native_pipeline_001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("master_object_proposals", "decision_reason", schema="qa")


def downgrade() -> None:
    op.add_column(
        "master_object_proposals",
        sa.Column("decision_reason", sa.TEXT(), autoincrement=False, nullable=True),
        schema="qa",
    )
