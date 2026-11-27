"""quality add shift teams

Revision ID: eb083fd428c6
Revises: fbd83416e8e7
Create Date: 2026-10-28 17:54:16.881007
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'eb083fd428c6'
down_revision: str | None = 'fbd83416e8e7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS quality")
    op.create_table(
        "quality_shift_teams",
        sa.Column("name", sa.String(length=64), nullable=False, comment="班组名"),
        sa.Column("member_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment="班组成员（identity.users.id 字符串列表）"),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0", comment="排序（轮换顺序按 seq）"),
        sa.Column("remark", sa.String(length=200), nullable=True, comment="备注"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"], ),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"], ),
        sa.PrimaryKeyConstraint("id"),
        schema="quality",
    )
    op.create_index("ix_quality_shift_team_seq", "quality_shift_teams", ["seq"], unique=False, schema="quality")
    op.create_table(
        "quality_shift_configs",
        sa.Column("key", sa.String(length=32), nullable=False, comment="配置键（rotation）"),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment="{start_date, period_days, duty_teams}"),
        sa.Column("remark", sa.String(length=200), nullable=True, comment="备注"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"], ),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"], ),
        sa.PrimaryKeyConstraint("id"),
        schema="quality",
    )
    op.create_index(
        "uq_quality_shift_config_key", "quality_shift_configs", ["key"],
        unique=True, schema="quality", postgresql_where=sa.text("is_deleted = false"),
    )


def downgrade() -> None:
    op.drop_index("uq_quality_shift_config_key", table_name="quality_shift_configs", schema="quality")
    op.drop_table("quality_shift_configs", schema="quality")
    op.drop_index("ix_quality_shift_team_seq", table_name="quality_shift_teams", schema="quality")
    op.drop_table("quality_shift_teams", schema="quality")
