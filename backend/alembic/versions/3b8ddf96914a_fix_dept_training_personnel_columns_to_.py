"""fix dept_training_personnel columns to match running code

Revision ID: 3b8ddf96914a
Revises: fdeefc1a1adf
Create Date: 2026-07-22 20:07:55.262213
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3b8ddf96914a'
down_revision: Union[str, None] = 'fdeefc1a1adf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 删旧表重建，匹配运行中代码的列名
    op.execute("DROP TABLE IF EXISTS hr.dept_training_personnel")
    op.create_table(
        "dept_training_personnel",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("display_department", sa.String(128), nullable=True),
        sa.Column("variety", sa.String(128), nullable=True),
        sa.Column("department", sa.String(128), nullable=True),
        sa.Column("training_admin", sa.Text(), nullable=True),
        sa.Column("department_head", sa.Text(), nullable=True),
        sa.Column("level1_trainer", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
        schema="hr",
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hr.dept_training_personnel")
    op.create_table(
        "dept_training_personnel",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("display_dept", sa.String(128), nullable=True),
        sa.Column("department", sa.String(128), nullable=True),
        sa.Column("admins", sa.Text(), nullable=True),
        sa.Column("dept_head", sa.Text(), nullable=True),
        sa.Column("primary_trainer", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
        schema="hr",
    )
