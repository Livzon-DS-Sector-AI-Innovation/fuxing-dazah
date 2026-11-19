"""qa coa: 报告头动态批次字段值（batch_data JSONB，key=模板生效字段 key）

Revision ID: d7b3f2a9c4e1
Revises: c5e8f1a3b7d2
Create Date: 2026-11-18 16:40:00.000000

出具登记页按模板字段集动态渲染批次信息列：字段键命中报告固定列别名
（生产日期/有效期/包装/批量/贮存/结论）的仍镜像写固定列，其余存本列。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd7b3f2a9c4e1'
down_revision: str | None = 'c5e8f1a3b7d2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'coa_reports',
        sa.Column(
            'batch_data',
            JSONB(),
            nullable=True,
            comment='模板动态批次字段值（key=生效字段集 key；固定列别名键镜像写固定列）',
        ),
        schema='qa',
    )


def downgrade() -> None:
    op.drop_column('coa_reports', 'batch_data', schema='qa')
