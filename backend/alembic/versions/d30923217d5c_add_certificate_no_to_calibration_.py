"""add certificate_no to calibration_reports

Revision ID: d30923217d5c
Revises: c20d75e382ef
Create Date: 2026-08-28 12:27:24.611017
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd30923217d5c'
down_revision: str | None = 'c20d75e382ef'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS meter")
    op.add_column(
        'calibration_reports',
        sa.Column('certificate_no', sa.String(length=100), nullable=True,
                  comment='证书编号（未删除报告中全局唯一）'),
        schema='meter',
    )
    op.create_index(
        'ix_calibration_reports_certificate_no_active',
        'calibration_reports',
        ['certificate_no'],
        unique=True,
        schema='meter',
        postgresql_where=sa.text('is_deleted = false'),
    )


def downgrade() -> None:
    op.drop_index(
        'ix_calibration_reports_certificate_no_active',
        table_name='calibration_reports',
        schema='meter',
        postgresql_where=sa.text('is_deleted = false'),
    )
    op.drop_column('calibration_reports', 'certificate_no', schema='meter')
