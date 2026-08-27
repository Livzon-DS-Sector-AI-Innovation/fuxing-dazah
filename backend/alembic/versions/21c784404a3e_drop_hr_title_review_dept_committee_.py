"""drop hr title_review dept committee manager/leader columns

初审/终审环节由飞书审批与线下流程完成，不属于系统职责范围，
移除部门评审组遗留的 manager/leader 字段（业务从未使用，前端也不收集）。

Revision ID: 21c784404a3e
Revises: 18da7fa0b8f9
Create Date: 2026-08-27 08:52:12.941373
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '21c784404a3e'
down_revision: str | None = '18da7fa0b8f9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column('title_review_dept_committees', 'manager_employee_id', schema='hr')
    op.drop_column('title_review_dept_committees', 'manager_name', schema='hr')
    op.drop_column('title_review_dept_committees', 'leader_employee_id', schema='hr')
    op.drop_column('title_review_dept_committees', 'leader_name', schema='hr')


def downgrade() -> None:
    op.add_column(
        'title_review_dept_committees',
        sa.Column('manager_employee_id', sa.UUID(), nullable=True,
                  comment='部门负责人（初审人） hr.employees.id'),
        schema='hr',
    )
    op.add_column(
        'title_review_dept_committees',
        sa.Column('manager_name', sa.String(length=64), nullable=True, comment='负责人姓名'),
        schema='hr',
    )
    op.add_column(
        'title_review_dept_committees',
        sa.Column('leader_employee_id', sa.UUID(), nullable=True,
                  comment='分管领导（终审人） hr.employees.id'),
        schema='hr',
    )
    op.add_column(
        'title_review_dept_committees',
        sa.Column('leader_name', sa.String(length=64), nullable=True, comment='分管领导姓名'),
        schema='hr',
    )
