"""plan_change_logs 计划单变更日志表

Revision ID: 1388bb526703
Revises: a63ea83681dc
Create Date: 2026-07-31 10:25:26.356777
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1388bb526703"
down_revision: str | None = "a63ea83681dc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plan_change_logs",
        sa.Column("plan_order_id", sa.Uuid(), nullable=False, comment="关联计划单"),
        sa.Column("plan_version", sa.Integer(), nullable=False, comment="变更后的版本号"),
        sa.Column("change_reason", sa.Text(), nullable=False, comment="变更原因"),
        sa.Column("changed_by", sa.Uuid(), nullable=True, comment="变更人"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="production",
    )
    op.create_index(
        "ix_production_plan_change_logs_order",
        "plan_change_logs",
        ["plan_order_id", "plan_version"],
        unique=False,
        schema="production",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_production_plan_change_logs_order",
        table_name="plan_change_logs",
        schema="production",
    )
    op.drop_table("plan_change_logs", schema="production")
