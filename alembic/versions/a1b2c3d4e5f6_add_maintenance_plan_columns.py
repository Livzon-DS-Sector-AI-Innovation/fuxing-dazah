"""add maintenance plan columns

Revision ID: a1b2c3d4e5f6
Revises: 8669b3dc5093
Create Date: 2026-06-04 15:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '8669b3dc5093'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add columns to the existing maintenance_plans stub table
    op.add_column(
        'maintenance_plans',
        sa.Column('equipment_id', sa.Uuid(), nullable=False, comment='设备ID'),
        schema='equipment',
    )
    op.add_column(
        'maintenance_plans',
        sa.Column('plan_name', sa.String(length=200), nullable=False, comment='计划名称'),
        schema='equipment',
    )
    op.add_column(
        'maintenance_plans',
        sa.Column('plan_type', sa.String(length=20), server_default='预防性维护', nullable=False, comment='计划类型：预防性维护/预测性维护'),
        schema='equipment',
    )
    op.add_column(
        'maintenance_plans',
        sa.Column('frequency', sa.Integer(), nullable=False, comment='维护频率数值'),
        schema='equipment',
    )
    op.add_column(
        'maintenance_plans',
        sa.Column('frequency_unit', sa.String(length=10), nullable=False, comment='频率单位：天/周/月/年'),
        schema='equipment',
    )
    op.add_column(
        'maintenance_plans',
        sa.Column('last_maintenance_date', sa.Date(), nullable=True, comment='上次维护日期'),
        schema='equipment',
    )
    op.add_column(
        'maintenance_plans',
        sa.Column('next_maintenance_date', sa.Date(), nullable=True, comment='下次维护日期'),
        schema='equipment',
    )
    op.add_column(
        'maintenance_plans',
        sa.Column('responsible_person_id', sa.Uuid(), nullable=True, comment='负责人ID'),
        schema='equipment',
    )
    op.add_column(
        'maintenance_plans',
        sa.Column('maintenance_content', sa.Text(), nullable=True, comment='维护内容说明'),
        schema='equipment',
    )
    op.add_column(
        'maintenance_plans',
        sa.Column('status', sa.String(length=10), server_default='启用', nullable=False, comment='状态：启用/停用/已完成'),
        schema='equipment',
    )
    op.add_column(
        'maintenance_plans',
        sa.Column('remark', sa.Text(), nullable=True, comment='备注'),
        schema='equipment',
    )

    # Add foreign key constraints
    op.create_foreign_key(
        'fk_maintenance_plans_equipment_id',
        'maintenance_plans',
        'equipments',
        ['equipment_id'],
        ['id'],
        source_schema='equipment',
        referent_schema='equipment',
    )
    op.create_foreign_key(
        'fk_maintenance_plans_responsible_person_id',
        'maintenance_plans',
        'users',
        ['responsible_person_id'],
        ['id'],
        source_schema='equipment',
        referent_schema='identity',
    )

    # Add check constraints
    op.create_check_constraint(
        'ck_maintenance_plans_plan_type',
        'maintenance_plans',
        "plan_type IN ('预防性维护', '预测性维护')",
        schema='equipment',
    )
    op.create_check_constraint(
        'ck_maintenance_plans_frequency_unit',
        'maintenance_plans',
        "frequency_unit IN ('天', '周', '月', '年')",
        schema='equipment',
    )
    op.create_check_constraint(
        'ck_maintenance_plans_status',
        'maintenance_plans',
        "status IN ('启用', '停用', '已完成')",
        schema='equipment',
    )


def downgrade() -> None:
    # Drop check constraints
    op.drop_constraint('ck_maintenance_plans_status', 'maintenance_plans', schema='equipment')
    op.drop_constraint('ck_maintenance_plans_frequency_unit', 'maintenance_plans', schema='equipment')
    op.drop_constraint('ck_maintenance_plans_plan_type', 'maintenance_plans', schema='equipment')

    # Drop foreign key constraints
    op.drop_constraint('fk_maintenance_plans_responsible_person_id', 'maintenance_plans', schema='equipment')
    op.drop_constraint('fk_maintenance_plans_equipment_id', 'maintenance_plans', schema='equipment')

    # Drop columns
    op.drop_column('maintenance_plans', 'remark', schema='equipment')
    op.drop_column('maintenance_plans', 'status', schema='equipment')
    op.drop_column('maintenance_plans', 'maintenance_content', schema='equipment')
    op.drop_column('maintenance_plans', 'responsible_person_id', schema='equipment')
    op.drop_column('maintenance_plans', 'next_maintenance_date', schema='equipment')
    op.drop_column('maintenance_plans', 'last_maintenance_date', schema='equipment')
    op.drop_column('maintenance_plans', 'frequency_unit', schema='equipment')
    op.drop_column('maintenance_plans', 'frequency', schema='equipment')
    op.drop_column('maintenance_plans', 'plan_type', schema='equipment')
    op.drop_column('maintenance_plans', 'plan_name', schema='equipment')
    op.drop_column('maintenance_plans', 'equipment_id', schema='equipment')
