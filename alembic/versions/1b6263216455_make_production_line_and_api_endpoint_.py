"""make production_line and api_endpoint optional

Revision ID: 1b6263216455
Revises: 77f1c0c605ba
Create Date: 2026-06-08 10:36:45.032977
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1b6263216455'
down_revision: Union[str, None] = '77f1c0c605ba'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "energy_device_configs",
        "production_line",
        existing_type=sa.String(100),
        nullable=True,
        schema="energy",
    )


def downgrade() -> None:
    op.alter_column(
        "energy_device_configs",
        "production_line",
        existing_type=sa.String(100),
        nullable=False,
        schema="energy",
    )
