"""quality add lab items inspection plans and culture days

Revision ID: 6dd0f0874f55
Revises: 79da991ca741
Create Date: 2026-10-19 14:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '6dd0f0874f55'
down_revision: Union[str, None] = '79da991ca741'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('quality_lab_items',
    sa.Column('item_type', sa.String(length=32), nullable=False, comment='reagent 试剂 / reference_standard 对照品 / titrant 滴定液 / instrument 仪器校验'),
    sa.Column('name', sa.String(length=200), nullable=False, comment='名称/仪器名称'),
    sa.Column('batch_no', sa.String(length=100), nullable=True, comment='批号（试剂类）'),
    sa.Column('spec', sa.String(length=100), nullable=True, comment='规格'),
    sa.Column('opened_at', sa.String(length=32), nullable=True, comment='开封日期 YYYY-MM-DD（试剂开启后效期从开封算）'),
    sa.Column('expiry_date', sa.String(length=32), nullable=True, comment='效期/下次校验日期 YYYY-MM-DD（到期提醒依据）'),
    sa.Column('remark', sa.String(length=200), nullable=True, comment='备注'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='quality'
    )
    op.create_index('ix_quality_lab_item_type', 'quality_lab_items', ['item_type'], unique=False, schema='quality')
    op.create_index('ix_quality_lab_item_expiry', 'quality_lab_items', ['expiry_date'], unique=False, schema='quality')
    op.create_table('quality_inspection_plans',
    sa.Column('department', sa.String(length=128), nullable=False, comment='车间/部门'),
    sa.Column('product_name', sa.String(length=200), nullable=False, comment='品种/产品名称'),
    sa.Column('batch_no', sa.String(length=100), nullable=True, comment='批号'),
    sa.Column('plan_time', sa.String(length=32), nullable=False, comment='计划请检时间 YYYY-MM-DD HH:mm'),
    sa.Column('status', sa.String(length=32), server_default='pending', nullable=False, comment='pending 待请检 / inspected 已请检'),
    sa.Column('remark', sa.String(length=200), nullable=True, comment='备注'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='quality'
    )
    op.create_index('ix_quality_plan_department', 'quality_inspection_plans', ['department'], unique=False, schema='quality')
    op.create_index('ix_quality_plan_plan_time', 'quality_inspection_plans', ['plan_time'], unique=False, schema='quality')
    op.add_column('quality_test_tasks', sa.Column('culture_days', sa.Integer(), nullable=True, comment='培养天数（微生物样品：出报日期自动=检测日期+培养天数）'), schema='quality')


def downgrade() -> None:
    op.drop_column('quality_test_tasks', 'culture_days', schema='quality')
    op.drop_index('ix_quality_plan_plan_time', table_name='quality_inspection_plans', schema='quality')
    op.drop_index('ix_quality_plan_department', table_name='quality_inspection_plans', schema='quality')
    op.drop_table('quality_inspection_plans', schema='quality')
    op.drop_index('ix_quality_lab_item_expiry', table_name='quality_lab_items', schema='quality')
    op.drop_index('ix_quality_lab_item_type', table_name='quality_lab_items', schema='quality')
    op.drop_table('quality_lab_items', schema='quality')
