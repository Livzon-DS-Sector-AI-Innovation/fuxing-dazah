"""add notification tracking fields to hazard_reports

Revision ID: d121aec51082
Revises: 9f02f3bfcdc1
Create Date: 2026-06-24 16:15:02.828827
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd121aec51082'
down_revision: Union[str, None] = '9f02f3bfcdc1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('hazard_reports', sa.Column('rectification_notified_at', sa.DateTime(timezone=True), nullable=True, comment='整改通知最近发送时间'), schema='safety')
    op.add_column('hazard_reports', sa.Column('rectification_notify_status', sa.String(16), nullable=True, comment='整改通知状态: success / failed'), schema='safety')
    op.add_column('hazard_reports', sa.Column('rectification_notify_error', sa.Text(), nullable=True, comment='整改通知失败原因'), schema='safety')
    op.add_column('hazard_reports', sa.Column('review_notified_at', sa.DateTime(timezone=True), nullable=True, comment='复核通知最近发送时间'), schema='safety')
    op.add_column('hazard_reports', sa.Column('review_notified_level', sa.Integer(), nullable=True, comment='复核通知级别: 1/2/3'), schema='safety')
    op.add_column('hazard_reports', sa.Column('review_notify_status', sa.String(16), nullable=True, comment='复核通知状态: success / failed'), schema='safety')
    op.add_column('hazard_reports', sa.Column('review_notify_error', sa.Text(), nullable=True, comment='复核通知失败原因'), schema='safety')


def downgrade() -> None:
    op.drop_column('hazard_reports', 'review_notify_error', schema='safety')
    op.drop_column('hazard_reports', 'review_notify_status', schema='safety')
    op.drop_column('hazard_reports', 'review_notified_level', schema='safety')
    op.drop_column('hazard_reports', 'review_notified_at', schema='safety')
    op.drop_column('hazard_reports', 'rectification_notify_error', schema='safety')
    op.drop_column('hazard_reports', 'rectification_notify_status', schema='safety')
    op.drop_column('hazard_reports', 'rectification_notified_at', schema='safety')
