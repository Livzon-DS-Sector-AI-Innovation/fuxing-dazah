"""drop meter ai_config table

Revision ID: ba23d2002af6
Revises: e22654fa1b3c
Create Date: 2026-07-06 16:33:24.728996
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ba23d2002af6'
down_revision: Union[str, None] = 'e22654fa1b3c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS meter.ai_config")


def downgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS meter")
    op.execute("""
        CREATE TABLE IF NOT EXISTS meter.ai_config (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            api_url VARCHAR(500) NOT NULL,
            api_key VARCHAR(500) NOT NULL,
            model VARCHAR(200) NOT NULL DEFAULT 'MiniMax-M2.5',
            is_deleted BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
