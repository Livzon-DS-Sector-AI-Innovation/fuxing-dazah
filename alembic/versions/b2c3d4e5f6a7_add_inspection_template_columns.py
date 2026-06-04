"""add inspection template columns and items table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-04 16:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add columns to the existing inspection_templates stub table
    op.add_column(
        'inspection_templates',
        sa.Column('name', sa.String(length=200), nullable=False, comment='模板名称'),
        schema='equipment',
    )
    op.add_column(
        'inspection_templates',
        sa.Column('description', sa.Text(), nullable=True, comment='模板描述'),
        schema='equipment',
    )
    op.add_column(
        'inspection_templates',
        sa.Column('equipment_category_id', sa.Uuid(), nullable=True, comment='适用设备分类ID'),
        schema='equipment',
    )
    op.add_column(
        'inspection_templates',
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False, comment='是否启用'),
        schema='equipment',
    )

    # Add foreign key constraints
    op.create_foreign_key(
        'fk_inspection_templates_equipment_category_id',
        'inspection_templates',
        'equipment_categories',
        ['equipment_category_id'],
        ['id'],
        source_schema='equipment',
        referent_schema='equipment',
    )

    # Create inspection_template_items table
    op.create_table(
        'inspection_template_items',
        sa.Column('template_id', sa.Uuid(), nullable=False, comment='模板ID'),
        sa.Column('item_name', sa.String(length=200), nullable=False, comment='检查项名称'),
        sa.Column('item_description', sa.Text(), nullable=True, comment='检查项说明'),
        sa.Column('expected_result', sa.String(length=200), nullable=True, comment='预期结果/标准值'),
        sa.Column('check_method', sa.String(length=100), nullable=True, comment='检查方法'),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False, comment='排序序号'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id']),
        sa.ForeignKeyConstraint(['template_id'], ['equipment.inspection_templates.id']),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id']),
        sa.PrimaryKeyConstraint('id'),
        schema='equipment',
    )


def downgrade() -> None:
    # Drop inspection_template_items table
    op.drop_table('inspection_template_items', schema='equipment')

    # Drop foreign key constraints
    op.drop_constraint('fk_inspection_templates_equipment_category_id', 'inspection_templates', schema='equipment')

    # Drop columns
    op.drop_column('inspection_templates', 'is_active', schema='equipment')
    op.drop_column('inspection_templates', 'equipment_category_id', schema='equipment')
    op.drop_column('inspection_templates', 'description', schema='equipment')
    op.drop_column('inspection_templates', 'name', schema='equipment')
