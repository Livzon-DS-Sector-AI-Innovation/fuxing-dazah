"""warehouse intelligence tables (Phase B)

智能中心数据底座：预警规则（默认播种）、规则变更审计、异常记录、补货建议。

Revision ID: f7a3b8c2d9e4
Revises: d5e1f8a3b6c2
Create Date: 2026-09-16
"""
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f7a3b8c2d9e4'
down_revision: str | None = 'd5e1f8a3b6c2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_RULES = [
    ("low_stock", "低库存预警", {}),
    ("zero_stock", "零库存预警", {}),
    ("idle", "呆滞预警", {"days": 90}),
    ("expiry", "效期临期预警", {"days": 30}),
    ("cover_days", "补货覆盖天数", {"days": 14}),
]


def _base_columns() -> list[sa.Column]:
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
    op.execute('CREATE SCHEMA IF NOT EXISTS warehouse')

    op.create_table('alert_rules',
        sa.Column('rule_key', sa.String(length=32), nullable=False, comment='规则键'),
        sa.Column('name', sa.String(length=64), nullable=False, comment='规则名称'),
        sa.Column('threshold', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False, comment='阈值（按规则键约定字段）'),
        sa.Column('enabled', sa.Boolean(), server_default='true', nullable=False, comment='是否启用'),
        sa.Column('note', sa.String(length=255), nullable=True, comment='备注'),
        *_base_columns(), *_base_fks(),
        schema='warehouse',
    )
    op.create_index('uq_warehouse_alert_rules_key', 'alert_rules', ['rule_key'], unique=True, schema='warehouse', postgresql_where=sa.text('is_deleted = false'))

    op.create_table('alert_rule_audits',
        sa.Column('rule_key', sa.String(length=32), nullable=False, comment='规则键'),
        sa.Column('action', sa.String(length=16), nullable=False, comment='动作: update/enable/disable'),
        sa.Column('before_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='变更前'),
        sa.Column('after_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='变更后'),
        sa.Column('operator_name', sa.String(length=128), nullable=True, comment='操作人'),
        *_base_columns(), *_base_fks(),
        schema='warehouse',
    )
    op.create_index('ix_warehouse_alert_rule_audits_key_created', 'alert_rule_audits', ['rule_key', 'created_at'], schema='warehouse')

    op.create_table('alert_records',
        sa.Column('rule_key', sa.String(length=32), nullable=False, comment='规则键'),
        sa.Column('level', sa.String(length=16), server_default='warning', nullable=False, comment='级别: warning/critical'),
        sa.Column('status', sa.String(length=16), server_default='open', nullable=False, comment='状态: open/resolved'),
        sa.Column('material_id', sa.Uuid(), nullable=False),
        sa.Column('material_code', sa.String(length=50), nullable=False, comment='物料编码（冗余）'),
        sa.Column('material_name', sa.String(length=200), nullable=False, comment='物料名称（冗余）'),
        sa.Column('batch_no', sa.String(length=100), server_default='', nullable=False, comment='批次号（临期类用）'),
        sa.Column('location_id', sa.Uuid(), nullable=True),
        sa.Column('location_code', sa.String(length=50), nullable=True, comment='库位编码（冗余）'),
        sa.Column('location_name', sa.String(length=200), nullable=True, comment='库位名称（冗余）'),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False, comment='异常详情（数量/天数等）'),
        sa.Column('resolved_by', sa.Uuid(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        *_base_columns(), *_base_fks(),
        schema='warehouse',
    )
    op.create_index('ix_warehouse_alert_records_key_material', 'alert_records', ['rule_key', 'material_id'], schema='warehouse')
    op.create_index('ix_warehouse_alert_records_status', 'alert_records', ['status'], schema='warehouse')

    op.create_table('replenishment_suggestions',
        sa.Column('material_id', sa.Uuid(), nullable=False),
        sa.Column('material_code', sa.String(length=50), nullable=False, comment='物料编码（冗余）'),
        sa.Column('material_name', sa.String(length=200), nullable=False, comment='物料名称（冗余）'),
        sa.Column('avg_daily_outbound', sa.Numeric(18, 4), server_default='0', nullable=False, comment='日均出库消耗（近30天）'),
        sa.Column('days_cover', sa.Numeric(18, 4), nullable=True, comment='可支撑天数（当前库存/日均），零消耗为空'),
        sa.Column('suggested_qty', sa.Numeric(18, 4), server_default='0', nullable=False, comment='建议采购量'),
        sa.Column('status', sa.String(length=16), server_default='pending', nullable=False, comment='pending/handled/ignored'),
        sa.Column('handled_by', sa.Uuid(), nullable=True),
        sa.Column('handled_at', sa.DateTime(timezone=True), nullable=True),
        *_base_columns(), *_base_fks(),
        schema='warehouse',
    )
    op.create_index('ix_warehouse_replenishment_suggestions_status', 'replenishment_suggestions', ['status'], schema='warehouse')
    op.create_index('uq_warehouse_replenishment_suggestions_material', 'replenishment_suggestions', ['material_id'], unique=True, schema='warehouse', postgresql_where=sa.text('is_deleted = false'))

    # ── 默认规则播种（表由本迁移新建，必然为空） ──
    now = datetime.now(UTC)
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
        for key, name, threshold in DEFAULT_RULES
    ])


def downgrade() -> None:
    op.drop_index('uq_warehouse_replenishment_suggestions_material', table_name='replenishment_suggestions', schema='warehouse')
    op.drop_index('ix_warehouse_replenishment_suggestions_status', table_name='replenishment_suggestions', schema='warehouse')
    op.drop_table('replenishment_suggestions', schema='warehouse')
    op.drop_index('ix_warehouse_alert_records_status', table_name='alert_records', schema='warehouse')
    op.drop_index('ix_warehouse_alert_records_key_material', table_name='alert_records', schema='warehouse')
    op.drop_table('alert_records', schema='warehouse')
    op.drop_index('ix_warehouse_alert_rule_audits_key_created', table_name='alert_rule_audits', schema='warehouse')
    op.drop_table('alert_rule_audits', schema='warehouse')
    op.drop_index('uq_warehouse_alert_rules_key', table_name='alert_rules', schema='warehouse')
    op.drop_table('alert_rules', schema='warehouse')
