"""drop safety_checks and accidents tables

Revision ID: d7c5bc5fbaa8
Revises: 89ae7800d21a
Create Date: 2026-08-26 17:32:13.559323
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd7c5bc5fbaa8'
down_revision: str | None = '89ae7800d21a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── 先移除对 safety_checks 的外键引用列（否则无法 DROP 表）──
    op.drop_constraint(op.f('ehs_changes_linked_safety_check_id_fkey'), 'ehs_changes', schema='safety', type_='foreignkey')
    op.drop_column('ehs_changes', 'linked_safety_check_id', schema='safety')

    op.drop_constraint(op.f('hazard_reports_check_id_fkey'), 'hazard_reports', schema='safety', type_='foreignkey')
    op.drop_column('hazard_reports', 'check_id', schema='safety')

    op.drop_constraint(op.f('special_operation_permits_check_id_fkey'), 'special_operation_permits', schema='safety', type_='foreignkey')
    op.drop_column('special_operation_permits', 'check_id', schema='safety')

    # ── 移除「安全检查」「事故/事件」业务表 ──
    op.drop_index(op.f('uq_accidents_accident_no'), table_name='accidents', schema='safety', postgresql_where='(is_deleted = false)')
    op.drop_table('accidents', schema='safety')
    op.drop_index(op.f('uq_safety_checks_check_no'), table_name='safety_checks', schema='safety', postgresql_where='(is_deleted = false)')
    op.drop_table('safety_checks', schema='safety')


def downgrade() -> None:
    # ── 恢复对 safety_checks 的外键引用列 ──
    op.add_column('special_operation_permits', sa.Column('check_id', sa.UUID(), autoincrement=False, nullable=True, comment='关联安全检查ID'), schema='safety')
    op.create_foreign_key(op.f('special_operation_permits_check_id_fkey'), 'special_operation_permits', 'safety_checks', ['check_id'], ['id'], source_schema='safety', referent_schema='safety')

    op.add_column('hazard_reports', sa.Column('check_id', sa.UUID(), autoincrement=False, nullable=True, comment='关联检查ID'), schema='safety')
    op.create_foreign_key(op.f('hazard_reports_check_id_fkey'), 'hazard_reports', 'safety_checks', ['check_id'], ['id'], source_schema='safety', referent_schema='safety')

    op.add_column('ehs_changes', sa.Column('linked_safety_check_id', sa.UUID(), autoincrement=False, nullable=True, comment='关联安全检查ID（变更验收）'), schema='safety')
    op.create_foreign_key(op.f('ehs_changes_linked_safety_check_id_fkey'), 'ehs_changes', 'safety_checks', ['linked_safety_check_id'], ['id'], source_schema='safety', referent_schema='safety')

    # ── 恢复「安全检查」「事故/事件」业务表 ──
    op.create_table(
        'safety_checks',
        sa.Column('check_no', sa.VARCHAR(length=64), autoincrement=False, nullable=False, comment='检查编号'),
        sa.Column('check_type', sa.VARCHAR(length=32), server_default=sa.text("'daily'::character varying"), autoincrement=False, nullable=False, comment='检查类型'),
        sa.Column('check_date', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=False, comment='检查日期'),
        sa.Column('department', sa.VARCHAR(length=100), autoincrement=False, nullable=True, comment='检查部门'),
        sa.Column('inspector', sa.UUID(), autoincrement=False, nullable=True, comment='检查人'),
        sa.Column('inspector_name', sa.VARCHAR(length=100), autoincrement=False, nullable=True, comment='检查人姓名'),
        sa.Column('location', sa.VARCHAR(length=255), autoincrement=False, nullable=True, comment='检查地点'),
        sa.Column('findings', sa.TEXT(), autoincrement=False, nullable=True, comment='检查发现'),
        sa.Column('result', sa.VARCHAR(length=32), autoincrement=False, nullable=True, comment='检查结果: qualified/unqualified/need_rectification'),
        sa.Column('rectification_required', sa.BOOLEAN(), autoincrement=False, nullable=False, comment='是否需要整改'),
        sa.Column('rectification_deadline', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=True, comment='整改期限'),
        sa.Column('rectification_status', sa.VARCHAR(length=32), autoincrement=False, nullable=True, comment='整改进度'),
        sa.Column('inspector_confirmed', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False, comment='检查人员确认'),
        sa.Column('safety_officer_confirmed', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False, comment='安全办确认'),
        sa.Column('status', sa.VARCHAR(length=32), server_default=sa.text("'draft'::character varying"), autoincrement=False, nullable=False, comment='状态'),
        sa.Column('notes', sa.TEXT(), autoincrement=False, nullable=True, comment='备注'),
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.Column('created_by', sa.UUID(), autoincrement=False, nullable=True),
        sa.Column('updated_by', sa.UUID(), autoincrement=False, nullable=True),
        sa.Column('is_deleted', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], name=op.f('safety_checks_created_by_fkey')),
        sa.ForeignKeyConstraint(['inspector'], ['identity.users.id'], name=op.f('safety_checks_inspector_fkey')),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], name=op.f('safety_checks_updated_by_fkey')),
        sa.PrimaryKeyConstraint('id', name=op.f('safety_checks_pkey')),
        schema='safety',
    )
    op.create_index(op.f('uq_safety_checks_check_no'), 'safety_checks', ['check_no'], unique=True, schema='safety', postgresql_where='(is_deleted = false)')

    op.create_table(
        'accidents',
        sa.Column('accident_no', sa.VARCHAR(length=64), autoincrement=False, nullable=False, comment='事故编号'),
        sa.Column('accident_type', sa.VARCHAR(length=32), autoincrement=False, nullable=False, comment='事故类型'),
        sa.Column('accident_level', sa.VARCHAR(length=32), autoincrement=False, nullable=False, comment='事故等级'),
        sa.Column('happened_at', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=False, comment='发生时间'),
        sa.Column('location', sa.VARCHAR(length=255), autoincrement=False, nullable=True, comment='发生地点'),
        sa.Column('department', sa.VARCHAR(length=100), autoincrement=False, nullable=True, comment='发生部门'),
        sa.Column('description', sa.TEXT(), autoincrement=False, nullable=False, comment='事故描述'),
        sa.Column('casualties', sa.VARCHAR(length=255), autoincrement=False, nullable=True, comment='伤亡情况汇总'),
        sa.Column('property_damage', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True, comment='财产损失(元)'),
        sa.Column('loss_work_days', sa.INTEGER(), autoincrement=False, nullable=True, comment='损失工作日'),
        sa.Column('injury_details', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True, comment='伤员详情 JSON'),
        sa.Column('investigation_team', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True, comment='调查组 JSON'),
        sa.Column('investigation_method', sa.VARCHAR(length=100), autoincrement=False, nullable=True, comment='调查方法'),
        sa.Column('investigation_findings', sa.TEXT(), autoincrement=False, nullable=True, comment='调查发现'),
        sa.Column('investigation_report_path', sa.VARCHAR(length=500), autoincrement=False, nullable=True, comment='调查报告文件路径'),
        sa.Column('direct_cause', sa.TEXT(), autoincrement=False, nullable=True, comment='直接原因'),
        sa.Column('root_cause', sa.TEXT(), autoincrement=False, nullable=True, comment='根本原因'),
        sa.Column('handling_measures', sa.TEXT(), autoincrement=False, nullable=True, comment='处理措施'),
        sa.Column('corrective_actions', sa.TEXT(), autoincrement=False, nullable=True, comment='纠正预防措施'),
        sa.Column('corrective_action_deadline', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=True, comment='CAPA截止日期'),
        sa.Column('corrective_action_responsible', sa.VARCHAR(length=100), autoincrement=False, nullable=True, comment='CAPA责任人'),
        sa.Column('corrective_action_status', sa.VARCHAR(length=32), autoincrement=False, nullable=True, comment='CAPA状态'),
        sa.Column('verified_by', sa.UUID(), autoincrement=False, nullable=True, comment='CAPA验证人'),
        sa.Column('verified_by_name', sa.VARCHAR(length=100), autoincrement=False, nullable=True, comment='验证人姓名'),
        sa.Column('verified_at', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=True, comment='验证时间'),
        sa.Column('status', sa.VARCHAR(length=32), server_default=sa.text("'reported'::character varying"), autoincrement=False, nullable=False, comment='状态'),
        sa.Column('reported_by', sa.UUID(), autoincrement=False, nullable=True, comment='报告人'),
        sa.Column('reported_by_name', sa.VARCHAR(length=100), autoincrement=False, nullable=True, comment='报告人姓名'),
        sa.Column('reported_at', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=False, comment='报告时间'),
        sa.Column('investigator', sa.UUID(), autoincrement=False, nullable=True, comment='调查人'),
        sa.Column('investigator_name', sa.VARCHAR(length=100), autoincrement=False, nullable=True, comment='调查人姓名'),
        sa.Column('notes', sa.TEXT(), autoincrement=False, nullable=True, comment='备注'),
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.Column('created_by', sa.UUID(), autoincrement=False, nullable=True),
        sa.Column('updated_by', sa.UUID(), autoincrement=False, nullable=True),
        sa.Column('is_deleted', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], name=op.f('accidents_created_by_fkey')),
        sa.ForeignKeyConstraint(['investigator'], ['identity.users.id'], name=op.f('accidents_investigator_fkey')),
        sa.ForeignKeyConstraint(['reported_by'], ['identity.users.id'], name=op.f('accidents_reported_by_fkey')),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], name=op.f('accidents_updated_by_fkey')),
        sa.ForeignKeyConstraint(['verified_by'], ['identity.users.id'], name=op.f('accidents_verified_by_fkey')),
        sa.PrimaryKeyConstraint('id', name=op.f('accidents_pkey')),
        schema='safety',
    )
    op.create_index(op.f('uq_accidents_accident_no'), 'accidents', ['accident_no'], unique=True, schema='safety', postgresql_where='(is_deleted = false)')
