"""add chemical inventory tables

新增危化品库存管理 3 张表（safety schema），固定行台账 + 变更触发风险分析 + 每日汇总快照：
  - chemical_inventory_records   （危化品库存总表镜像，固定行，原地更新）
  - chemical_risk_alerts         （库存风险预警，库存变化触发）
  - chemical_inventory_summaries （库存汇总快照，每日 17:00 提取）

Revision ID: f41b724c4df8
Revises: ef05484455e7
Create Date: 2026-08-24 14:49:03.971151
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f41b724c4df8'
down_revision: Union[str, None] = 'ef05484455e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS safety")

    # ── 表 1：危化品库存总表镜像（固定行）──
    op.create_table('chemical_inventory_records',
    sa.Column('feishu_record_id', sa.String(length=64), nullable=True, comment='Bitable 记录 ID'),
    sa.Column('department', sa.String(length=32), nullable=False, comment='部门'),
    sa.Column('storage_location', sa.String(length=128), nullable=True, comment='存放部位'),
    sa.Column('material_name', sa.String(length=128), nullable=False, comment='物料名称'),
    sa.Column('cas_no', sa.String(length=64), nullable=True, comment='CAS号'),
    sa.Column('package_spec', sa.String(length=128), nullable=True, comment='包装规格'),
    sa.Column('quantity', sa.Numeric(precision=14, scale=4), nullable=True, comment='库存数量'),
    sa.Column('unit', sa.String(length=16), nullable=True, comment='单位'),
    sa.Column('total_quantity_t', sa.Numeric(precision=14, scale=4), nullable=True, comment='现场物料总量(T)'),
    sa.Column('pure_quantity', sa.Numeric(precision=14, scale=4), nullable=True, comment='折纯量'),
    sa.Column('max_limit', sa.Numeric(precision=14, scale=4), nullable=True, comment='库存上限'),
    sa.Column('max_limit_unit', sa.String(length=16), nullable=True, comment='上限单位'),
    sa.Column('hazard_classes', sa.JSON(), nullable=True, comment='危险性(多选)'),
    sa.Column('category', sa.String(length=64), nullable=True, comment='品类'),
    sa.Column('last_updated_at', sa.DateTime(timezone=True), nullable=True, comment='最后更新时间（Bitable 系统字段）'),
    sa.Column('remark', sa.Text(), nullable=True, comment='备注'),
    sa.Column('risk_flag', sa.String(length=16), server_default='normal', nullable=False, comment='风险标记'),
    sa.Column('risk_note', sa.Text(), nullable=True, comment='风险说明'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='safety'
    )
    op.create_index('idx_cir_feishu_record', 'chemical_inventory_records', ['feishu_record_id'], unique=False, schema='safety')
    op.create_index('idx_cir_dept_loc', 'chemical_inventory_records', ['department', 'storage_location'], unique=False, schema='safety')
    op.create_index('uq_cir_feishu_record', 'chemical_inventory_records', ['feishu_record_id'], unique=True, schema='safety', postgresql_where=sa.text('feishu_record_id IS NOT NULL AND is_deleted = false'))
    op.create_index('uq_cir_dept_loc_name', 'chemical_inventory_records', ['department', 'storage_location', 'material_name'], unique=True, schema='safety', postgresql_where=sa.text('is_deleted = false'))

    # ── 表 2：库存汇总快照 ──
    op.create_table('chemical_inventory_summaries',
    sa.Column('feishu_record_id', sa.String(length=64), nullable=True, comment='Bitable 记录 ID'),
    sa.Column('extract_date', sa.Date(), nullable=False, comment='提取日期'),
    sa.Column('department', sa.String(length=32), nullable=False, comment='部门'),
    sa.Column('material_name', sa.String(length=128), nullable=False, comment='物料名称'),
    sa.Column('total_quantity_t', sa.Numeric(precision=14, scale=4), nullable=False, comment='现场物料总量(T) SUM'),
    sa.Column('record_count', sa.Integer(), nullable=False, comment='聚合记录条数'),
    sa.Column('risk_level', sa.String(length=16), server_default='normal', nullable=False, comment='该部门该物料最高风险'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='safety'
    )
    op.create_index('idx_cis_extract_dept', 'chemical_inventory_summaries', ['extract_date', 'department'], unique=False, schema='safety')
    op.create_index('idx_cis_extract_name', 'chemical_inventory_summaries', ['extract_date', 'material_name'], unique=False, schema='safety')
    op.create_index('uq_cis_extract_dept_name', 'chemical_inventory_summaries', ['extract_date', 'department', 'material_name'], unique=True, schema='safety', postgresql_where=sa.text('is_deleted = false'))

    # ── 表 3：库存风险预警 ──
    op.create_table('chemical_risk_alerts',
    sa.Column('feishu_record_id', sa.String(length=64), nullable=True, comment='Bitable 记录 ID'),
    sa.Column('trigger_date', sa.Date(), nullable=False, comment='触发日期'),
    sa.Column('triggered_at', sa.DateTime(timezone=True), nullable=True, comment='触发时间'),
    sa.Column('department', sa.String(length=32), nullable=False, comment='部门'),
    sa.Column('material_name', sa.String(length=128), nullable=False, comment='物料名称'),
    sa.Column('alert_type', sa.String(length=32), nullable=False, comment='预警类型'),
    sa.Column('severity', sa.String(length=16), nullable=False, comment='严重程度'),
    sa.Column('description', sa.Text(), nullable=False, comment='风险描述'),
    sa.Column('suggestion', sa.Text(), nullable=True, comment='建议措施'),
    sa.Column('related_record_ids', sa.JSON(), nullable=True, comment='关联记录 record_id/uuid'),
    sa.Column('status', sa.String(length=16), server_default='pending', nullable=False, comment='状态'),
    sa.Column('source', sa.String(length=8), server_default='rule', nullable=False, comment='来源: rule/ai'),
    sa.Column('ai_call_audit_id', sa.UUID(), nullable=True, comment='关联 ai_call_audits.id'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='safety'
    )
    op.create_index('idx_cra_dept_material', 'chemical_risk_alerts', ['department', 'material_name'], unique=False, schema='safety')
    op.create_index('idx_cra_trigger_date', 'chemical_risk_alerts', ['trigger_date'], unique=False, schema='safety')
    op.create_index('idx_cra_severity', 'chemical_risk_alerts', ['severity'], unique=False, schema='safety')
    op.create_index('uq_cra_feishu_record', 'chemical_risk_alerts', ['feishu_record_id'], unique=True, schema='safety', postgresql_where=sa.text('feishu_record_id IS NOT NULL AND is_deleted = false'))


def downgrade() -> None:
    op.drop_index('uq_cra_feishu_record', table_name='chemical_risk_alerts', schema='safety', postgresql_where=sa.text('feishu_record_id IS NOT NULL AND is_deleted = false'))
    op.drop_index('idx_cra_severity', table_name='chemical_risk_alerts', schema='safety')
    op.drop_index('idx_cra_trigger_date', table_name='chemical_risk_alerts', schema='safety')
    op.drop_index('idx_cra_dept_material', table_name='chemical_risk_alerts', schema='safety')
    op.drop_table('chemical_risk_alerts', schema='safety')
    op.drop_index('uq_cis_extract_dept_name', table_name='chemical_inventory_summaries', schema='safety', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('idx_cis_extract_name', table_name='chemical_inventory_summaries', schema='safety')
    op.drop_index('idx_cis_extract_dept', table_name='chemical_inventory_summaries', schema='safety')
    op.drop_table('chemical_inventory_summaries', schema='safety')
    op.drop_index('uq_cir_dept_loc_name', table_name='chemical_inventory_records', schema='safety', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('uq_cir_feishu_record', table_name='chemical_inventory_records', schema='safety', postgresql_where=sa.text('feishu_record_id IS NOT NULL AND is_deleted = false'))
    op.drop_index('idx_cir_dept_loc', table_name='chemical_inventory_records', schema='safety')
    op.drop_index('idx_cir_feishu_record', table_name='chemical_inventory_records', schema='safety')
    op.drop_table('chemical_inventory_records', schema='safety')
