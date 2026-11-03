"""production node_assignments unique index add assigned_by

工序默认执行人按「配置人」各存一份（GET /node-assignments 与 MCP 候选名单
都按 assigned_by 过滤），唯一索引必须同口径，否则同工段的第二位负责人
无法把同一个人配成自己的默认执行人。

Revision ID: a7ad46fc8f5b
Revises: 7f0b3a5ce9d1
Create Date: 2026-10-09 16:57:18.103175
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a7ad46fc8f5b'
down_revision: Union[str, None] = '7f0b3a5ce9d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(
        op.f('uq_production_node_assignments'),
        table_name='node_assignments', schema='production',
        postgresql_where='(is_deleted = false)',
    )
    op.create_index(
        'uq_production_node_assignments', 'node_assignments',
        ['assigned_by', 'user_id', 'node_id'],
        unique=True, schema='production',
        postgresql_where=sa.text('is_deleted = false'),
    )


def downgrade() -> None:
    op.drop_index(
        'uq_production_node_assignments',
        table_name='node_assignments', schema='production',
        postgresql_where=sa.text('is_deleted = false'),
    )
    op.create_index(
        op.f('uq_production_node_assignments'), 'node_assignments',
        ['user_id', 'node_id'],
        unique=True, schema='production',
        postgresql_where='(is_deleted = false)',
    )
