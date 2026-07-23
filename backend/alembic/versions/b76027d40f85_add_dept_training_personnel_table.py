"""add dept_training_personnel table

Revision ID: b76027d40f85
Revises: 62e7d3bdee64
Create Date: 2026-07-22 18:25:14.870316
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b76027d40f85'
down_revision: Union[str, None] = '62e7d3bdee64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dept_training_personnel",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("display_department", sa.String(128), nullable=False, comment="体现部门"),
        sa.Column("variety", sa.String(64), nullable=True, comment="品种"),
        sa.Column("department", sa.String(128), nullable=False, comment="部门"),
        sa.Column("training_admin", sa.String(256), nullable=True, comment="培训管理员"),
        sa.Column("department_head", sa.String(64), nullable=True, comment="部门负责人"),
        sa.Column("level1_trainer", sa.String(64), nullable=True, comment="一级培训师"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        schema="hr",
    )
    op.create_index("ix_dtp_department", "dept_training_personnel", ["department"], unique=False, schema="hr")
    op.create_index("ix_dtp_display_department", "dept_training_personnel", ["display_department"], unique=False, schema="hr")


def downgrade() -> None:
    op.drop_table("dept_training_personnel", schema="hr")
