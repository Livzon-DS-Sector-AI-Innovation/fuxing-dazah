"""add is_level1 and admin to trainers

Revision ID: 18fda41cfdd1
Revises: c3e4ebb6a363
Create Date: 2026-07-13 12:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '18fda41cfdd1'
down_revision: Union[str, None] = 'c3e4ebb6a363'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE hr.trainers ADD COLUMN IF NOT EXISTS is_level1 VARCHAR(16)")
    op.execute("ALTER TABLE hr.trainers ADD COLUMN IF NOT EXISTS admin VARCHAR(64)")


def downgrade() -> None:
    op.execute("ALTER TABLE hr.trainers DROP COLUMN IF EXISTS admin")
    op.execute("ALTER TABLE hr.trainers DROP COLUMN IF EXISTS is_level1")
