"""add notification tracking fields to hazard_reports

Revision ID: d121aec51082
Revises: 9f02f3bfcdc1
Create Date: 2026-06-24 16:15:02.828827
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd121aec51082'
down_revision: str | None = '9f02f3bfcdc1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(table: str, column: str, schema: str) -> bool:
    conn = op.get_bind()
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :table AND column_name = :column"
        ),
        {"schema": schema, "table": table, "column": column},
    ).first()
    return row is not None


def _add_column_if_missing(table: str, column: sa.Column, *, schema: str) -> None:
    if not _column_exists(table, column.name, schema):
        op.add_column(table, column, schema=schema)


def upgrade() -> None:
    _add_column_if_missing('hazard_reports', sa.Column('rectification_notified_at', sa.DateTime(timezone=True), nullable=True, comment='整改通知最近发送时间'), schema='safety')
    _add_column_if_missing('hazard_reports', sa.Column('rectification_notify_status', sa.String(16), nullable=True, comment='整改通知状态: success / failed'), schema='safety')
    _add_column_if_missing('hazard_reports', sa.Column('rectification_notify_error', sa.Text(), nullable=True, comment='整改通知失败原因'), schema='safety')
    _add_column_if_missing('hazard_reports', sa.Column('review_notified_at', sa.DateTime(timezone=True), nullable=True, comment='复核通知最近发送时间'), schema='safety')
    _add_column_if_missing('hazard_reports', sa.Column('review_notified_level', sa.Integer(), nullable=True, comment='复核通知级别: 1/2/3'), schema='safety')
    _add_column_if_missing('hazard_reports', sa.Column('review_notify_status', sa.String(16), nullable=True, comment='复核通知状态: success / failed'), schema='safety')
    _add_column_if_missing('hazard_reports', sa.Column('review_notify_error', sa.Text(), nullable=True, comment='复核通知失败原因'), schema='safety')


def downgrade() -> None:
    op.drop_column('hazard_reports', 'review_notify_error', schema='safety')
    op.drop_column('hazard_reports', 'review_notify_status', schema='safety')
    op.drop_column('hazard_reports', 'review_notified_level', schema='safety')
    op.drop_column('hazard_reports', 'review_notified_at', schema='safety')
    op.drop_column('hazard_reports', 'rectification_notify_error', schema='safety')
    op.drop_column('hazard_reports', 'rectification_notify_status', schema='safety')
    op.drop_column('hazard_reports', 'rectification_notified_at', schema='safety')
