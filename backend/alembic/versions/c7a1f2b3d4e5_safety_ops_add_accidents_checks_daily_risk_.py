"""safety ops: add accidents, safety_checks, daily_risk_reports, oh_hazard_monitors + hazard_reports.check_id

迁移安全模块补齐的 4 个业务域（事故/安全检查/每日风险作业报备/职业危害因素监测），
并为 hazard_reports 补 check_id 外键（隐患关联安全检查）。

Revision ID: c7a1f2b3d4e5
Revises: be9dee409a39
Create Date: 2026-09-10 20:10:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c7a1f2b3d4e5'
down_revision: Union[str, None] = 'be9dee409a39'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BASE_COLUMNS = [
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
]

_BASE_FKS = [
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
]


def upgrade() -> None:
    # ── accidents（事故登记）──
    op.create_table('accidents',
        sa.Column('accident_no', sa.String(length=64), nullable=False, comment='事故编号'),
        sa.Column('accident_type', sa.String(length=32), nullable=False, comment='事故类型'),
        sa.Column('accident_level', sa.String(length=32), server_default='general', nullable=False, comment='事故等级'),
        sa.Column('happened_at', sa.DateTime(timezone=True), nullable=False, comment='发生时间'),
        sa.Column('location', sa.String(length=255), nullable=True, comment='发生地点'),
        sa.Column('department', sa.String(length=100), nullable=True, comment='发生部门'),
        sa.Column('description', sa.Text(), nullable=False, comment='事故描述'),
        sa.Column('casualties', sa.String(length=255), nullable=True, comment='伤亡情况汇总'),
        sa.Column('property_damage', sa.Float(), nullable=True, comment='财产损失(元)'),
        sa.Column('loss_work_days', sa.Integer(), nullable=True, comment='损失工作日'),
        sa.Column('injury_details', sa.JSON(), nullable=True, comment='伤员详情 JSON'),
        sa.Column('investigation_team', sa.JSON(), nullable=True, comment='调查组 JSON'),
        sa.Column('investigation_method', sa.String(length=100), nullable=True, comment='调查方法'),
        sa.Column('investigation_findings', sa.Text(), nullable=True, comment='调查发现'),
        sa.Column('investigation_report_path', sa.String(length=500), nullable=True, comment='调查报告文件路径'),
        sa.Column('direct_cause', sa.Text(), nullable=True, comment='直接原因'),
        sa.Column('root_cause', sa.Text(), nullable=True, comment='根本原因'),
        sa.Column('handling_measures', sa.Text(), nullable=True, comment='处理措施'),
        sa.Column('corrective_actions', sa.Text(), nullable=True, comment='纠正预防措施'),
        sa.Column('corrective_action_deadline', sa.DateTime(timezone=True), nullable=True, comment='CAPA截止日期'),
        sa.Column('corrective_action_responsible', sa.String(length=100), nullable=True, comment='CAPA责任人'),
        sa.Column('corrective_action_status', sa.String(length=32), server_default='pending', nullable=True, comment='CAPA状态'),
        sa.Column('verified_by', sa.Uuid(), nullable=True, comment='CAPA验证人'),
        sa.Column('verified_by_name', sa.String(length=100), nullable=True, comment='验证人姓名'),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True, comment='验证时间'),
        sa.Column('status', sa.String(length=32), server_default='reported', nullable=False, comment='状态'),
        sa.Column('reported_by', sa.Uuid(), nullable=True, comment='报告人'),
        sa.Column('reported_by_name', sa.String(length=100), nullable=True, comment='报告人姓名'),
        sa.Column('reported_at', sa.DateTime(timezone=True), nullable=False, comment='报告时间'),
        sa.Column('investigator', sa.Uuid(), nullable=True, comment='调查人'),
        sa.Column('investigator_name', sa.String(length=100), nullable=True, comment='调查人姓名'),
        sa.Column('notes', sa.Text(), nullable=True, comment='备注'),
        *_BASE_COLUMNS,
        *_BASE_FKS,
        sa.ForeignKeyConstraint(['verified_by'], ['identity.users.id'], ),
        sa.ForeignKeyConstraint(['reported_by'], ['identity.users.id'], ),
        sa.ForeignKeyConstraint(['investigator'], ['identity.users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        schema='safety',
    )
    op.create_index('uq_accidents_accident_no', 'accidents', ['accident_no'], unique=True, postgresql_where=sa.text('is_deleted = false'), schema='safety')

    # ── safety_checks（安全检查）──
    op.create_table('safety_checks',
        sa.Column('check_no', sa.String(length=64), nullable=False, comment='检查编号'),
        sa.Column('check_type', sa.String(length=32), server_default='daily', nullable=False, comment='检查类型'),
        sa.Column('check_date', sa.DateTime(timezone=True), nullable=False, comment='检查日期'),
        sa.Column('department', sa.String(length=100), nullable=True, comment='检查部门'),
        sa.Column('inspector', sa.Uuid(), nullable=True, comment='检查人'),
        sa.Column('inspector_name', sa.String(length=100), nullable=True, comment='检查人姓名'),
        sa.Column('location', sa.String(length=255), nullable=True, comment='检查地点'),
        sa.Column('findings', sa.Text(), nullable=True, comment='检查发现'),
        sa.Column('result', sa.String(length=32), nullable=True, comment='检查结果'),
        sa.Column('rectification_required', sa.Boolean(), nullable=False, comment='是否需要整改'),
        sa.Column('rectification_deadline', sa.DateTime(timezone=True), nullable=True, comment='整改期限'),
        sa.Column('rectification_status', sa.String(length=32), server_default='pending', nullable=True, comment='整改进度'),
        sa.Column('inspector_confirmed', sa.Boolean(), server_default='false', nullable=False, comment='检查人员确认'),
        sa.Column('safety_officer_confirmed', sa.Boolean(), server_default='false', nullable=False, comment='安全办确认'),
        sa.Column('status', sa.String(length=32), server_default='draft', nullable=False, comment='状态'),
        sa.Column('notes', sa.Text(), nullable=True, comment='备注'),
        *_BASE_COLUMNS,
        *_BASE_FKS,
        sa.ForeignKeyConstraint(['inspector'], ['identity.users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        schema='safety',
    )
    op.create_index('uq_safety_checks_check_no', 'safety_checks', ['check_no'], unique=True, postgresql_where=sa.text('is_deleted = false'), schema='safety')

    # hazard_reports 关联安全检查
    op.add_column('hazard_reports',
        sa.Column('check_id', sa.Uuid(), nullable=True, comment='关联检查ID'),
        schema='safety',
    )
    op.create_foreign_key(
        'fk_hazard_reports_check_id_safety_checks',
        'hazard_reports', 'safety_checks',
        ['check_id'], ['id'],
        source_schema='safety', referent_schema='safety',
    )

    # ── daily_risk_reports（每日风险作业报备）──
    op.create_table('daily_risk_reports',
        sa.Column('report_no', sa.String(length=64), nullable=False, comment='报备编号'),
        sa.Column('report_date', sa.DateTime(timezone=True), nullable=False, comment='报备作业日期'),
        sa.Column('report_type', sa.String(length=20), server_default='regular', nullable=False, comment='报备类型: regular/non_regular'),
        sa.Column('department', sa.String(length=100), nullable=True, comment='报备部门'),
        sa.Column('hazard_identification_id', sa.Uuid(), nullable=True, comment='关联危险源辨识ID'),
        sa.Column('operation_description', sa.Text(), nullable=False, comment='风险作业描述'),
        sa.Column('operation_steps', sa.Text(), nullable=True, comment='作业步骤'),
        sa.Column('hazard_factors', sa.Text(), nullable=True, comment='危险因素'),
        sa.Column('risk_level', sa.String(length=20), nullable=True, comment='风险等级'),
        sa.Column('control_measures', sa.Text(), nullable=True, comment='控制措施'),
        sa.Column('responsible_person', sa.String(length=100), nullable=True, comment='作业负责人'),
        sa.Column('operator_count', sa.Integer(), nullable=True, comment='作业人数'),
        sa.Column('location', sa.String(length=255), nullable=True, comment='作业地点'),
        sa.Column('planned_start_time', sa.DateTime(timezone=True), nullable=True, comment='计划开始时间'),
        sa.Column('planned_end_time', sa.DateTime(timezone=True), nullable=True, comment='计划结束时间'),
        sa.Column('applicant_name', sa.String(length=100), nullable=True, comment='报备申请人姓名'),
        sa.Column('approver_name', sa.String(length=100), nullable=True, comment='审批人姓名'),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True, comment='审批时间'),
        sa.Column('rejection_reason', sa.Text(), nullable=True, comment='驳回原因'),
        sa.Column('status', sa.String(length=32), server_default='draft', nullable=False, comment='状态'),
        sa.Column('notes', sa.Text(), nullable=True, comment='备注'),
        *_BASE_COLUMNS,
        *_BASE_FKS,
        sa.ForeignKeyConstraint(['hazard_identification_id'], ['safety.hazard_identifications.id'], ),
        sa.PrimaryKeyConstraint('id'),
        schema='safety',
    )
    op.create_index('uq_daily_risk_reports_no', 'daily_risk_reports', ['report_no'], unique=True, postgresql_where=sa.text('is_deleted = false'), schema='safety')

    # ── oh_hazard_monitors（职业危害因素监测）──
    op.create_table('oh_hazard_monitors',
        sa.Column('monitor_no', sa.String(length=64), nullable=False, comment='监测编号'),
        sa.Column('workplace', sa.String(length=255), nullable=False, comment='监测场所/车间'),
        sa.Column('location', sa.String(length=255), nullable=True, comment='具体监测点位'),
        sa.Column('equipment_info', sa.String(length=255), nullable=True, comment='关联设备/岗位'),
        sa.Column('detection_type', sa.String(length=32), nullable=False, comment='检测类型'),
        sa.Column('detection_date', sa.DateTime(timezone=True), nullable=True, comment='检测日期'),
        sa.Column('detection_agency', sa.String(length=255), nullable=True, comment='检测机构'),
        sa.Column('status', sa.String(length=32), server_default='draft', nullable=False, comment='状态'),
        sa.Column('inspector_name', sa.String(length=100), nullable=True, comment='检测人员'),
        sa.Column('verifier_name', sa.String(length=100), nullable=True, comment='验证人员'),
        sa.Column('detection_results', sa.JSON(), nullable=True, comment='检测结果 JSON数组'),
        sa.Column('abnormality_records', sa.JSON(), nullable=True, comment='异常处置记录 JSON数组'),
        sa.Column('attachments', sa.JSON(), nullable=True, comment='附件列表 JSON数组'),
        sa.Column('notes', sa.Text(), nullable=True, comment='备注'),
        *_BASE_COLUMNS,
        *_BASE_FKS,
        sa.PrimaryKeyConstraint('id'),
        comment='职业危害因素监测表',
        schema='safety',
    )
    op.create_index('uq_oh_hazard_monitors_monitor_no', 'oh_hazard_monitors', ['monitor_no'], unique=True, postgresql_where=sa.text('is_deleted = false'), schema='safety')


def downgrade() -> None:
    op.drop_index('uq_oh_hazard_monitors_monitor_no', table_name='oh_hazard_monitors', schema='safety')
    op.drop_table('oh_hazard_monitors', schema='safety')
    op.drop_index('uq_daily_risk_reports_no', table_name='daily_risk_reports', schema='safety')
    op.drop_table('daily_risk_reports', schema='safety')
    op.drop_constraint('fk_hazard_reports_check_id_safety_checks', 'hazard_reports', type_='foreignkey', schema='safety')
    op.drop_column('hazard_reports', 'check_id', schema='safety')
    op.drop_index('uq_safety_checks_check_no', table_name='safety_checks', schema='safety')
    op.drop_table('safety_checks', schema='safety')
    op.drop_index('uq_accidents_accident_no', table_name='accidents', schema='safety')
    op.drop_table('accidents', schema='safety')
