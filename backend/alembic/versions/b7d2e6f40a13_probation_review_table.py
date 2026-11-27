"""add probation review table and employee.probation_end_date

Revision ID: b7d2e6f40a13
Revises: f3a9c5d80e47
Create Date: 2026-11-13 14:00:00.000000

试用期转正流程：员工表加转正到期日（延长时覆盖派生值），新表存
两级评估记录（部门负责人飞书评 → HR 确认生效）。同一员工仅一条进行中。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b7d2e6f40a13'
down_revision: Union[str, None] = 'f3a9c5d80e47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'probation_reviews'
_SCHEMA = 'hr'


def upgrade() -> None:
    # IF NOT EXISTS：开发库该列可能已被并行改动预先创建（共享库），幂等跳过
    op.execute(
        f"ALTER TABLE {_SCHEMA}.employees ADD COLUMN IF NOT EXISTS probation_end_date DATE"
    )
    op.execute(
        f"COMMENT ON COLUMN {_SCHEMA}.employees.probation_end_date IS "
        "'转正到期日（空=按入职+3月-1天派生；试用期延长时写入新日期）'"
    )
    op.create_table(_TABLE,
    sa.Column('employee_id', sa.Uuid(), nullable=False, comment='员工档案ID'),
    sa.Column('reviewer_name', sa.String(length=64), nullable=False, comment='评估人（部门负责人姓名）'),
    sa.Column('reviewer_open_id', sa.String(length=64), nullable=False, comment='评估人飞书open_id'),
    sa.Column('status', sa.String(length=16), nullable=False, server_default='pending_reviewer',
              comment='pending_reviewer待评估/pending_hr待HR确认/effective已生效/cancelled已取消'),
    sa.Column('conclusion', sa.String(length=8), nullable=True, comment='负责人结论: 通过/延长/不通过'),
    sa.Column('comment', sa.Text(), nullable=True, comment='负责人评语'),
    sa.Column('proposed_probation_end', sa.Date(), nullable=True, comment='延长时建议的新到期日'),
    sa.Column('hr_note', sa.String(length=256), nullable=True, comment='HR 确认附注'),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True, comment='负责人提交时间'),
    sa.Column('reviewed_by', sa.String(length=64), nullable=True, comment='HR 确认人'),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True, comment='HR 确认时间'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['employee_id'], [f'{_SCHEMA}.employees.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema=_SCHEMA
    )
    op.create_index(
        'uq_pr_employee_active', _TABLE, ['employee_id'], unique=True, schema=_SCHEMA,
        postgresql_where=sa.text("status IN ('pending_reviewer', 'pending_hr') AND is_deleted = false"),
    )


def downgrade() -> None:
    op.drop_index('uq_pr_employee_active', table_name=_TABLE, schema=_SCHEMA)
    op.drop_table(_TABLE, schema=_SCHEMA)
    op.drop_column('employees', 'probation_end_date', schema=_SCHEMA)
