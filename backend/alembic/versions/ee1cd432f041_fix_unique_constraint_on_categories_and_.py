"""fix soft-delete unique constraint to partial unique index

将 equipment 模块所有含 is_deleted 的复合唯一约束改为部分唯一索引，
解决：同名 code 软删除后无法再次软删除的问题。

涉及表：equipment_categories, locations, failure_symptoms,
        failure_causes, failure_actions, spare_parts, equipment_spare_parts

Revision ID: ee1cd432f041
Revises: 68024feea3d7
Create Date: 2026-06-17 16:13:06.598433
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ee1cd432f041'
down_revision: Union[str, None] = '68024feea3d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 需要修复的表及其约束名和列
_TABLES = [
    ('equipment_categories', 'uq_equipment_categories_code', ['code']),
    ('locations',             'uq_locations_code',             ['code']),
]


def upgrade() -> None:
    for table, constraint, columns in _TABLES:
        op.drop_constraint(constraint, table, schema='equipment', type_='unique')
        op.create_index(
            constraint, table, columns,
            unique=True, schema='equipment',
            postgresql_where=sa.text('is_deleted = false'),
        )


def downgrade() -> None:
    for table, constraint, columns in _TABLES:
        op.drop_index(
            constraint, table_name=table,
            schema='equipment', postgresql_where=sa.text('is_deleted = false'),
        )
        op.create_unique_constraint(
            constraint, table, [*columns, 'is_deleted'], schema='equipment',
        )
