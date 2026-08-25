"""add unique constraint on intermediate batch no

Revision ID: 77804745dd04
Revises: 82071259e84c
Create Date: 2026-08-21 14:29:54.710542
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '77804745dd04'
down_revision: Union[str, None] = '82071259e84c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 历史数据可能存在重复批号（此前留空默认取批次号，同批多步骤会重复）：
    # 建唯一索引前先为每组重复行（保留最早一条）追加短 id 后缀去重
    op.execute(
        """
        UPDATE production.batch_intermediate_outputs AS o
        SET intermediate_batch_no = substring(d.base_no from 1 for 90)
            || '-' || substr(o.id::text, 1, 8)
        FROM (
            SELECT id, intermediate_batch_no AS base_no,
                   ROW_NUMBER() OVER (
                       PARTITION BY intermediate_batch_no
                       ORDER BY created_at, id
                   ) AS rn
            FROM production.batch_intermediate_outputs
            WHERE is_deleted = false AND intermediate_batch_no IS NOT NULL
        ) AS d
        WHERE o.id = d.id AND d.rn > 1
        """
    )
    op.create_index(
        'uq_production_outputs_batch_no',
        'batch_intermediate_outputs',
        ['intermediate_batch_no'],
        unique=True,
        schema='production',
        postgresql_where=sa.text('is_deleted = false'),
    )


def downgrade() -> None:
    op.drop_index(
        'uq_production_outputs_batch_no',
        table_name='batch_intermediate_outputs',
        schema='production',
        postgresql_where=sa.text('is_deleted = false'),
    )
