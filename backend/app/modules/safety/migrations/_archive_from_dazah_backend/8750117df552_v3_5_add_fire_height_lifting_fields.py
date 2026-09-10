"""v3.5_add_fire_height_lifting_fields

Revision ID: 8750117df552
Revises: a356e7f1b1f9
Create Date: 2026-07-29 15:49:33.198693
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8750117df552'
down_revision: Union[str, None] = 'a356e7f1b1f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('special_operation_reports',
        sa.Column('fire_work_method', sa.String(length=64), nullable=True,
                  comment='动火方式: 电焊/气割/氩弧焊/切割机/电钻/塑料焊/其他'),
        schema='safety')
    op.add_column('special_operation_reports',
        sa.Column('height_work_method', sa.String(length=64), nullable=True,
                  comment='高处作业方式（多选）'),
        schema='safety')
    op.add_column('special_operation_reports',
        sa.Column('work_height', sa.Float(), nullable=True,
                  comment='作业高度(米)'),
        schema='safety')
    op.add_column('special_operation_reports',
        sa.Column('lifting_weight', sa.Float(), nullable=True,
                  comment='吊物质量(吨)'),
        schema='safety')
    op.add_column('special_operation_reports',
        sa.Column('contractor_name', sa.String(length=200), nullable=True,
                  comment='施工单位'),
        schema='safety')


def downgrade() -> None:
    op.drop_column('special_operation_reports', 'contractor_name', schema='safety')
    op.drop_column('special_operation_reports', 'lifting_weight', schema='safety')
    op.drop_column('special_operation_reports', 'work_height', schema='safety')
    op.drop_column('special_operation_reports', 'height_work_method', schema='safety')
    op.drop_column('special_operation_reports', 'fire_work_method', schema='safety')
