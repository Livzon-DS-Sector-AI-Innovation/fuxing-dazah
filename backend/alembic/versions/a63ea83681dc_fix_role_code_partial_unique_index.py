"""fix: convert permission.roles.code unique constraint to partial index for soft-delete

将 permission.roles.code 的唯一约束改为部分唯一索引 (WHERE is_deleted = false),
支持软删除后重用角色编码。

Revision ID: a63ea83681dc
Revises: 43c93cf55450
Create Date: 2026-07-30 19:57:09.342203
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a63ea83681dc"
down_revision: str | None = "43c93cf55450"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_permission_roles_code", "roles",
        schema="permission", type_="unique",
    )
    op.create_index(
        "uq_permission_roles_code",
        "roles",
        ["code"],
        unique=True,
        schema="permission",
        postgresql_where=sa.text("is_deleted = false"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_permission_roles_code",
        table_name="roles",
        schema="permission",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_unique_constraint(
        "uq_permission_roles_code", "roles", ["code"],
        schema="permission",
    )
