"""warehouse push center tables

推送订阅中心（V3.0 分期A Ticket 01）：推送任务/推送任务审计/推送日志
3 张表 + registry 播种（5 个任务：晨报/周报/月报/清单/快递通知）。

Revision ID: a7c3e9f5b2d8
Revises: l7f3a9b5c8d2
Create Date: 2026-09-17
"""
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# registry 单向导出播种（禁止手抄，防双份常量漂移）
from app.modules.warehouse.push_center import registry as push_registry

# revision identifiers, used by Alembic.
revision: str = 'a7c3e9f5b2d8'
down_revision: str | None = 'l7f3a9b5c8d2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base_columns() -> list[sa.Column]:
    """BaseModel 公共列（与 app/shared/base_model.py 对齐）。"""
    return [
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    ]


def _base_fks() -> list:
    return [
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id']),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id']),
        sa.PrimaryKeyConstraint('id'),
    ]


def upgrade() -> None:
    # ── 推送任务配置 ──
    op.create_table('push_tasks',
        sa.Column('task_name', sa.String(length=64), nullable=False, comment='任务 key（push_center registry 注册，如 morning_report）'),
        sa.Column('enabled', sa.Boolean(), server_default='true', nullable=False, comment='是否启用'),
        sa.Column('schedule', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='调度 daily/weekly/monthly/interval；event 任务为 null；空值=回落 registry 默认'),
        sa.Column('targets', sa.String(length=512), nullable=True, comment='推送目标（逗号分隔群 chat_id/个人 open_id；空 = 回落 env 兜底）'),
        sa.Column('note', sa.String(length=255), nullable=True, comment='备注'),
        *_base_columns(), *_base_fks(),
        schema='warehouse',
    )
    op.create_index('ix_warehouse_push_tasks_task', 'push_tasks', ['task_name'], unique=False, schema='warehouse')
    op.create_index('uq_warehouse_push_tasks_task', 'push_tasks', ['task_name'], unique=True, schema='warehouse', postgresql_where=sa.text('is_deleted = false'))

    op.create_table('push_task_audits',
        sa.Column('task_name', sa.String(length=64), nullable=False, comment='任务 key'),
        sa.Column('action', sa.String(length=32), nullable=False, comment='动作: update/enable/disable'),
        sa.Column('before_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='变更前'),
        sa.Column('after_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='变更后'),
        sa.Column('operator_name', sa.String(length=128), nullable=True, comment='操作人 name'),
        *_base_columns(), *_base_fks(),
        schema='warehouse',
    )
    op.create_index('ix_warehouse_push_task_audits_task_created', 'push_task_audits', ['task_name', 'created_at'], unique=False, schema='warehouse')
    op.create_index('ix_warehouse_push_task_audits_created', 'push_task_audits', ['created_at'], unique=False, schema='warehouse')

    # ── 推送日志（append-only）──
    op.create_table('push_logs',
        sa.Column('task_name', sa.String(length=64), nullable=False, comment='任务 key'),
        sa.Column('scene', sa.String(length=64), nullable=False, comment='内容场景（生成器注册 key）'),
        sa.Column('trigger', sa.String(length=16), nullable=False, comment='触发: scheduled/manual/event'),
        sa.Column('run_at', sa.DateTime(timezone=True), nullable=False, comment='引擎执行时刻（interval 冷却判断基准）'),
        sa.Column('slot', sa.DateTime(timezone=True), nullable=True, comment='计划槽位（日历型调度当日判重；interval/event 为空）'),
        sa.Column('target', sa.String(length=64), nullable=True, comment='目标 chat_id/open_id（无目标跳过行为空）'),
        sa.Column('status', sa.String(length=16), nullable=False, comment='success/failed/skipped'),
        sa.Column('message_id', sa.String(length=64), nullable=True, comment='飞书 message_id（dry_run 为占位值）'),
        sa.Column('error', sa.String(length=512), nullable=True, comment='失败/跳过原因'),
        sa.Column('duration_ms', sa.Integer(), nullable=True, comment='发送耗时毫秒'),
        *_base_columns(), *_base_fks(),
        schema='warehouse',
    )
    op.create_index('ix_warehouse_push_logs_task_slot', 'push_logs', ['task_name', 'slot'], unique=False, schema='warehouse')
    op.create_index('ix_warehouse_push_logs_task_created', 'push_logs', ['task_name', 'created_at'], unique=False, schema='warehouse')
    op.create_index('ix_warehouse_push_logs_created', 'push_logs', ['created_at'], unique=False, schema='warehouse')

    # ── 播种（registry 单向导出；目标默认空 = 回落 env 兜底）──
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
        for info in push_registry.iter_tasks()
    ])


def downgrade() -> None:
    for table in ('push_logs', 'push_task_audits', 'push_tasks'):
        op.drop_table(table, schema='warehouse')
