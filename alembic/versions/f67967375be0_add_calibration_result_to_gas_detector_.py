"""add_calibration_result_to_gas_detector_records

Revision ID: f67967375be0
Revises: fddc836e5ce6
Create Date: 2026-07-01 16:58:10.270907
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f67967375be0'
down_revision: Union[str, None] = 'fddc836e5ce6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('gas_detector_records',
                  sa.Column('calibration_result', sa.String(length=50), nullable=True, comment='检定结论'),
                  schema='meter')


def downgrade() -> None:
    op.drop_column('gas_detector_records', 'calibration_result', schema='meter')
