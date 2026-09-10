"""add contractor_admissions table

Revision ID: 4cecb5911e73
Revises: 0381ab8c0cb0
Create Date: 2026-08-20 15:15:50.463722
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '4cecb5911e73'
down_revision: Union[str, None] = '0381ab8c0cb0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 新建相关方准入条件审核表（Bitable 镜像）
    # BaseModel 自带 id/created_at/updated_at/created_by/updated_by/is_deleted
    op.create_table(
        'contractor_admissions',
        sa.Column('admission_no', sa.String(length=64), nullable=True, comment='准入编号（平台自动生成 CA-YYYYMMDD-####）'),
        sa.Column('company_name', sa.String(length=255), nullable=True, comment='作业单位名称'),
        sa.Column('related_party_type', sa.String(length=32), nullable=True, comment='相关方类型: 承包商/合作类相关方/劳务派遣/其他相关方'),
        sa.Column('contact_person', sa.String(length=100), nullable=True, comment='承包商负责人'),
        sa.Column('contact_phone', sa.String(length=32), nullable=True, comment='承包商负责人联系电话'),
        sa.Column('liaison_user_id', sa.String(length=64), nullable=True, comment='对接人员飞书 open_id/user_id（Bitable user 字段）'),
        sa.Column('liaison_user_name', sa.String(length=100), nullable=True, comment='对接人员姓名'),
        sa.Column('entry_date', sa.Date(), nullable=True, comment='入厂日期'),
        sa.Column('start_date', sa.Date(), nullable=True, comment='开始日期'),
        sa.Column('end_date', sa.Date(), nullable=True, comment='结束日期'),
        sa.Column('material_expiry_date', sa.Date(), nullable=True, comment='材料失效日期'),
        sa.Column('actual_submit_date', sa.Date(), nullable=True, comment='实际提交日期'),
        sa.Column('actual_complete_date', sa.Date(), nullable=True, comment='实际完成日期'),
        sa.Column('submit_status', sa.String(length=32), nullable=True, comment='提交状态: 已完成/进行中/未开始'),
        sa.Column('training_status', sa.String(length=32), nullable=True, comment='培训状态: 已完结/已培训待补材/未培训'),
        sa.Column('notes', sa.Text(), nullable=True, comment='备注'),
        sa.Column('safety_agreement_files', sa.JSON(), nullable=True, comment='安全管理协议附件 [{name,path,file_token}]（按 type 取对应 Bitable 字段）'),
        sa.Column('business_license_files', sa.JSON(), nullable=True, comment='企业营业执照附件 [{name,path,file_token}]'),
        sa.Column('insurance_files', sa.JSON(), nullable=True, comment='现场作业保险凭证附件 [{name,path,file_token}]'),
        sa.Column('assessment_rules_files', sa.JSON(), nullable=True, comment='承包商考核细则附件 [{name,path,file_token}]'),
        sa.Column('employee_cert_files', sa.JSON(), nullable=True, comment='员工证明盖章文件附件 [{name,path,file_token}]'),
        sa.Column('on_site_leader_stamp_files', sa.JSON(), nullable=True, comment='现场负责人盖章文件附件 [{name,path,file_token}]'),
        sa.Column('source', sa.String(length=16), server_default='bitable', nullable=False, comment='数据来源: bitable(飞书同步)/manual(手动)'),
        sa.Column('feishu_record_id', sa.String(length=64), nullable=True, comment='飞书 Bitable 记录 ID（同步主键）'),
        sa.Column('feishu_table_id', sa.String(length=32), nullable=True, comment='飞书表 ID（单表恒为 admission）'),
        sa.Column('feishu_url', sa.String(length=512), nullable=True, comment='Bitable 记录跳转链接'),
        sa.Column('ai_review_status', sa.String(length=32), server_default='none', nullable=False, comment='AI审核状态: none/processing/completed/failed'),
        sa.Column('ai_review_result', sa.JSON(), nullable=True, comment='AI审核结果 JSONB {agreement:{conclusion,report,defects}, license:{...}, insurance:{...}, overall_conclusion, overall_report, defect_categories:[], regulations:[...]}'),
        sa.Column('ai_error_message', sa.Text(), nullable=True, comment='AI审核失败信息（failed 时记录，completed 时清空）'),
        sa.Column('ai_reviewed_at', sa.DateTime(timezone=True), nullable=True, comment='最近一次 AI 审核完成时间'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='safety',
        comment='相关方准入条件审核表（Bitable 镜像）'
    )
    # 部分唯一索引（软删除/空值不参与唯一约束）
    op.create_index(
        'uq_contractor_admissions_admission_no', 'contractor_admissions', ['admission_no'],
        unique=True, schema='safety',
        postgresql_where=sa.text('is_deleted = false AND admission_no IS NOT NULL')
    )
    op.create_index(
        'uq_contractor_admissions_feishu_record_id', 'contractor_admissions', ['feishu_record_id'],
        unique=True, schema='safety',
        postgresql_where=sa.text('is_deleted = false AND feishu_record_id IS NOT NULL')
    )
    # 查询索引
    op.create_index('ix_contractor_admissions_company', 'contractor_admissions', ['company_name'], unique=False, schema='safety')
    op.create_index('ix_contractor_admissions_type', 'contractor_admissions', ['related_party_type'], unique=False, schema='safety')
    op.create_index('ix_contractor_admissions_submit', 'contractor_admissions', ['submit_status'], unique=False, schema='safety')
    op.create_index('ix_contractor_admissions_review', 'contractor_admissions', ['ai_review_status'], unique=False, schema='safety')
    op.create_index('ix_contractor_admissions_entry_date', 'contractor_admissions', ['entry_date'], unique=False, schema='safety')


def downgrade() -> None:
    op.drop_index('ix_contractor_admissions_entry_date', table_name='contractor_admissions', schema='safety')
    op.drop_index('ix_contractor_admissions_review', table_name='contractor_admissions', schema='safety')
    op.drop_index('ix_contractor_admissions_submit', table_name='contractor_admissions', schema='safety')
    op.drop_index('ix_contractor_admissions_type', table_name='contractor_admissions', schema='safety')
    op.drop_index('ix_contractor_admissions_company', table_name='contractor_admissions', schema='safety')
    op.drop_index('uq_contractor_admissions_feishu_record_id', table_name='contractor_admissions', schema='safety', postgresql_where=sa.text('is_deleted = false AND feishu_record_id IS NOT NULL'))
    op.drop_index('uq_contractor_admissions_admission_no', table_name='contractor_admissions', schema='safety', postgresql_where=sa.text('is_deleted = false AND admission_no IS NOT NULL'))
    op.drop_table('contractor_admissions', schema='safety')
