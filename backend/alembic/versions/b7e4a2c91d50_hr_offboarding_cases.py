"""hr 离职管理：办结单/清退明细/保存视图/导出留痕四表 + 离职台账证明开具时间列

1. hr.offboarding_cases 离职办结单（状态机主干，一次离职一行；
   case_no 唯一；cert_sign 沿用 departure_records.cert_sign_*，本表经
   departure_record_id 逻辑关联，不带外键——仓库惯例）
2. hr.offboarding_clearance_items 清退交接明细（四部门维度+扣补金额）
3. hr.departure_saved_views 离职台账保存视图（个人维度）
4. hr.export_logs 台账导出留痕（通用设计，module 区分）
5. departure_records 加 cert_issued_at（证明开具时间，联动回写+筛选）

Revision ID: b7e4a2c91d50
Revises: 31877707aa99
Create Date: 2026-11-25 10:30:00.000000
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b7e4a2c91d50'
down_revision: str | None = '31877707aa99'
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        'offboarding_cases',
        sa.Column('case_no', sa.String(32), nullable=False, comment='申请编号（LB-YYYYMMDD-XXXX）'),
        sa.Column('employee_id', sa.Uuid(), nullable=False, comment='员工档案ID（逻辑关联，无外键）'),
        sa.Column('departure_record_id', sa.Uuid(), nullable=True, comment='关联离职台账记录ID（发起时 upsert 建立，逻辑关联）'),
        sa.Column('employee_number', sa.String(32), nullable=False, comment='工号'),
        sa.Column('name', sa.String(64), nullable=False, comment='姓名'),
        sa.Column('department', sa.String(64), nullable=False, comment='部门'),
        sa.Column('position', sa.String(64), nullable=True, comment='岗位'),
        sa.Column('level', sa.String(32), nullable=True, comment='级别（职级路由快照）'),
        sa.Column('initiator_name', sa.String(64), nullable=True, comment='发起人姓名快照（台账「发起人」列）'),
        sa.Column('offboarding_date', sa.Date(), nullable=False, comment='离职日期'),
        sa.Column('offboarding_type', sa.String(16), nullable=False, server_default='辞职', comment='离职类型: 辞职/辞退/合同到期/退休/其他'),
        sa.Column('reason', sa.String(512), nullable=True, comment='离职原因'),
        sa.Column('employee_category', sa.String(64), nullable=True, comment='用工类型（员工性质快照）'),
        sa.Column('application_submitted', sa.Boolean(), nullable=False, server_default='true', comment='是否递交离职申请'),
        sa.Column('status', sa.String(24), nullable=False, server_default='draft', comment='状态: draft/approving/clearing/cert_issuing/delivering/signed/closed/canceled'),
        sa.Column('approval_track', sa.String(16), nullable=True, comment='审批轨: staff/director（按 level 前缀路由）'),
        sa.Column('approval_attempt', sa.Integer(), nullable=False, server_default='0', comment='审批发起次数（两阶段共用计数，幂等键后缀，撤销后重发递增）'),
        sa.Column('resignation_instance_code', sa.String(64), nullable=True, comment='离职审批飞书实例 Code'),
        sa.Column('resignation_finished_at', sa.DateTime(timezone=True), nullable=True, comment='离职审批办结时间'),
        sa.Column('clearance_instance_code', sa.String(64), nullable=True, comment='清退交接飞书实例 Code'),
        sa.Column('clearance_finished_at', sa.DateTime(timezone=True), nullable=True, comment='清退会签办结时间'),
        sa.Column('health_check_required', sa.Boolean(), nullable=False, server_default='false', comment='是否需离岗体检（取员工 is_key_position，可改）'),
        sa.Column('health_check_done', sa.Boolean(), nullable=False, server_default='false', comment='离岗体检已完成登记'),
        sa.Column('health_check_date', sa.Date(), nullable=True, comment='离岗体检完成日期'),
        sa.Column('health_check_file_key', sa.String(256), nullable=True, comment='体检报告对象存储 key'),
        sa.Column('health_check_file_name', sa.String(255), nullable=True, comment='体检报告原始文件名'),
        sa.Column('cert_template', sa.String(16), nullable=True, comment='证明模板: electronic 电子单张（链接线上签收）/ paper 纸质两联（当面签收）'),
        sa.Column('cert_issued_at', sa.DateTime(timezone=True), nullable=True, comment='证明开具时间'),
        sa.Column('cert_storage_key', sa.String(256), nullable=True, comment='证明 PDF 对象存储 key'),
        sa.Column('cert_issued_by', sa.String(64), nullable=True, comment='开具人（HR 经办人姓名快照）'),
        sa.Column('mail_recipient', sa.String(128), nullable=True, comment='送达邮箱'),
        sa.Column('mail_sent_at', sa.DateTime(timezone=True), nullable=True, comment='邮件发送时间'),
        sa.Column('mail_status', sa.String(16), nullable=True, comment='邮件状态: sent/failed'),
        sa.Column('sms_phone', sa.String(32), nullable=True, comment='短信接收号码（送达留痕）'),
        sa.Column('sms_status', sa.String(16), nullable=True, comment='短信状态: sent/not_configured/failed（通道预留）'),
        sa.Column('delivery_channel', sa.String(16), nullable=True, comment='签收渠道: mail/sms/paper'),
        sa.Column('paper_signed_at', sa.DateTime(timezone=True), nullable=True, comment='纸质证明当面签收时间'),
        sa.Column('paper_signed_by', sa.String(64), nullable=True, comment='纸质证明签收人（员工本人）'),
        sa.Column('account_deactivated', sa.Boolean(), nullable=False, server_default='false', comment='飞书账号已注销（HR 办结时勾选确认）'),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True, comment='办结时间'),
        sa.Column('remark', sa.String(512), nullable=True, comment='备注'),
        sa.Column('id', sa.Uuid(), autoincrement=False, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='hr',
    )
    op.create_index('uq_offboarding_cases_case_no', 'offboarding_cases', ['case_no'], unique=True, schema='hr')
    op.create_index('ix_offboarding_cases_employee_id', 'offboarding_cases', ['employee_id'], schema='hr')
    op.create_index('ix_offboarding_cases_status', 'offboarding_cases', ['status'], schema='hr')
    op.create_index('ix_offboarding_cases_department', 'offboarding_cases', ['department'], schema='hr')
    op.create_index('ix_offboarding_cases_offboarding_date', 'offboarding_cases', ['offboarding_date'], schema='hr')

    op.create_table(
        'offboarding_clearance_items',
        sa.Column('case_id', sa.Uuid(), nullable=False, comment='所属离职办结单ID（逻辑关联）'),
        sa.Column('category', sa.String(16), nullable=False, comment='部门维度: admin/finance/hr/work'),
        sa.Column('item_name', sa.String(64), nullable=False, comment='清退事项'),
        sa.Column('status', sa.String(16), nullable=False, server_default='pending', comment='状态: pending/confirmed/deducted'),
        sa.Column('deduction_amount', sa.Numeric(12, 2), nullable=True, comment='扣款金额'),
        sa.Column('supplement_amount', sa.Numeric(12, 2), nullable=True, comment='补发金额'),
        sa.Column('remark', sa.String(255), nullable=True, comment='备注'),
        sa.Column('confirmed_by', sa.String(64), nullable=True, comment='确认人（经办人姓名）'),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True, comment='确认时间'),
        sa.Column('source', sa.String(16), nullable=False, server_default='manual', comment='来源: manual 平台登记 / feishu_form 实例回读'),
        sa.Column('id', sa.Uuid(), autoincrement=False, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='hr',
    )
    op.create_index('ix_clearance_items_case', 'offboarding_clearance_items', ['case_id'], schema='hr')
    op.create_index('ix_clearance_items_category', 'offboarding_clearance_items', ['category'], schema='hr')

    op.create_table(
        'departure_saved_views',
        sa.Column('owner_user_id', sa.Uuid(), nullable=False, comment='归属用户ID'),
        sa.Column('name', sa.String(64), nullable=False, comment='视图名称'),
        sa.Column('filters', JSON, nullable=True, comment='筛选条件（键=后端筛选参数名）'),
        sa.Column('columns', JSON, nullable=True, comment='导出字段 key 列表'),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false', comment='默认视图'),
        sa.Column('id', sa.Uuid(), autoincrement=False, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='hr',
    )
    op.create_index('ix_departure_views_owner', 'departure_saved_views', ['owner_user_id'], schema='hr')

    op.create_table(
        'export_logs',
        sa.Column('module', sa.String(32), nullable=False, comment='台账: departure 起步'),
        sa.Column('operator_id', sa.Uuid(), nullable=True, comment='操作人用户ID'),
        sa.Column('operator_name', sa.String(64), nullable=True, comment='操作人姓名'),
        sa.Column('filters', JSON, nullable=True, comment='筛选条件'),
        sa.Column('columns', JSON, nullable=True, comment='导出字段'),
        sa.Column('row_count', sa.Integer(), nullable=False, server_default='0', comment='导出条数'),
        sa.Column('note', sa.Text(), nullable=True, comment='备注'),
        sa.Column('id', sa.Uuid(), autoincrement=False, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='hr',
    )
    op.create_index('ix_export_logs_module', 'export_logs', ['module'], schema='hr')
    op.create_index('ix_export_logs_created_at', 'export_logs', ['created_at'], schema='hr')

    op.add_column(
        'departure_records',
        sa.Column('cert_issued_at', sa.DateTime(timezone=True), nullable=True,
                  comment='解除劳动关系证明开具时间（离职办理流程回写）'),
        schema='hr',
    )


def downgrade() -> None:
    op.drop_column('departure_records', 'cert_issued_at', schema='hr')
    op.drop_index('ix_export_logs_created_at', table_name='export_logs', schema='hr')
    op.drop_index('ix_export_logs_module', table_name='export_logs', schema='hr')
    op.drop_table('export_logs', schema='hr')
    op.drop_index('ix_departure_views_owner', table_name='departure_saved_views', schema='hr')
    op.drop_table('departure_saved_views', schema='hr')
    op.drop_index('ix_clearance_items_category', table_name='offboarding_clearance_items', schema='hr')
    op.drop_index('ix_clearance_items_case', table_name='offboarding_clearance_items', schema='hr')
    op.drop_table('offboarding_clearance_items', schema='hr')
    op.drop_index('ix_offboarding_cases_offboarding_date', table_name='offboarding_cases', schema='hr')
    op.drop_index('ix_offboarding_cases_department', table_name='offboarding_cases', schema='hr')
    op.drop_index('ix_offboarding_cases_status', table_name='offboarding_cases', schema='hr')
    op.drop_index('ix_offboarding_cases_employee_id', table_name='offboarding_cases', schema='hr')
    op.drop_index('uq_offboarding_cases_case_no', table_name='offboarding_cases', schema='hr')
    op.drop_table('offboarding_cases', schema='hr')
