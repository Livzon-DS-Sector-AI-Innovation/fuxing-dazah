"""warehouse phase D seeds: env connections, push tasks, runtime key

分期D（分析补全+生产切换准备，设计 §3.3/§4.4/§4.5/§4.8）：
- 建 warehouse.bitable_env_connections（表级坐标环境维度：test/prod 双组）；
- 播种 7 个推送任务行（registry 单向导出过滤）；
- 播种 bitable_connections 行 ×4（分期D 新注册成品侧四表——不播种则
  live「播种行数=注册表数」断言不一致，分期C supplier_directory 先例）；
- 播种 bitable_env_connections test 组行（全部注册表，坐标=既有连接行
  等价语义：base_token 空、table_id=代码快照默认）；
- 播种运行参数 bitable_env_mode（默认 test）。

Revision ID: f8a3c1d5b7e9
Revises: e7b2d9f4a6c1
Create Date: 2026-09-21
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
revision: str = 'f8a3c1d5b7e9'
down_revision: str | None = 'e7b2d9f4a6c1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 分期D 新增推送任务
PHASE_D_PUSH_TASKS = (
    "finished_daily_summary",
    "invoice_four_state",
    "finished_disposition_lists",
    "shipment_analysis",
    "material_usage_compare",
    "workshop_weekly_usage",
    "annual_report",
)
# 分期D 新注册的 Bitable 表（需补 bitable_connections 播种行）
PHASE_D_TABLES = (
    "daily_sales_summary",
    "finished_receipt",
    "finished_returns",
    "finished_unqualified",
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

    # ① 环境坐标表
    op.create_table(
        'bitable_env_connections',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('table_key', sa.String(64), nullable=False, comment='表 key（bitable_schema.TABLES 注册）'),
        sa.Column('env', sa.String(16), nullable=False, comment='环境: test 测试版 / prod 生产版'),
        sa.Column('base_token', sa.String(128), nullable=True, comment='Base app_token 覆盖（空 = 回落既有连接行/env/快照）'),
        sa.Column('table_id', sa.String(64), nullable=True, comment='表 table_id 覆盖（空 = 回落既有连接行/代码快照）'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true', comment='是否启用（false = 该环境显式停用该表）'),
        sa.Column('note', sa.String(255), nullable=True, comment='备注'),
        sa.Column('created_by', sa.Uuid(), sa.ForeignKey('identity.users.id'), nullable=True),
        sa.Column('updated_by', sa.Uuid(), sa.ForeignKey('identity.users.id'), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Index(
            'uq_warehouse_bitable_env_connections_key',
            'table_key', 'env', unique=True,
            postgresql_where=sa.text('is_deleted = false'),
        ),
        sa.Index('ix_warehouse_bitable_env_connections_table_key', 'table_key'),
        schema='warehouse',
    )

    # ② 分期D 新推送任务行
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
        for info in push_registry.iter_tasks() if info.task_name in PHASE_D_PUSH_TASKS
    ])

    # ③ 分期D 新表连接行（既有机制，测试版坐标=快照默认）
    connection_rows = sa.table(
        'bitable_connections',
        *_base_columns(),
        sa.column('table_key', sa.String(64)),
        sa.column('base_token', sa.String(128)),
        sa.column('table_id', sa.String(64)),
        sa.column('enabled', sa.Boolean()),
        schema='warehouse',
    )
    op.bulk_insert(connection_rows, [
        {"id": uuid4(), "table_key": info.table_key, "base_token": None,
         "table_id": info.default_table_id, "enabled": True,
         "is_deleted": False, "created_at": now, "updated_at": now}
        for info in bitable_config.registry.iter_connections()
        if info.table_key in PHASE_D_TABLES
    ])

    # ④ test 组环境行（全部注册表；与既有连接行等价语义）
    env_rows = sa.table(
        'bitable_env_connections',
        *_base_columns(),
        sa.column('table_key', sa.String(64)),
        sa.column('env', sa.String(16)),
        sa.column('base_token', sa.String(128)),
        sa.column('table_id', sa.String(64)),
        sa.column('enabled', sa.Boolean()),
        schema='warehouse',
    )
    op.bulk_insert(env_rows, [
        {"id": uuid4(), "table_key": info.table_key, "env": "test",
         "base_token": None, "table_id": None, "enabled": True,
         "is_deleted": False, "created_at": now, "updated_at": now}
        for info in bitable_config.registry.iter_connections()
    ])

    # ⑤ 运行参数：环境模式（默认 test）
    runtime_rows = sa.table(
        'runtime_configs',
        *_base_columns(),
        sa.column('key', sa.String(64)),
        sa.column('value', postgresql.JSONB()),
        schema='warehouse',
    )
    op.bulk_insert(runtime_rows, [
        {"id": uuid4(), "key": "bitable_env_mode", "value": "test",
         "is_deleted": False, "created_at": now, "updated_at": now}
    ])


def downgrade() -> None:
    op.execute("DELETE FROM warehouse.runtime_configs WHERE key = 'bitable_env_mode'")
    op.execute("DELETE FROM warehouse.bitable_env_connections")
    op.execute(
        "DELETE FROM warehouse.bitable_connections WHERE table_key IN "
        "('daily_sales_summary', 'finished_receipt', 'finished_returns', 'finished_unqualified')"
    )
    op.execute(
        "DELETE FROM warehouse.push_tasks WHERE task_name IN "
        "('finished_daily_summary', 'invoice_four_state', 'finished_disposition_lists', "
        "'shipment_analysis', 'material_usage_compare', 'workshop_weekly_usage', 'annual_report')"
    )
    op.drop_table('bitable_env_connections', schema='warehouse')
