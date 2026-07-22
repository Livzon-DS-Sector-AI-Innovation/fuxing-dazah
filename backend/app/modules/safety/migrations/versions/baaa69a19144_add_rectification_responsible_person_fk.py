"""add rectification_responsible_person FK to identity.users

Revision ID: baaa69a19144
Revises: f7f9067c9bbe
Create Date: 2026-06-22

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "baaa69a19144"
down_revision: str | None = "f7f9067c9bbe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "hazard_reports",
        sa.Column(
            "rectification_responsible_person",
            sa.UUID(as_uuid=True),
            nullable=True,
            comment="整改责任人（FK → identity.users）",
        ),
        schema="safety",
    )


def downgrade() -> None:
    op.drop_column("hazard_reports", "rectification_responsible_person", schema="safety")
