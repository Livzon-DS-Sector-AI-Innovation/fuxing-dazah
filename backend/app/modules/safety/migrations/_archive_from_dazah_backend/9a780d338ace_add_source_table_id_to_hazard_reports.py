"""add source_table_id to hazard_reports

Revision ID: 9a780d338ace
Revises: a1b2c3d4e5f7
Create Date: 2026-07-14 09:16:22.732821

安全模块隐患接入新多维表格：新增 source_table_id 标记来源 Bitable 数据表，
用于隔离不同表格来源的记录、防止回写串表。仅本模块 DDL（手工清理 autogenerate
混入的其他模块无关漂移）。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9a780d338ace'
down_revision: str | None = 'a1b2c3d4e5f7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'hazard_reports',
        sa.Column(
            'source_table_id',
            sa.String(length=64),
            nullable=True,
            comment='来源 Bitable 数据表 ID（区分不同多维表格来源，隔离回写目标，防止串表）',
        ),
        schema='safety',
    )
    op.create_index(
        'ix_hazard_reports_source_table_id',
        'hazard_reports',
        ['source_table_id'],
        unique=False,
        schema='safety',
    )


def downgrade() -> None:
    op.drop_index(
        'ix_hazard_reports_source_table_id',
        table_name='hazard_reports',
        schema='safety',
    )
    op.drop_column('hazard_reports', 'source_table_id', schema='safety')
