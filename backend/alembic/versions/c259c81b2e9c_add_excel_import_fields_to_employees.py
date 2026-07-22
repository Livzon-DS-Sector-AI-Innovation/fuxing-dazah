"""add excel import fields to employees

Revision ID: c259c81b2e9c
Revises: 95788739338f
Create Date: 2026-07-09 17:05:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c259c81b2e9c'
down_revision: Union[str, None] = '95788739338f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('employees', sa.Column('duty', sa.String(length=64), nullable=True, comment='职务'), schema='hr')
    op.add_column('employees', sa.Column('dept_manager', sa.String(length=64), nullable=True, comment='部门管理者'), schema='hr')
    op.add_column('employees', sa.Column('additional_manager', sa.String(length=64), nullable=True, comment='额外管理者'), schema='hr')
    op.add_column('employees', sa.Column('report_grade', sa.String(length=32), nullable=True, comment='报表用职级'), schema='hr')
    op.add_column('employees', sa.Column('dept_head_trainer', sa.String(length=64), nullable=True, comment='部门负责人/一级培训师'), schema='hr')
    op.add_column('employees', sa.Column('safety_training_date', sa.Date(), nullable=True, comment='入职安全培训日期'), schema='hr')
    op.add_column('employees', sa.Column('safety_training_score', sa.String(length=32), nullable=True, comment='入职安全培训成绩'), schema='hr')
    op.add_column('employees', sa.Column('culture_training_date', sa.Date(), nullable=True, comment='企业文化培训日期'), schema='hr')
    op.add_column('employees', sa.Column('gmp_training_date', sa.Date(), nullable=True, comment='GMP基础培训时间'), schema='hr')
    op.add_column('employees', sa.Column('departure_date', sa.Date(), nullable=True, comment='离职时间'), schema='hr')


def downgrade() -> None:
    op.drop_column('employees', 'departure_date', schema='hr')
    op.drop_column('employees', 'gmp_training_date', schema='hr')
    op.drop_column('employees', 'culture_training_date', schema='hr')
    op.drop_column('employees', 'safety_training_score', schema='hr')
    op.drop_column('employees', 'safety_training_date', schema='hr')
    op.drop_column('employees', 'dept_head_trainer', schema='hr')
    op.drop_column('employees', 'report_grade', schema='hr')
    op.drop_column('employees', 'additional_manager', schema='hr')
    op.drop_column('employees', 'dept_manager', schema='hr')
    op.drop_column('employees', 'duty', schema='hr')
