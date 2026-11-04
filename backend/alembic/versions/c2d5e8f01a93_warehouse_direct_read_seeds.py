"""warehouse: 播种直读开关与缓存 TTL 运行参数（直读改造 2026-11-04）

Revision ID: c2d5e8f01a93
Revises: a3f8c2d91e47
Create Date: 2026-11-04
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c2d5e8f01a93"
down_revision = "a3f8c2d91e47"
branch_labels = None
depends_on = None

_KEYS = [
    ("warehouse_direct_read_enabled", "1"),      # 默认直读（用户拍板路线）
    ("warehouse_direct_cache_ttl_seconds", 300),
]


def upgrade() -> None:
    op.execute(
        postgresql.insert(
            sa.table(
                "runtime_configs",
                sa.column("id", postgresql.UUID()),
                sa.column("key", sa.String(64)),
                sa.column("value", postgresql.JSONB()),
                sa.column("is_deleted", sa.Boolean()),
                sa.column("created_at", sa.DateTime()),
                sa.column("updated_at", sa.DateTime()),
                schema="warehouse",
            )
        ).values(
            [
                {
                    "id": uuid.uuid4(),
                    "key": key,
                    "value": value,
                    "is_deleted": False,
                    "created_at": sa.func.now(),
                    "updated_at": sa.func.now(),
                }
                for key, value in _KEYS
            ]
        ).on_conflict_do_nothing()
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM warehouse.runtime_configs "
        "WHERE key IN ('warehouse_direct_read_enabled', "
        "'warehouse_direct_cache_ttl_seconds')"
    )
