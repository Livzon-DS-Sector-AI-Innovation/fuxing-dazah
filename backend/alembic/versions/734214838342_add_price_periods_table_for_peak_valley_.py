"""add price_periods table for peak-valley config

Revision ID: 734214838342
Revises: 98926345fc1c
Create Date: 2026-08-05 10:56:16.622282
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '734214838342'
down_revision: Union[str, None] = '98926345fc1c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 默认峰谷时段规则
DEFAULT_PERIODS = [
    # 谷: 00:00-08:00 全年
    ("谷", 0, 8, list(range(1, 13))),
    # 平: 08:00-10:00, 12:00-15:00, 20:00-21:00, 22:00-24:00 全年
    ("平", 8, 10, list(range(1, 13))),
    ("平", 12, 15, list(range(1, 13))),
    ("平", 20, 21, list(range(1, 13))),
    ("平", 22, 24, list(range(1, 13))),
    # 峰: 10:00-11:00 全年
    ("峰", 10, 11, list(range(1, 13))),
    # 峰: 11:00-12:00 非夏季 (1-6, 10-12)
    ("峰", 11, 12, [1, 2, 3, 4, 5, 6, 10, 11, 12]),
    # 峰: 15:00-17:00 全年
    ("峰", 15, 17, list(range(1, 13))),
    # 峰: 17:00-18:00 非夏季
    ("峰", 17, 18, [1, 2, 3, 4, 5, 6, 10, 11, 12]),
    # 峰: 18:00-20:00 全年
    ("峰", 18, 20, list(range(1, 13))),
    # 峰: 21:00-22:00 全年
    ("峰", 21, 22, list(range(1, 13))),
    # 尖: 11:00-12:00 夏季 (7-9)
    ("尖", 11, 12, [7, 8, 9]),
    # 尖: 17:00-18:00 夏季
    ("尖", 17, 18, [7, 8, 9]),
]


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS energy")
    op.create_table(
        'price_periods',
        sa.Column('category', sa.String(length=10), nullable=False, comment='分类: 尖/峰/平/谷'),
        sa.Column('start_hour', sa.Integer(), nullable=False, comment='开始小时 (0-23, 含)'),
        sa.Column('end_hour', sa.Integer(), nullable=False, comment='结束小时 (1-24, 不含)'),
        sa.Column('months', postgresql.ARRAY(sa.Integer()), nullable=False, comment='适用月份, 如 [7,8,9]'),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.text('false'), comment='软删除标记'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id']),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id']),
        sa.PrimaryKeyConstraint('id'),
        schema='energy'
    )

    # 插入默认规则
    from uuid import uuid4
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    period_table = sa.table(
        'price_periods',
        sa.column('id', sa.Uuid()),
        sa.column('category', sa.String()),
        sa.column('start_hour', sa.Integer()),
        sa.column('end_hour', sa.Integer()),
        sa.column('months', postgresql.ARRAY(sa.Integer())),
        sa.column('is_deleted', sa.Boolean()),
        sa.column('created_at', sa.DateTime(timezone=True)),
        sa.column('updated_at', sa.DateTime(timezone=True)),
        schema='energy',
    )
    op.bulk_insert(
        period_table,
        [
            {
                "id": uuid4(), "category": cat, "start_hour": sh, "end_hour": eh,
                "months": months, "is_deleted": False,
                "created_at": now, "updated_at": now,
            }
            for cat, sh, eh, months in DEFAULT_PERIODS
        ],
    )


def downgrade() -> None:
    op.drop_table('price_periods', schema='energy')
