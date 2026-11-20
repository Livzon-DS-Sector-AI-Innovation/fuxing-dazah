"""permission role group feishu department

Revision ID: 38854a399971
Revises: 3255fabca2f6
Create Date: 2026-11-16 10:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '38854a399971'
down_revision: str | None = '3255fabca2f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 角色展示分组：挂到飞书部门（identity.departments.feishu_department_id），NULL=未分组
    op.add_column(
        "roles",
        sa.Column("group_feishu_department_id", sa.String(length=64), nullable=True,
                  comment="展示分组：飞书部门 open_department_id，NULL=未分组"),
        schema="permission",
    )


def downgrade() -> None:
    op.drop_column("roles", "group_feishu_department_id", schema="permission")
