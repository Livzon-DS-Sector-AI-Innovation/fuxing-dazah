"""add_alert_rule_id_to_workshop_configs

Revision ID: b30b2344705d
Revises: 76aef6b4f6d0
Create Date: 2026-07-27 10:38:23.308231
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b30b2344705d'
down_revision: Union[str, None] = '76aef6b4f6d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE energy.energy_workshop_configs "
        "ADD COLUMN IF NOT EXISTS alert_rule_id UUID"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE energy.energy_workshop_configs "
        "DROP COLUMN IF EXISTS alert_rule_id"
    )
