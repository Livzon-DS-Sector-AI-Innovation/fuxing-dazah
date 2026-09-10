"""drop_daily_risk_reports

删除旧的每日风险作业报备表 daily_risk_reports（重构为 key_risk_operation_reports，
数据源迁移到飞书多维表格）。注意：此操作会删除旧手动填报数据，不可逆。

Revision ID: 3f9a7c1b5d2e
Revises: 26ef86e65dbe
Create Date: 2026-08-05 16:20:00.000000
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '3f9a7c1b5d2e'
down_revision: Union[str, None] = '26ef86e65dbe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table('daily_risk_reports', schema='safety')


def downgrade() -> None:
    # 不可逆（数据已删除），仅重建空表结构占位
    op.execute("CREATE SCHEMA IF NOT EXISTS safety")
    op.create_table(
        'daily_risk_reports',
        op.Column('report_no', op.String(64), nullable=False),
        op.Column('report_date', op.DateTime(timezone=True), nullable=False),
        op.Column('department', op.String(100), nullable=True),
        op.Column('hazard_identification_id', op.UUID(), nullable=True),
        op.Column('operation_description', op.Text(), nullable=False),
        op.Column('operation_steps', op.Text(), nullable=True),
        op.Column('hazard_factors', op.Text(), nullable=True),
        op.Column('risk_level', op.String(20), nullable=True),
        op.Column('control_measures', op.Text(), nullable=True),
        op.Column('responsible_person', op.String(100), nullable=True),
        op.Column('operator_count', op.Integer(), nullable=True),
        op.Column('location', op.String(255), nullable=True),
        op.Column('planned_start_time', op.DateTime(timezone=True), nullable=True),
        op.Column('planned_end_time', op.DateTime(timezone=True), nullable=True),
        op.Column('applicant_name', op.String(100), nullable=True),
        op.Column('approver_name', op.String(100), nullable=True),
        op.Column('approved_at', op.DateTime(timezone=True), nullable=True),
        op.Column('rejection_reason', op.Text(), nullable=True),
        op.Column('status', op.String(32), server_default='draft', nullable=False),
        op.Column('notes', op.Text(), nullable=True),
        op.Column('id', op.UUID(), nullable=False),
        op.Column('created_at', op.DateTime(timezone=True), server_default=op.text('now()'), nullable=False),
        op.Column('updated_at', op.DateTime(timezone=True), server_default=op.text('now()'), nullable=False),
        op.Column('created_by', op.UUID(), nullable=True),
        op.Column('updated_by', op.UUID(), nullable=True),
        op.Column('is_deleted', op.Boolean(), server_default='false', nullable=False),
        op.PrimaryKeyConstraint('id'),
        schema='safety',
    )
