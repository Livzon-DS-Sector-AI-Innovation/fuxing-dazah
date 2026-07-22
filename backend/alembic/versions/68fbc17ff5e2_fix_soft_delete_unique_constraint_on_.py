"""fix soft-delete unique constraint on failure_codes and spare_parts

将 failure_symptoms, failure_causes, failure_actions, spare_parts,
equipment_spare_parts 的复合唯一约束改为部分唯一索引。

Revision ID: 68fbc17ff5e2
Revises: ee1cd432f041
Create Date: 2026-06-17 16:27:22.083063
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '68fbc17ff5e2'
down_revision: Union[str, None] = 'ee1cd432f041'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = [
    ('failure_symptoms',      'uq_failure_symptoms_code',      ['code']),
    ('failure_causes',        'uq_failure_causes_code',        ['code']),
    ('failure_actions',       'uq_failure_actions_code',       ['code']),
    ('spare_parts',           'uq_spare_parts_code',           ['code']),
    ('equipment_spare_parts', 'uq_equipment_spare_parts_eq_sp', ['equipment_id', 'spare_part_id']),
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
