"""drop table_id from energy_type_configs

Revision ID: a952ff1636f5
Revises: 79faec14363d
Create Date: 2026-07-15 15:09:10.808081
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a952ff1636f5'
down_revision: Union[str, None] = '79faec14363d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE energy.energy_type_configs DROP COLUMN IF EXISTS table_id")


def downgrade() -> None:
    op.execute("ALTER TABLE energy.energy_type_configs ADD COLUMN IF NOT EXISTS table_id VARCHAR(100)")
