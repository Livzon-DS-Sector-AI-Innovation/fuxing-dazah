"""quality: report_records serial_no unique index

Revision ID: d4819835e97d
Revises: 2edb80e50226
Create Date: 2026-09-20 17:42:40.212677
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd4819835e97d'
down_revision: Union[str, None] = '2edb80e50226'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 流水号唯一索引（并发生成 COA 时数据库兜底防重号；历史空号记录不受约束）
    op.create_index(
        'uq_quality_report_record_serial',
        'report_records',
        ['serial_no'],
        unique=True,
        schema='quality',
        postgresql_where=sa.text('serial_no IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index(
        'uq_quality_report_record_serial',
        table_name='report_records',
        schema='quality',
        postgresql_where=sa.text('serial_no IS NOT NULL'),
    )
