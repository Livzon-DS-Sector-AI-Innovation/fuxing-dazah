"""add sort_order to instrument_records and gas_detector_records

Revision ID: 1c3d4968c09c
Revises: 7419e6f7039e
Create Date: 2026-07-10 15:20:09.046570
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1c3d4968c09c'
down_revision: Union[str, None] = '7419e6f7039e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 新增 sort_order 列，替换废弃的 pinned_at 列
    op.add_column(
        'instrument_records',
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False,
                  comment='排序序号（Excel 行顺序）'),
        schema='meter',
    )
    op.drop_column('instrument_records', 'pinned_at', schema='meter')

    op.add_column(
        'gas_detector_records',
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False,
                  comment='排序序号（Excel 行顺序）'),
        schema='meter',
    )
    op.drop_column('gas_detector_records', 'pinned_at', schema='meter')

    # 回填已有数据：按 id 排序赋予递增序号，保证现网数据有合理默认值
    op.execute("""
        WITH numbered AS (
            SELECT id, ROW_NUMBER() OVER (ORDER BY id) AS rn
            FROM meter.instrument_records
            WHERE is_deleted = false
        )
        UPDATE meter.instrument_records SET sort_order = numbered.rn
        FROM numbered WHERE instrument_records.id = numbered.id
    """)
    op.execute("""
        WITH numbered AS (
            SELECT id, ROW_NUMBER() OVER (ORDER BY id) AS rn
            FROM meter.gas_detector_records
            WHERE is_deleted = false
        )
        UPDATE meter.gas_detector_records SET sort_order = numbered.rn
        FROM numbered WHERE gas_detector_records.id = numbered.id
    """)


def downgrade() -> None:
    op.add_column(
        'instrument_records',
        sa.Column('pinned_at', sa.DateTime(timezone=True), nullable=True,
                  comment='最近一次上传报告的时间（用于列表置顶）'),
        schema='meter',
    )
    op.drop_column('instrument_records', 'sort_order', schema='meter')

    op.add_column(
        'gas_detector_records',
        sa.Column('pinned_at', sa.DateTime(timezone=True), nullable=True,
                  comment='最近一次上传报告的时间（用于列表置顶）'),
        schema='meter',
    )
    op.drop_column('gas_detector_records', 'sort_order', schema='meter')
