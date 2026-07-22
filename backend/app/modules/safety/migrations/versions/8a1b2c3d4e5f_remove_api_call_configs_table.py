"""remove api_call_configs table

Revision ID: 8a1b2c3d4e5f
Revises: d640ce4ef846
Create Date: 2026-06-22 09:21:08.242240
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8a1b2c3d4e5f'
down_revision: Union[str, None] = 'd640ce4ef846'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS safety.api_call_configs CASCADE")


def downgrade() -> None:
    op.create_table(
        "api_call_configs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("config_name", sa.String(128), nullable=False),
        sa.Column("config_type", sa.String(20), server_default="text", nullable=False),
        sa.Column("api_base_url", sa.String(500), nullable=False),
        sa.Column("api_key", sa.String(500), nullable=False),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("temperature", sa.Float(), server_default="0.1", nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), server_default="120", nullable=False),
        sa.Column("max_tokens", sa.Integer(), nullable=True),
        sa.Column("extra_config", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="safety",
    )
