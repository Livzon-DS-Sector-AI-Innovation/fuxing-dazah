"""add_key_risk_operation_reports

Revision ID: 26ef86e65dbe
Revises: d2e3f4a5b6c7
Create Date: 2026-08-05 16:04:13.982638
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '26ef86e65dbe'
down_revision: Union[str, None] = 'd2e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS safety")
    op.create_table('key_risk_operation_reports',
    sa.Column('report_no', sa.String(length=64), nullable=False, comment='申请编号文本（如 202511280372）'),
    sa.Column('approval_no_url', sa.String(length=500), nullable=True, comment='申请编号链接'),
    sa.Column('source', sa.String(length=16), server_default='bitable', nullable=False, comment='数据来源: bitable(飞书同步)'),
    sa.Column('feishu_record_id', sa.String(length=64), nullable=True, comment='飞书 Bitable 记录 ID（同步主键）'),
    sa.Column('apply_status', sa.String(length=16), nullable=True, comment='申请状态: 已通过/审批中/已拒绝/已取消/已终止/已撤回'),
    sa.Column('approval_node', sa.String(length=100), nullable=True, comment='审批节点'),
    sa.Column('approval_flow', sa.String(length=100), nullable=True, comment='审批流程名称'),
    sa.Column('current_handler', sa.String(length=100), nullable=True, comment='当前处理人'),
    sa.Column('initiator_name', sa.String(length=100), nullable=True, comment='发起人姓名'),
    sa.Column('initiator_department', sa.String(length=100), nullable=True, comment='发起人部门'),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True, comment='发起时间'),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True, comment='完成时间'),
    sa.Column('department', sa.String(length=100), nullable=True, comment='部门'),
    sa.Column('area', sa.String(length=255), nullable=True, comment='区域'),
    sa.Column('operation_content', sa.String(length=255), nullable=True, comment='作业内容'),
    sa.Column('start_time', sa.DateTime(timezone=True), nullable=True, comment='作业开始时间'),
    sa.Column('end_time', sa.DateTime(timezone=True), nullable=True, comment='作业结束时间'),
    sa.Column('duration_hours', sa.Float(), nullable=True, comment='作业时长（小时）'),
    sa.Column('notes', sa.Text(), nullable=True, comment='备注'),
    sa.Column('personal_protection', sa.Text(), nullable=True, comment='个人防护'),
    sa.Column('preparation_measures', sa.Text(), nullable=True, comment='准备措施'),
    sa.Column('operation_precautions', sa.Text(), nullable=True, comment='操作注意事项'),
    sa.Column('emergency_measures', sa.Text(), nullable=True, comment='应急措施'),
    sa.Column('guardian', sa.String(length=100), nullable=True, comment='现场作业监护人'),
    sa.Column('site_guardian', sa.String(length=100), nullable=True, comment='现场监护人（User）'),
    sa.Column('dept_safety_officer', sa.String(length=100), nullable=True, comment='部门安全员（User）'),
    sa.Column('operations', sa.JSON(), nullable=True, comment='附加作业块数组[{department,area,operation_content,personal_protection,preparation_measures,operation_precautions,emergency_measures,guardian,time_slot}]'),
    sa.Column('phase_before', sa.JSON(), nullable=True, comment='作业前现场确认 {date,photo_url,issue_desc}'),
    sa.Column('phase_ongoing', sa.JSON(), nullable=True, comment='作业中现场确认 {date,photo_url,issue_desc}'),
    sa.Column('phase_after', sa.JSON(), nullable=True, comment='作业后现场确认 {date,photo_url,issue_desc}'),
    sa.Column('source_id', sa.String(length=255), nullable=True, comment='飞书 SourceID'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='safety'
    )
    op.create_index('ix_key_risk_op_feishu_record_id', 'key_risk_operation_reports', ['feishu_record_id'], unique=False, schema='safety', postgresql_where=sa.text('is_deleted = false'))
    op.create_index('uq_key_risk_operation_reports_no', 'key_risk_operation_reports', ['report_no'], unique=True, schema='safety', postgresql_where=sa.text('is_deleted = false'))


def downgrade() -> None:
    op.drop_index('uq_key_risk_operation_reports_no', table_name='key_risk_operation_reports', schema='safety', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('ix_key_risk_op_feishu_record_id', table_name='key_risk_operation_reports', schema='safety', postgresql_where=sa.text('is_deleted = false'))
    op.drop_table('key_risk_operation_reports', schema='safety')
