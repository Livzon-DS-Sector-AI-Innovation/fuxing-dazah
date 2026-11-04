"""warehouse: 播种 agent_submit_enabled 运行参数（生产版只读切换 2026-11-04）

Revision ID: a3f8c2d91e47
Revises: b7c9d1e3f5a2
Create Date: 2026-11-04

新运行参数注册（runtime_registry）后，live 库 runtime_configs 需有对应行
（test_live_system_config.test_seeded_row_counts_match_registries 断言行数
= 注册表长度）。缺省值空串 = 随 bitable_env_mode（prod 拒写 / test 放行）。
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a3f8c2d91e47"
down_revision = "b7c9d1e3f5a2"
branch_labels = None
depends_on = None


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
                    "key": "agent_submit_enabled",
                    "value": "",
                    "is_deleted": False,
                    "created_at": sa.func.now(),
                    "updated_at": sa.func.now(),
                }
            ]
        ).on_conflict_do_nothing()
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM warehouse.runtime_configs WHERE key = 'agent_submit_enabled'"
    )
