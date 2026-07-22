"""add departments table

Revision ID: 7bf26efe0801
Revises: ba23d2002af6
Create Date: 2026-07-07 08:36:50.697634
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7bf26efe0801'
down_revision: Union[str, None] = 'ba23d2002af6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS meter")
    op.create_table(
        "departments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False, comment="instrument / gas_detector"),
        sa.Column("name", sa.String(length=200), nullable=False, comment="部门名称"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema="meter",
    )
    op.create_index("ix_departments_source", "departments", ["source"], schema="meter")
    op.execute(
        "CREATE UNIQUE INDEX ix_departments_source_name_active "
        "ON meter.departments (source, name) WHERE is_deleted = false"
    )


def downgrade() -> None:
    op.drop_table("departments", schema="meter")
