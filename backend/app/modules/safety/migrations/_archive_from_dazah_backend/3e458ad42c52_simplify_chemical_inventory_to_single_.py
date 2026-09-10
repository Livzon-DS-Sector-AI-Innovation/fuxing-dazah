"""simplify chemical inventory to single table

精简为单表「危化品库存总表」：
- 删除 chemical_inventory_summaries（汇总表）
- 删除 chemical_risk_alerts（预警表）
- chemical_inventory_records 去掉 pure_quantity；risk_note 由 text 改为 json（预警类型多选）

Revision ID: 3e458ad42c52
Revises: f41b724c4df8
Create Date: 2026-08-24 16:33:39.085321
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '3e458ad42c52'
down_revision: Union[str, None] = 'f41b724c4df8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 删除预警表 ──
    op.drop_index('uq_cra_feishu_record', table_name='chemical_risk_alerts', schema='safety', postgresql_where=sa.text('feishu_record_id IS NOT NULL AND is_deleted = false'))
    op.drop_index('idx_cra_severity', table_name='chemical_risk_alerts', schema='safety')
    op.drop_index('idx_cra_trigger_date', table_name='chemical_risk_alerts', schema='safety')
    op.drop_index('idx_cra_dept_material', table_name='chemical_risk_alerts', schema='safety')
    op.drop_table('chemical_risk_alerts', schema='safety')

    # ── 删除汇总表 ──
    op.drop_index('uq_cis_extract_dept_name', table_name='chemical_inventory_summaries', schema='safety', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('idx_cis_extract_name', table_name='chemical_inventory_summaries', schema='safety')
    op.drop_index('idx_cis_extract_dept', table_name='chemical_inventory_summaries', schema='safety')
    op.drop_table('chemical_inventory_summaries', schema='safety')

    # ── 总表：去掉折纯量，风险说明改 json ──
    op.drop_column('chemical_inventory_records', 'pure_quantity', schema='safety')
    op.alter_column(
        'chemical_inventory_records', 'risk_note',
        existing_type=sa.Text(),
        type_=sa.JSON(),
        existing_nullable=True,
        schema='safety',
        postgresql_using='risk_note::json',
    )


def downgrade() -> None:
    # ── 恢复 risk_note 为 text、加回 pure_quantity ──
    op.alter_column(
        'chemical_inventory_records', 'risk_note',
        existing_type=sa.JSON(),
        type_=sa.Text(),
        existing_nullable=True,
        schema='safety',
        postgresql_using='risk_note::text',
    )
    op.add_column(
        'chemical_inventory_records',
        sa.Column('pure_quantity', sa.Numeric(precision=14, scale=4), nullable=True, comment='折纯量'),
        schema='safety',
    )

    # ── 重建汇总表 ──
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

    # ── 重建预警表 ──
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
