"""add department_id to equipment_categories and locations

Revision ID: 0fac3372e248
Revises: f103dadd0ecd
Create Date: 2026-06-27 17:36:40.886378
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0fac3372e248'
down_revision: Union[str, None] = 'f103dadd0ecd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── equipment_categories: 添加 department_id，更新唯一索引 ──
    op.add_column(
        'equipment_categories',
        sa.Column(
            'department_id', sa.Uuid(), nullable=True,
            comment='归属部门ID，逻辑引用 identity.departments.id',
        ),
        schema='equipment',
    )
    op.drop_index(
        op.f('uq_equipment_categories_code'),
        table_name='equipment_categories',
        schema='equipment',
        postgresql_where='(is_deleted = false)',
    )
    op.create_index(
        'uq_equipment_categories_code_dept',
        'equipment_categories',
        ['code', 'department_id'],
        unique=True,
        schema='equipment',
        postgresql_where=sa.text('is_deleted = false'),
    )

    # ── locations: 添加 department_id，更新唯一索引 ──
    op.add_column(
        'locations',
        sa.Column(
            'department_id', sa.Uuid(), nullable=True,
            comment='归属部门ID，逻辑引用 identity.departments.id',
        ),
        schema='equipment',
    )
    op.drop_index(
        op.f('uq_locations_code'),
        table_name='locations',
        schema='equipment',
        postgresql_where='(is_deleted = false)',
    )
    op.create_index(
        'uq_locations_code_dept',
        'locations',
        ['code', 'department_id'],
        unique=True,
        schema='equipment',
        postgresql_where=sa.text('is_deleted = false'),
    )


def downgrade() -> None:
    # ── locations: 回滚 ──
    op.drop_index(
        'uq_locations_code_dept',
        table_name='locations',
        schema='equipment',
        postgresql_where='(is_deleted = false)',
    )
    op.create_index(
        op.f('uq_locations_code'),
        'locations',
        ['code'],
        unique=True,
        schema='equipment',
        postgresql_where='(is_deleted = false)',
    )
    op.drop_column('locations', 'department_id', schema='equipment')

    # ── equipment_categories: 回滚 ──
    op.drop_index(
        'uq_equipment_categories_code_dept',
        table_name='equipment_categories',
        schema='equipment',
        postgresql_where='(is_deleted = false)',
    )
    op.create_index(
        op.f('uq_equipment_categories_code'),
        'equipment_categories',
        ['code'],
        unique=True,
        schema='equipment',
        postgresql_where='(is_deleted = false)',
    )
    op.drop_column('equipment_categories', 'department_id', schema='equipment')
