"""quality add task assignments

Revision ID: 54b731ca811d
Revises: 5fca5b3a3da7
Create Date: 2026-10-28 15:46:02.532907
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '54b731ca811d'
down_revision: str | None = '5fca5b3a3da7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS quality")
    op.create_table(
        "quality_task_assignments",
        sa.Column("task_id", sa.Uuid(), nullable=False, comment="检验任务（逻辑引用）"),
        sa.Column("sop_no", sa.String(length=100), nullable=False, comment="SOP 号"),
        sa.Column("assignee_id", sa.Uuid(), nullable=False, comment="负责人，逻辑引用 identity.users.id"),
        sa.Column("assigned_by", sa.Uuid(), nullable=True, comment="排班人"),
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
    op.create_index("ix_quality_assign_task", "quality_task_assignments", ["task_id"], unique=False, schema="quality")
    op.create_index(
        "uq_quality_assign_task_sop", "quality_task_assignments", ["task_id", "sop_no"],
        unique=True, schema="quality", postgresql_where=sa.text("is_deleted = false"),
    )


def downgrade() -> None:
    op.drop_index("uq_quality_assign_task_sop", table_name="quality_task_assignments", schema="quality")
    op.drop_index("ix_quality_assign_task", table_name="quality_task_assignments", schema="quality")
    op.drop_table("quality_task_assignments", schema="quality")
