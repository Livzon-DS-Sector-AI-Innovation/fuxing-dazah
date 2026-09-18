"""warehouse qc status mirror and seeds

QC 请验放行闭环（V3.0 分期B Ticket 01，设计 §4.1）：
- 新表 warehouse.qc_status（QC 状态镜像，record_id 幂等 upsert）；
- 播种 3 个推送任务行（到货请验/QC 进度提醒/放行通知，event 型）；
- 播种 2 个预警规则行（QC 未取样超期/未出报超期，全局默认阈值）。

Revision ID: d1f6b8a4c2e9
Revises: c9e5a7b3d1f4
Create Date: 2026-09-18
"""
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# registry 单向导出播种（禁止手抄，防双份常量漂移）
from app.modules.warehouse.ops_config import runtime_registry
from app.modules.warehouse.push_center import registry as push_registry

# revision identifiers, used by Alembic.
revision: str = 'd1f6b8a4c2e9'
down_revision: str | None = 'c9e5a7b3d1f4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 分期B 新增推送任务（a7c3e9f5b2d8 已播种分期A 5 行，这里只补 B 期 3 行）
QC_PUSH_TASKS = ("arrival_inspection", "qc_progress_alert", "release_notify")

# 补播种的运行参数行（含分期A 欠账 bitable_writeback_enabled——b4ad023 只注册
# 未播种，DB 缺行靠 fallback 生效，live 行数断言不一致；值取注册表默认）
QC_RUNTIME_KEYS = ("bitable_writeback_enabled", "qc_writeback_enabled", "qa_confirm_target")

# QC 超期规则全局默认（物料级覆盖走 material_master「实际物料：请检后出报天数」）
QC_ALERT_RULES = (
    ("qc_sample_overdue", "QC未取样超期", {"days": 3}),
    ("qc_report_overdue", "QC未出报超期", {"days": 7}),
)


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
    # ── QC 状态镜像（Base 为权威，本表只读展示 + 变迁检测）──
    op.create_table('qc_status',
        sa.Column('record_id', sa.String(length=64), nullable=False, comment='material_receipt record_id（唯一，幂等键）'),
        sa.Column('batch_no', sa.String(length=100), server_default='', nullable=False, comment='物料批号'),
        sa.Column('material_name', sa.String(length=200), server_default='', nullable=False, comment='物料名称'),
        sa.Column('receipt_date', sa.Date(), nullable=True, comment='入库日期（超期判断与展示）'),
        sa.Column('sample_status', sa.String(length=32), nullable=True, comment='QC取样情况: 已取样/未取样/无需取'),
        sa.Column('report_status', sa.String(length=32), nullable=True, comment='QC出报: 已出报（合格）/已出报（不合格）/未出报/免检物料'),
        sa.Column('release_status', sa.String(length=32), nullable=True, comment='QA放行: 放行/否决/条件放行'),
        sa.Column('scanned_at', sa.DateTime(timezone=True), nullable=False, comment='最近一次扫描时间'),
        *_base_columns(), *_base_fks(),
        schema='warehouse',
    )
    op.create_index('uq_warehouse_qc_status_record', 'qc_status', ['record_id'], unique=True, schema='warehouse', postgresql_where=sa.text('is_deleted = false'))
    op.create_index('ix_warehouse_qc_status_batch', 'qc_status', ['batch_no'], schema='warehouse')

    now = datetime.now(UTC)

    # ── 播种：B 期 3 个推送任务（registry 单向导出）──
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
        for info in push_registry.iter_tasks() if info.task_name in QC_PUSH_TASKS
    ])

    # ── 播种：QC 超期规则全局默认（智能中心预警配置可改）──
    rule_rows = sa.table(
        'alert_rules',
        sa.column('id', sa.Uuid()), sa.column('rule_key', sa.String(32)),
        sa.column('name', sa.String(64)), sa.column('threshold', postgresql.JSONB()),
        sa.column('enabled', sa.Boolean()), sa.column('is_deleted', sa.Boolean()),
        sa.column('created_at', sa.DateTime(timezone=True)),
        sa.column('updated_at', sa.DateTime(timezone=True)),
        schema='warehouse',
    )
    op.bulk_insert(rule_rows, [
        {"id": uuid4(), "rule_key": key, "name": name, "threshold": threshold,
         "enabled": True, "is_deleted": False, "created_at": now, "updated_at": now}
        for key, name, threshold in QC_ALERT_RULES
    ])

    # ── 播种：运行参数行（registry 默认值；含分期A 欠账 bitable_writeback_enabled）──
    runtime_rows = sa.table(
        'runtime_configs',
        sa.column('id', sa.Uuid()), sa.column('key', sa.String(64)),
        sa.column('value', postgresql.JSONB()), sa.column('note', sa.String(255)),
        sa.column('is_deleted', sa.Boolean()),
        sa.column('created_at', sa.DateTime(timezone=True)),
        sa.column('updated_at', sa.DateTime(timezone=True)),
        schema='warehouse',
    )
    op.bulk_insert(runtime_rows, [
        {"id": uuid4(), "key": info.key, "value": info.default, "note": None,
         "is_deleted": False, "created_at": now, "updated_at": now}
        for info in runtime_registry.iter_runtime_keys() if info.key in QC_RUNTIME_KEYS
    ])


def downgrade() -> None:
    op.execute("DELETE FROM warehouse.runtime_configs WHERE key IN ('bitable_writeback_enabled', 'qc_writeback_enabled', 'qa_confirm_target')")
    op.execute("DELETE FROM warehouse.alert_rules WHERE rule_key IN ('qc_sample_overdue', 'qc_report_overdue')")
    op.execute("DELETE FROM warehouse.push_tasks WHERE task_name IN ('arrival_inspection', 'qc_progress_alert', 'release_notify')")
    op.drop_index('ix_warehouse_qc_status_batch', table_name='qc_status', schema='warehouse')
    op.drop_index('uq_warehouse_qc_status_record', table_name='qc_status', schema='warehouse')
    op.drop_table('qc_status', schema='warehouse')
