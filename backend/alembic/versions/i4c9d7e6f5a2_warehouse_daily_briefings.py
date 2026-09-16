"""warehouse daily briefings

每日晨报表：聚合异常/补货建议/昨日出入库（brief_date 唯一，重生成覆盖）。

Revision ID: i4c9d7e6f5a2
Revises: g8b2c6d4e1f3
Create Date: 2026-09-16
"""
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'i4c9d7e6f5a2'
down_revision: str | None = 'g8b2c6d4e1f3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    ]


def _base_fks() -> list:
    return [
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id']),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id']),
        sa.PrimaryKeyConstraint('id'),
    ]


def upgrade() -> None:
    op.execute('CREATE SCHEMA IF NOT EXISTS warehouse')

    op.create_table('daily_briefings',
        sa.Column('brief_date', sa.Date(), nullable=False, comment='晨报业务日'),
        sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False, comment='晨报内容 JSON'),
        *_base_columns(), *_base_fks(),
        schema='warehouse',
    )
    op.create_index('uq_warehouse_daily_briefings_date', 'daily_briefings', ['brief_date'], unique=True, schema='warehouse', postgresql_where=sa.text('is_deleted = false'))


def downgrade() -> None:
    op.drop_index('uq_warehouse_daily_briefings_date', table_name='daily_briefings', schema='warehouse')
    op.drop_table('daily_briefings', schema='warehouse')
