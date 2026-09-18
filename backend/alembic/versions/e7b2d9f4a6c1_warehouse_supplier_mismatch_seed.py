"""warehouse supplier mismatch alert and connection seed

供应商不一致提醒与名录表连接（V3.0 分期C Ticket 03/04，设计 §4.3）：
- 播种 1 个推送任务行（supplier_mismatch_alert，event 型，registry 单向导出）；
- 播种 1 个 Bitable 连接行（supplier_directory——bitable_schema 新注册表，
  table_id 空占位，Base 建表后经配置中心覆盖；不播种则 live「播种行数=
  注册表数」断言不一致，同分期A runtime 欠账先例）。

Revision ID: e7b2d9f4a6c1
Revises: d1f6b8a4c2e9
Create Date: 2026-09-18
"""
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# registry 单向导出播种（禁止手抄，防双份常量漂移）
from app.modules.warehouse import bitable_config
from app.modules.warehouse.push_center import registry as push_registry

# revision identifiers, used by Alembic.
revision: str = 'e7b2d9f4a6c1'
down_revision: str | None = 'd1f6b8a4c2e9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 分期C 新增推送任务
PHASE_C_PUSH_TASKS = ("supplier_mismatch_alert",)
# 分期C 新增表连接
PHASE_C_TABLES = ("supplier_directory",)


def upgrade() -> None:
    now = datetime.now(UTC)
    task_rows = sa.table(
        'push_tasks',
        sa.column('id', sa.Uuid()), sa.column('task_name', sa.String(64)),
        sa.column('enabled', sa.Boolean()), sa.column('schedule', postgresql.JSONB()),
        sa.column('targets', sa.String(512)),
        sa.column('is_deleted', sa.Boolean()),
        sa.column('created_at', sa.DateTime(timezone=True)),
        sa.column('updated_at', sa.DateTime(timezone=True)),
        schema='warehouse',
    )
    op.bulk_insert(task_rows, [
        {"id": uuid4(), "task_name": info.task_name, "enabled": True,
         "schedule": info.default_schedule, "targets": None,
         "is_deleted": False, "created_at": now, "updated_at": now}
        for info in push_registry.iter_tasks() if info.task_name in PHASE_C_PUSH_TASKS
    ])

    connection_rows = sa.table(
        'bitable_connections',
        sa.column('id', sa.Uuid()), sa.column('table_key', sa.String(64)),
        sa.column('base_token', sa.String(128)), sa.column('table_id', sa.String(64)),
        sa.column('enabled', sa.Boolean()),
        sa.column('is_deleted', sa.Boolean()),
        sa.column('created_at', sa.DateTime(timezone=True)),
        sa.column('updated_at', sa.DateTime(timezone=True)),
        schema='warehouse',
    )
    op.bulk_insert(connection_rows, [
        {"id": uuid4(), "table_key": info.table_key, "base_token": None,
         "table_id": info.default_table_id, "enabled": True,
         "is_deleted": False, "created_at": now, "updated_at": now}
        for info in bitable_config.registry.iter_connections()
        if info.table_key in PHASE_C_TABLES
    ])


def downgrade() -> None:
    op.execute("DELETE FROM warehouse.bitable_connections WHERE table_key IN ('supplier_directory')")
    op.execute("DELETE FROM warehouse.push_tasks WHERE task_name IN ('supplier_mismatch_alert')")
