"""warehouse P1 seeds: low_stock_alert push task + sales_target_monthly
runtime key

二期 P1 缺口补齐（2026-09-22，总文档成品⑤/原辅料⑤）：
- 播种推送任务 low_stock_alert（每日 08:10 低库存预警，本地镜像口径）；
- 播种运行参数 sales_target_monthly（默认空；发货分析预设销量对比数据源，
  配置中心运行参数 Tab 录入 JSON）。
两行均从代码注册表单向导出过滤（禁止手抄，防双份常量漂移）。

Revision ID: c5a9d3e7f1b2
Revises: a9d4e7f2c6b8
Create Date: 2026-09-22
"""
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# registry 单向导出播种
from app.modules.warehouse.ops_config import runtime_registry
from app.modules.warehouse.push_center import registry as push_registry

# revision identifiers, used by Alembic.
revision: str = 'c5a9d3e7f1b2'
down_revision: str | None = 'a9d4e7f2c6b8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

P1_PUSH_TASKS = (
    "low_stock_alert",
)
P1_RUNTIME_KEYS = (
    "sales_target_monthly",
)


def _base_columns() -> list[sa.Column]:
    return [
        sa.column('id', sa.Uuid()),
        sa.column('is_deleted', sa.Boolean()),
        sa.column('created_at', sa.DateTime(timezone=True)),
        sa.column('updated_at', sa.DateTime(timezone=True)),
    ]


def upgrade() -> None:
    now = datetime.now(UTC)

    task_rows = sa.table(
        'push_tasks',
        *_base_columns(),
        sa.column('task_name', sa.String(64)),
        sa.column('enabled', sa.Boolean()),
        sa.column('schedule', postgresql.JSONB()),
        sa.column('targets', sa.String(512)),
        schema='warehouse',
    )
    op.bulk_insert(task_rows, [
        {"id": uuid4(), "task_name": info.task_name, "enabled": True,
         "schedule": info.default_schedule, "targets": None,
         "is_deleted": False, "created_at": now, "updated_at": now}
        for info in push_registry.iter_tasks() if info.task_name in P1_PUSH_TASKS
    ])

    runtime_rows = sa.table(
        'runtime_configs',
        *_base_columns(),
        sa.column('key', sa.String(64)),
        sa.column('value', postgresql.JSONB()),
        schema='warehouse',
    )
    op.bulk_insert(runtime_rows, [
        {"id": uuid4(), "key": info.key, "value": info.default,
         "is_deleted": False, "created_at": now, "updated_at": now}
        for info in runtime_registry.iter_runtime_keys()
        if info.key in P1_RUNTIME_KEYS
    ])


def downgrade() -> None:
    op.execute(
        "DELETE FROM warehouse.runtime_configs WHERE key = 'sales_target_monthly'"
    )
    op.execute(
        "DELETE FROM warehouse.push_tasks WHERE task_name = 'low_stock_alert'"
    )
