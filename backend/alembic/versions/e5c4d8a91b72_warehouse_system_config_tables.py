"""warehouse system config tables

仓库模块系统配置中心：AI 模型/场景配置、AI 调用审计、Bitable 连接、
运行参数、定时任务/告警目标（11 张表）+ registry 播种。

注意：main 合并后本地库与 main 侧迁移链存在既有分叉
（aae52f0e112e 假设 production.batches.product_id 存在，本地未满足），
本迁移只挂接分支侧父节点 c7a1f2b3d4e5；main 链本地落地后需补一个
双头 merge 迁移（仓库已有 0728ff9db81f 先例）。

Revision ID: e5c4d8a91b72
Revises: c7a1f2b3d4e5
Create Date: 2026-09-14
"""
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# registry 单向导出播种（禁止手抄，防双份常量漂移）
from app.modules.warehouse.ai_config import registry as ai_registry
from app.modules.warehouse.ai_config import scenario_registry as ai_scenario_registry
from app.modules.warehouse.bitable_config import registry as bitable_registry
from app.modules.warehouse.ops_config import runtime_registry, scheduler_registry

# revision identifiers, used by Alembic.
revision: str = 'e5c4d8a91b72'
down_revision: str | None = 'c7a1f2b3d4e5'
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
    # ── AI 模型配置 ──
    op.create_table('ai_model_profiles',
        sa.Column('profile', sa.String(length=32), nullable=False, comment='profile key（registry 注册，如 agent/agent_backup）'),
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='模型配置（默认值来自 registry.default_config，api_key 恒为空串不回显）'),
        sa.Column('enabled', sa.Boolean(), server_default='true', nullable=False, comment='是否启用（false 时读路径整行回落 env/registry 默认）'),
        sa.Column('note', sa.String(length=255), nullable=True, comment='备注'),
        *_base_columns(), *_base_fks(),
        schema='warehouse',
    )
    op.create_index('ix_warehouse_ai_model_profiles_profile', 'ai_model_profiles', ['profile'], unique=False, schema='warehouse')
    op.create_index('uq_warehouse_ai_model_profiles_profile', 'ai_model_profiles', ['profile'], unique=True, schema='warehouse', postgresql_where=sa.text('is_deleted = false'))

    op.create_table('ai_config_audits',
        sa.Column('profile', sa.String(length=32), nullable=False, comment='profile key'),
        sa.Column('action', sa.String(length=32), nullable=False, comment='动作: update/enable/disable'),
        sa.Column('before_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='变更前（compact，api_key 已脱敏）'),
        sa.Column('after_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='变更后（compact，api_key 已脱敏）'),
        sa.Column('operator_name', sa.String(length=128), nullable=True, comment='操作人 name'),
        *_base_columns(), *_base_fks(),
        schema='warehouse',
    )
    op.create_index('ix_warehouse_ai_config_audits_profile_created', 'ai_config_audits', ['profile', 'created_at'], unique=False, schema='warehouse')
    op.create_index('ix_warehouse_ai_config_audits_created', 'ai_config_audits', ['created_at'], unique=False, schema='warehouse')

    # ── AI 场景配置 ──
    op.create_table('ai_scenario_configs',
        sa.Column('scenario', sa.String(length=64), nullable=False, comment='场景 key（registry 注册，DB 只能改值不能新增场景）'),
        sa.Column('enabled', sa.Boolean(), server_default='true', nullable=False, comment='是否启用（false = 熔断，统一入口抛 ScenarioDisabledError）'),
        sa.Column('model_profile', sa.String(length=32), nullable=True, comment='绑定 profile 名（agent/agent_backup）；NULL = 按场景默认'),
        sa.Column('note', sa.String(length=255), nullable=True, comment='备注'),
        *_base_columns(), *_base_fks(),
        schema='warehouse',
    )
    op.create_index('ix_warehouse_ai_scenario_configs_scenario', 'ai_scenario_configs', ['scenario'], unique=False, schema='warehouse')
    op.create_index('uq_warehouse_ai_scenario_configs_scenario', 'ai_scenario_configs', ['scenario'], unique=True, schema='warehouse', postgresql_where=sa.text('is_deleted = false'))

    op.create_table('ai_scenario_config_audits',
        sa.Column('scenario', sa.String(length=64), nullable=False, comment='对应场景'),
        sa.Column('action', sa.String(length=32), nullable=False, comment='动作: update/enable/disable'),
        sa.Column('before_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='变更前（compact）'),
        sa.Column('after_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='变更后（compact）'),
        sa.Column('operator_name', sa.String(length=128), nullable=True, comment='操作人 name'),
        *_base_columns(), *_base_fks(),
        schema='warehouse',
    )
    op.create_index('ix_warehouse_ai_scenario_config_audits_scenario_created', 'ai_scenario_config_audits', ['scenario', 'created_at'], unique=False, schema='warehouse')
    op.create_index('ix_warehouse_ai_scenario_config_audits_created', 'ai_scenario_config_audits', ['created_at'], unique=False, schema='warehouse')

    # ── AI 调用审计 ──
    op.create_table('ai_call_audits',
        sa.Column('trace_id', sa.String(length=64), nullable=False, comment='一次 Runner.run / 识别管线的追踪 ID（UUID）'),
        sa.Column('scenario', sa.String(length=64), nullable=False, comment='场景（agent_chat / receipt_recognition）'),
        sa.Column('resource', sa.String(length=64), nullable=True, comment='场景内细分（chat / rotate_detect / receipt_parse）'),
        sa.Column('model', sa.String(length=128), nullable=False, comment='模型名'),
        sa.Column('prompt_version', sa.String(length=16), nullable=True, comment='system 消息 sha256 前 12 位'),
        sa.Column('input_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='请求消息（64K 字符截断 + truncated 标志）'),
        sa.Column('output_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='响应 content + tool_calls（64K 截断）'),
        sa.Column('tool_names', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='本轮模型请求的 tool_calls 名称'),
        sa.Column('status', sa.String(length=16), nullable=False, comment='success / failed'),
        sa.Column('error', sa.Text(), nullable=True, comment='错误摘要'),
        sa.Column('input_tokens', sa.Numeric(12), nullable=True, comment='输入 token'),
        sa.Column('output_tokens', sa.Numeric(12), nullable=True, comment='输出 token（含 reasoning）'),
        sa.Column('cache_hit_tokens', sa.Numeric(12), nullable=True, comment='prompt 缓存命中 token'),
        sa.Column('cache_miss_tokens', sa.Numeric(12), nullable=True, comment='prompt 缓存未命中 token'),
        sa.Column('latency_ms', sa.Numeric(12), nullable=True, comment='耗时毫秒'),
        sa.Column('degradation_level', sa.String(length=32), nullable=True, comment='降级标记（backup_model）；正常为空'),
        sa.Column('session_id', sa.Uuid(), nullable=True, comment='关联会话'),
        sa.Column('draft_id', sa.Uuid(), nullable=True, comment='关联草稿（识别入库场景）'),
        sa.Column('chat_id', sa.String(length=64), nullable=True, comment='发起会话（群/私聊 chat_id）'),
        sa.Column('user_open_id', sa.String(length=64), nullable=True, comment='发起人飞书 open_id'),
        sa.Column('channel', sa.String(length=16), nullable=True, comment='触发渠道（feishu）'),
        *_base_columns(), *_base_fks(),
        schema='warehouse',
    )
    op.create_index('ix_warehouse_ai_call_audits_scenario_created', 'ai_call_audits', ['scenario', 'created_at'], unique=False, schema='warehouse')
    op.create_index('ix_warehouse_ai_call_audits_trace', 'ai_call_audits', ['trace_id'], unique=False, schema='warehouse')
    op.create_index('ix_warehouse_ai_call_audits_session', 'ai_call_audits', ['session_id'], unique=False, schema='warehouse')
    op.create_index('ix_warehouse_ai_call_audits_created', 'ai_call_audits', ['created_at'], unique=False, schema='warehouse')

    # ── Bitable 连接 ──
    op.create_table('bitable_connections',
        sa.Column('table_key', sa.String(length=64), nullable=False, comment='表 key（bitable_schema.TABLES 注册，如 material_receipt）'),
        sa.Column('base_token', sa.String(length=128), nullable=True, comment='Base app_token 覆盖（空 = 回落 env/快照）'),
        sa.Column('table_id', sa.String(length=64), nullable=True, comment='表 table_id 覆盖（空 = 回落代码快照）'),
        sa.Column('enabled', sa.Boolean(), server_default='true', nullable=False, comment='是否启用（false = 显式停用该表，不回退默认）'),
        sa.Column('note', sa.String(length=255), nullable=True, comment='备注'),
        *_base_columns(), *_base_fks(),
        schema='warehouse',
    )
    op.create_index('ix_warehouse_bitable_connections_table_key', 'bitable_connections', ['table_key'], unique=False, schema='warehouse')
    op.create_index('uq_warehouse_bitable_connections_table_key', 'bitable_connections', ['table_key'], unique=True, schema='warehouse', postgresql_where=sa.text('is_deleted = false'))

    op.create_table('bitable_config_audits',
        sa.Column('table_key', sa.String(length=64), nullable=False, comment='表 key'),
        sa.Column('action', sa.String(length=32), nullable=False, comment='动作: update/enable/disable'),
        sa.Column('before_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='变更前（compact，base_token 脱敏）'),
        sa.Column('after_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='变更后（compact，base_token 脱敏）'),
        sa.Column('operator_name', sa.String(length=128), nullable=True, comment='操作人 name'),
        *_base_columns(), *_base_fks(),
        schema='warehouse',
    )
    op.create_index('ix_warehouse_bitable_config_audits_created', 'bitable_config_audits', ['created_at'], unique=False, schema='warehouse')

    # ── 运行参数 ──
    op.create_table('runtime_configs',
        sa.Column('key', sa.String(length=64), nullable=False, comment='参数 key（runtime_registry 注册，DB 只能改值不能新增）'),
        sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='参数值（按注册表类型写入）'),
        sa.Column('note', sa.String(length=255), nullable=True, comment='备注'),
        *_base_columns(), *_base_fks(),
        schema='warehouse',
    )
    op.create_index('ix_warehouse_runtime_configs_key', 'runtime_configs', ['key'], unique=False, schema='warehouse')
    op.create_index('uq_warehouse_runtime_configs_key', 'runtime_configs', ['key'], unique=True, schema='warehouse', postgresql_where=sa.text('is_deleted = false'))

    op.create_table('runtime_config_audits',
        sa.Column('key', sa.String(length=64), nullable=False, comment='参数 key'),
        sa.Column('action', sa.String(length=32), nullable=False, comment='动作: update/reset'),
        sa.Column('before_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='变更前'),
        sa.Column('after_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='变更后'),
        sa.Column('operator_name', sa.String(length=128), nullable=True, comment='操作人 name'),
        *_base_columns(), *_base_fks(),
        schema='warehouse',
    )
    op.create_index('ix_warehouse_runtime_config_audits_key_created', 'runtime_config_audits', ['key', 'created_at'], unique=False, schema='warehouse')
    op.create_index('ix_warehouse_runtime_config_audits_created', 'runtime_config_audits', ['created_at'], unique=False, schema='warehouse')

    # ── 定时任务/告警目标 ──
    op.create_table('scheduler_task_configs',
        sa.Column('job_name', sa.String(length=64), nullable=False, comment='任务 key（scheduler_registry 注册，如 system_alert）'),
        sa.Column('enabled', sa.Boolean(), server_default='true', nullable=False, comment='是否启用'),
        sa.Column('schedule', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='调度（interval/cron；null=事件触发）'),
        sa.Column('target_chat_id', sa.String(length=64), nullable=True, comment='飞书投递目标（群 chat_id；空 = 回落 env 兜底）'),
        sa.Column('note', sa.String(length=255), nullable=True, comment='备注'),
        *_base_columns(), *_base_fks(),
        schema='warehouse',
    )
    op.create_index('ix_warehouse_scheduler_task_configs_job', 'scheduler_task_configs', ['job_name'], unique=False, schema='warehouse')
    op.create_index('uq_warehouse_scheduler_task_configs_job', 'scheduler_task_configs', ['job_name'], unique=True, schema='warehouse', postgresql_where=sa.text('is_deleted = false'))

    op.create_table('scheduler_config_audits',
        sa.Column('job_name', sa.String(length=64), nullable=False, comment='任务 key'),
        sa.Column('action', sa.String(length=32), nullable=False, comment='动作: update/enable/disable'),
        sa.Column('before_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='变更前'),
        sa.Column('after_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='变更后'),
        sa.Column('operator_name', sa.String(length=128), nullable=True, comment='操作人 name'),
        *_base_columns(), *_base_fks(),
        schema='warehouse',
    )
    op.create_index('ix_warehouse_scheduler_config_audits_job_created', 'scheduler_config_audits', ['job_name', 'created_at'], unique=False, schema='warehouse')
    op.create_index('ix_warehouse_scheduler_config_audits_created', 'scheduler_config_audits', ['created_at'], unique=False, schema='warehouse')

    # ═══════════════════════════════════════════════════════════
    # 播种（registry 单向导出；幂等语义由唯一键保证——重复执行先清后插）
    # ═══════════════════════════════════════════════════════════
    now = datetime.now(UTC)

    profile_rows = sa.table(
        'ai_model_profiles',
        sa.column('id', sa.Uuid()), sa.column('profile', sa.String(32)),
        sa.column('config', postgresql.JSONB()), sa.column('enabled', sa.Boolean()),
        sa.column('is_deleted', sa.Boolean()),
        sa.column('created_at', sa.DateTime(timezone=True)),
        sa.column('updated_at', sa.DateTime(timezone=True)),
        schema='warehouse',
    )
    op.bulk_insert(profile_rows, [
        {"id": uuid4(), "profile": info.profile, "config": dict(info.default_config),
         "enabled": True, "is_deleted": False, "created_at": now, "updated_at": now}
        for info in ai_registry.iter_profiles()
    ])

    scenario_rows = sa.table(
        'ai_scenario_configs',
        sa.column('id', sa.Uuid()), sa.column('scenario', sa.String(64)),
        sa.column('enabled', sa.Boolean()), sa.column('model_profile', sa.String(32)),
        sa.column('is_deleted', sa.Boolean()),
        sa.column('created_at', sa.DateTime(timezone=True)),
        sa.column('updated_at', sa.DateTime(timezone=True)),
        schema='warehouse',
    )
    op.bulk_insert(scenario_rows, [
        {"id": uuid4(), "scenario": info.scenario, "enabled": True,
         "model_profile": None, "is_deleted": False, "created_at": now, "updated_at": now}
        for info in ai_scenario_registry.iter_scenarios()
    ])

    runtime_rows = sa.table(
        'runtime_configs',
        sa.column('id', sa.Uuid()), sa.column('key', sa.String(64)),
        sa.column('value', postgresql.JSONB()),
        sa.column('is_deleted', sa.Boolean()),
        sa.column('created_at', sa.DateTime(timezone=True)),
        sa.column('updated_at', sa.DateTime(timezone=True)),
        schema='warehouse',
    )
    op.bulk_insert(runtime_rows, [
        {"id": uuid4(), "key": info.key, "value": info.default,
         "is_deleted": False, "created_at": now, "updated_at": now}
        for info in runtime_registry.iter_runtime_keys()
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
        for info in bitable_registry.iter_connections()
    ])

    task_rows = sa.table(
        'scheduler_task_configs',
        sa.column('id', sa.Uuid()), sa.column('job_name', sa.String(64)),
        sa.column('enabled', sa.Boolean()), sa.column('schedule', postgresql.JSONB()),
        sa.column('target_chat_id', sa.String(64)),
        sa.column('is_deleted', sa.Boolean()),
        sa.column('created_at', sa.DateTime(timezone=True)),
        sa.column('updated_at', sa.DateTime(timezone=True)),
        schema='warehouse',
    )
    op.bulk_insert(task_rows, [
        {"id": uuid4(), "job_name": info.job_name, "enabled": True,
         "schedule": info.default_schedule, "target_chat_id": None,
         "is_deleted": False, "created_at": now, "updated_at": now}
        for info in scheduler_registry.iter_tasks()
    ])


def downgrade() -> None:
    for table in (
        'scheduler_config_audits', 'scheduler_task_configs',
        'runtime_config_audits', 'runtime_configs',
        'bitable_config_audits', 'bitable_connections',
        'ai_call_audits', 'ai_scenario_config_audits', 'ai_scenario_configs',
        'ai_config_audits', 'ai_model_profiles',
    ):
        op.drop_table(table, schema='warehouse')
