"""add_feishu_doc_fields_to_emergency_drill_documents

Revision ID: 97454d0f435a
Revises: 76f673e6ca7b
Create Date: 2026-07-27 09:44:55.741865
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '97454d0f435a'
down_revision: Union[str, None] = '76f673e6ca7b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE safety.emergency_drill_documents "
        "ADD COLUMN IF NOT EXISTS feishu_doc_id VARCHAR(64)"
    )
    op.execute(
        "ALTER TABLE safety.emergency_drill_documents "
        "ADD COLUMN IF NOT EXISTS feishu_doc_url VARCHAR(512)"
    )
    op.execute(
        "ALTER TABLE safety.emergency_drill_documents "
        "ADD COLUMN IF NOT EXISTS feishu_doc_status VARCHAR(16)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_drill_docs_feishu_status "
        "ON safety.emergency_drill_documents (feishu_doc_status)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS safety.idx_drill_docs_feishu_status")
    op.execute("ALTER TABLE safety.emergency_drill_documents DROP COLUMN IF EXISTS feishu_doc_status")
    op.execute("ALTER TABLE safety.emergency_drill_documents DROP COLUMN IF EXISTS feishu_doc_url")
    op.execute("ALTER TABLE safety.emergency_drill_documents DROP COLUMN IF EXISTS feishu_doc_id")
