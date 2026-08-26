"""add title review v2 tables

Revision ID: ae2ff4e45582
Revises: 52c07f89caa7
Create Date: 2026-08-19 15:00:00.000000

仅包含 hr.title_review_* 七张表（职称评审 v2 投票制）。autogenerate 混入的
其他模块无关变更已按规范人工清理。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'ae2ff4e45582'
down_revision: Union[str, None] = '52c07f89caa7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS hr")
    op.create_table('title_review_activities',
    sa.Column('name', sa.String(length=128), nullable=False, comment='活动名称'),
    sa.Column('status', sa.String(length=16), server_default='draft', nullable=False, comment='draft/open/reviewing/closed'),
    sa.Column('apply_deadline', sa.DateTime(timezone=True), nullable=True, comment='申报截止时间'),
    sa.Column('review_deadline', sa.DateTime(timezone=True), nullable=True, comment='评审截止时间'),
    sa.Column('pass_ratio', sa.Float(), server_default='0.6667', nullable=False, comment='通过比例：同意÷(同意+不同意) ≥ 此值（默认三分之二）'),
    sa.Column('feishu_app_token', sa.String(length=64), nullable=True, comment='飞书多维表格 app_token（绑定现有表）'),
    sa.Column('apply_table_id', sa.String(length=64), nullable=True, comment='申报表 table_id'),
    sa.Column('vote_table_id', sa.String(length=64), nullable=True, comment='投票表 table_id'),
    sa.Column('feishu_folder_token', sa.String(length=64), nullable=True, comment='备用：存放多维表格的文件夹 token'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='hr'
    )
    op.create_index('ix_tract_feishu_app', 'title_review_activities', ['feishu_app_token'], unique=False, schema='hr')
    op.create_index('ix_tract_status', 'title_review_activities', ['status'], unique=False, schema='hr')
    op.create_table('title_review_applications',
    sa.Column('activity_id', sa.Uuid(), nullable=False, comment='所属活动'),
    sa.Column('employee_id', sa.Uuid(), nullable=True, comment='hr.employees.id'),
    sa.Column('employee_no', sa.String(length=32), nullable=False, comment='工号快照'),
    sa.Column('name', sa.String(length=64), nullable=False, comment='姓名快照'),
    sa.Column('department', sa.String(length=128), nullable=True, comment='部门快照'),
    sa.Column('sequence', sa.String(length=32), nullable=True, comment='申报序列'),
    sa.Column('apply_level', sa.String(length=32), nullable=True, comment='申报职级'),
    sa.Column('current_level', sa.String(length=32), nullable=True, comment='现任职级'),
    sa.Column('is_exception', sa.Boolean(), server_default='false', nullable=False, comment='是否破格申报'),
    sa.Column('exception_reason', sa.Text(), nullable=True, comment='破格申报理由'),
    sa.Column('tenure_start', sa.DateTime(timezone=True), nullable=True, comment='任现职开始时间'),
    sa.Column('tenure_end', sa.DateTime(timezone=True), nullable=True, comment='任现职结束时间'),
    sa.Column('self_evaluations', sa.JSON(), nullable=True, comment='7 项自我评价 {维度名: 优秀/合格/不合格}'),
    sa.Column('work_statements', sa.JSON(), nullable=True, comment='业绩陈述文本 {字段名: 文本}'),
    sa.Column('attachments', sa.JSON(), nullable=True, comment='4 类附件元数据 {类别: [{file_token,name,size}]}'),
    sa.Column('feishu_record_id', sa.String(length=64), nullable=True, comment='申报表记录 id'),
    sa.Column('status', sa.String(length=16), server_default='submitted', nullable=False, comment='submitted/dept_rejected/voting/passed/failed/final_passed/final_failed/invalid'),
    sa.Column('agree_votes', sa.Integer(), server_default='0', nullable=False, comment='同意票数'),
    sa.Column('oppose_votes', sa.Integer(), server_default='0', nullable=False, comment='不同意票数'),
    sa.Column('abstain_votes', sa.Integer(), server_default='0', nullable=False, comment='弃权票数'),
    sa.Column('final_result', sa.String(length=16), nullable=True, comment='判定结果 passed/failed'),
    sa.Column('final_opinion', sa.Text(), nullable=True, comment='附件4评审综合意见（终审意见）'),
    sa.Column('result_notified_at', sa.DateTime(timezone=True), nullable=True, comment='结果已通知申报人时间'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='hr'
    )
    op.create_index('ix_tapp_activity_status', 'title_review_applications', ['activity_id', 'status'], unique=False, schema='hr')
    op.create_index('uq_tapp_activity_employee', 'title_review_applications', ['activity_id', 'employee_id'], unique=True, schema='hr', postgresql_where=sa.text('is_deleted = false'))
    op.create_index('uq_tapp_activity_record', 'title_review_applications', ['activity_id', 'feishu_record_id'], unique=True, schema='hr', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('title_review_dept_committees',
    sa.Column('department', sa.String(length=64), nullable=False, comment='部门名称'),
    sa.Column('manager_employee_id', sa.Uuid(), nullable=True, comment='部门负责人（初审人） hr.employees.id'),
    sa.Column('manager_name', sa.String(length=64), nullable=True, comment='负责人姓名'),
    sa.Column('leader_employee_id', sa.Uuid(), nullable=True, comment='分管领导（终审人） hr.employees.id'),
    sa.Column('leader_name', sa.String(length=64), nullable=True, comment='分管领导姓名'),
    sa.Column('committee_members', sa.JSON(), nullable=True, comment='职级评定小组成员 [{employee_id,name,employee_no}]'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='hr'
    )
    op.create_index('uq_tdc_department', 'title_review_dept_committees', ['department'], unique=True, schema='hr', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('title_review_dimensions',
    sa.Column('activity_id', sa.Uuid(), nullable=False, comment='所属活动'),
    sa.Column('name', sa.String(length=64), nullable=False, comment='评价项名称'),
    sa.Column('feishu_field_name', sa.String(length=64), nullable=False, comment='投票表列名'),
    sa.Column('feishu_field_id', sa.String(length=64), nullable=True, comment='投票表 field_id（事件映射用，绑定后回写）'),
    sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False, comment='排序'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='hr'
    )
    op.create_index('ix_tdim_activity', 'title_review_dimensions', ['activity_id'], unique=False, schema='hr')
    op.create_index('uq_tdim_activity_field', 'title_review_dimensions', ['activity_id', 'feishu_field_name'], unique=True, schema='hr', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('title_review_judges',
    sa.Column('activity_id', sa.Uuid(), nullable=False, comment='所属活动'),
    sa.Column('application_id', sa.Uuid(), nullable=False, comment='所属申报'),
    sa.Column('judge_employee_id', sa.Uuid(), nullable=False, comment='hr.employees.id'),
    sa.Column('judge_name', sa.String(length=64), nullable=False, comment='评委姓名（仅内网）'),
    sa.Column('judge_employee_no', sa.String(length=32), nullable=True, comment='评委工号（仅内网）'),
    sa.Column('judge_code', sa.String(length=16), nullable=False, comment='评审人编号（匿名，写入投票表）'),
    sa.Column('judge_role', sa.String(length=32), nullable=True, comment='评审人角色：技术专家/部门经理/人力资源'),
    sa.Column('feishu_record_id', sa.String(length=64), nullable=True, comment='投票表行 id（批量写行后回写）'),
    sa.Column('vote_result', sa.String(length=16), nullable=True, comment='投票结果：同意/不同意/弃权'),
    sa.Column('comprehensive_grade', sa.String(length=16), nullable=True, comment='综合等级：优秀/合格/不合格'),
    sa.Column('review_comment', sa.Text(), nullable=True, comment='评审意见'),
    sa.Column('voted_at', sa.DateTime(timezone=True), nullable=True, comment='投票时间'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='hr'
    )
    op.create_index('ix_tjud_activity', 'title_review_judges', ['activity_id'], unique=False, schema='hr')
    op.create_index('ix_tjud_application', 'title_review_judges', ['application_id'], unique=False, schema='hr')
    op.create_index('uq_tjud_app_judge', 'title_review_judges', ['application_id', 'judge_employee_id'], unique=True, schema='hr', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('title_review_levels',
    sa.Column('activity_id', sa.Uuid(), nullable=False, comment='所属活动'),
    sa.Column('sequence', sa.String(length=32), nullable=False, comment='序列：技术职级/职业技能'),
    sa.Column('level_name', sa.String(length=32), nullable=False, comment='职级名'),
    sa.Column('basic_conditions', sa.Text(), nullable=True, comment='基本条件'),
    sa.Column('ability_requirements', sa.Text(), nullable=True, comment='专业能力要求'),
    sa.Column('achievement_requirements', sa.Text(), nullable=True, comment='业绩成果要求'),
    sa.Column('review_points', sa.Text(), nullable=True, comment='评审要点'),
    sa.Column('remark', sa.Text(), nullable=True, comment='备注说明'),
    sa.Column('need_final_review', sa.Boolean(), server_default='false', nullable=False, comment='是否需要终审（分管领导）'),
    sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False, comment='排序'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='hr'
    )
    op.create_index('ix_tlvl_activity', 'title_review_levels', ['activity_id'], unique=False, schema='hr')
    op.create_index('uq_tlvl_activity_level', 'title_review_levels', ['activity_id', 'sequence', 'level_name'], unique=True, schema='hr', postgresql_where=sa.text('is_deleted = false'))
    op.create_table('title_review_scores',
    sa.Column('activity_id', sa.Uuid(), nullable=False, comment='所属活动'),
    sa.Column('application_id', sa.Uuid(), nullable=False, comment='所属申报'),
    sa.Column('judge_id', sa.Uuid(), nullable=False, comment='关联 title_review_judges.id'),
    sa.Column('dimension_id', sa.Uuid(), nullable=False, comment='关联评价项'),
    sa.Column('dimension_name', sa.String(length=64), nullable=False, comment='评价项名快照'),
    sa.Column('grade', sa.String(length=16), nullable=True, comment='评价等级：优秀/合格/不合格'),
    sa.Column('voted_at', sa.DateTime(timezone=True), nullable=True, comment='评价时间'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    schema='hr'
    )
    op.create_index('ix_tscore_judge', 'title_review_scores', ['judge_id'], unique=False, schema='hr')
    op.create_index('uq_tscore_judge_dim', 'title_review_scores', ['judge_id', 'dimension_id'], unique=True, schema='hr', postgresql_where=sa.text('is_deleted = false'))

def downgrade() -> None:
    op.drop_index('uq_tscore_judge_dim', table_name='title_review_scores', schema='hr', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('ix_tscore_judge', table_name='title_review_scores', schema='hr')
    op.drop_table('title_review_scores', schema='hr')
    op.drop_index('uq_tlvl_activity_level', table_name='title_review_levels', schema='hr', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('ix_tlvl_activity', table_name='title_review_levels', schema='hr')
    op.drop_table('title_review_levels', schema='hr')
    op.drop_index('uq_tjud_app_judge', table_name='title_review_judges', schema='hr', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('ix_tjud_application', table_name='title_review_judges', schema='hr')
    op.drop_index('ix_tjud_activity', table_name='title_review_judges', schema='hr')
    op.drop_table('title_review_judges', schema='hr')
    op.drop_index('uq_tdim_activity_field', table_name='title_review_dimensions', schema='hr', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('ix_tdim_activity', table_name='title_review_dimensions', schema='hr')
    op.drop_table('title_review_dimensions', schema='hr')
    op.drop_index('uq_tdc_department', table_name='title_review_dept_committees', schema='hr', postgresql_where=sa.text('is_deleted = false'))
    op.drop_table('title_review_dept_committees', schema='hr')
    op.drop_index('uq_tapp_activity_record', table_name='title_review_applications', schema='hr', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('uq_tapp_activity_employee', table_name='title_review_applications', schema='hr', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('ix_tapp_activity_status', table_name='title_review_applications', schema='hr')
    op.drop_table('title_review_applications', schema='hr')
    op.drop_index('ix_tract_status', table_name='title_review_activities', schema='hr')
    op.drop_index('ix_tract_feishu_app', table_name='title_review_activities', schema='hr')
    op.drop_table('title_review_activities', schema='hr')
