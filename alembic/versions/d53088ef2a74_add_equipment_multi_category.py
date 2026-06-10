"""add_equipment_multi_category

Revision ID: d53088ef2a74
Revises: 851c55d07045
Create Date: 2026-06-10 09:55:05.512820
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd53088ef2a74'
down_revision: Union[str, None] = '851c55d07045'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 创建联结表
    op.create_table('equipment_category_links',
        sa.Column('equipment_id', sa.Uuid(), nullable=False, comment='设备ID'),
        sa.Column('category_id', sa.Uuid(), nullable=False, comment='分类ID'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.ForeignKeyConstraint(['category_id'], ['equipment.equipment_categories.id'],),
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'],),
        sa.ForeignKeyConstraint(['equipment_id'], ['equipment.equipments.id'],),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'],),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('equipment_id', 'category_id', 'is_deleted', name='uq_equipment_category_links'),
        schema='equipment',
    )

    # 2. 迁移现有数据：将 equipments.category_id 迁移到联结表
    op.execute(
        "INSERT INTO equipment.equipment_category_links "
        "(id, equipment_id, category_id, created_at, updated_at, is_deleted) "
        "SELECT gen_random_uuid(), id, category_id, created_at, NOW(), false "
        "FROM equipment.equipments "
        "WHERE category_id IS NOT NULL AND is_deleted = false"
    )

    # 3. 删除旧外键和列
    op.drop_constraint(
        op.f('equipments_category_id_fkey'), 'equipments',
        schema='equipment', type_='foreignkey',
    )
    op.drop_column('equipments', 'category_id', schema='equipment')


def downgrade() -> None:
    # 1. 恢复 category_id 列
    op.add_column('equipments',
        sa.Column('category_id', sa.UUID(), autoincrement=False, nullable=True, comment='设备分类'),
        schema='equipment',
    )

    # 2. 从联结表恢复第一个分类到 category_id
    op.execute(
        "UPDATE equipment.equipments e "
        "SET category_id = l.category_id "
        "FROM equipment.equipment_category_links l "
        "WHERE e.id = l.equipment_id AND l.is_deleted = false "
        "AND l.created_at = ("
        "  SELECT MIN(l2.created_at) FROM equipment.equipment_category_links l2 "
        "  WHERE l2.equipment_id = e.id AND l2.is_deleted = false"
        ")"
    )

    # 3. 恢复外键
    op.create_foreign_key(
        op.f('equipments_category_id_fkey'), 'equipments', 'equipment_categories',
        ['category_id'], ['id'],
        source_schema='equipment', referent_schema='equipment',
    )

    # 4. 删除联结表
    op.drop_table('equipment_category_links', schema='equipment')
