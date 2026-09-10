"""add person_certificates table

Revision ID: 813667b97e08
Revises: 4cecb5911e73
Create Date: 2026-08-21 14:30:38.849001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '813667b97e08'
down_revision: Union[str, None] = '4cecb5911e73'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 人员持证台账表（Bitable 镜像 + 预警计算输入）
    # BaseModel 自带 id/created_at/updated_at/created_by/updated_by/is_deleted
    op.create_table(
        'person_certificates',
        sa.Column('feishu_record_id', sa.String(length=64), nullable=True, comment='Bitable 记录 ID（镜像同步主键；软删时置 NULL）'),
        sa.Column('source', sa.String(length=16), server_default='bitable', nullable=False, comment='数据来源: bitable(飞书同步) / manual(手动)'),
        sa.Column('cert_category', sa.String(length=32), nullable=False, comment='证件类别: special_op(特种作业证) / guardian_a(监护人A证) / guardian_b(监护人B证)'),
        sa.Column('person_name', sa.String(length=100), nullable=False, comment='姓名'),
        sa.Column('department', sa.String(length=100), nullable=True, comment='部门'),
        sa.Column('employee_no', sa.String(length=64), nullable=True, comment='工号'),
        sa.Column('phone', sa.String(length=32), nullable=True, comment='联系方式'),
        sa.Column('operation_type', sa.String(length=32), nullable=True, comment='作业类别（特种作业证用，对应 OperationType 8 类: hot_work 等）'),
        sa.Column('project', sa.String(length=100), nullable=True, comment='项目（如电工、焊接、高处）'),
        sa.Column('certificate_no', sa.String(length=100), nullable=True, comment='证件编号'),
        sa.Column('issue_date', sa.Date(), nullable=True, comment='取证日期'),
        sa.Column('next_review_date', sa.Date(), nullable=True, comment='再复审时间（特种作业证用）'),
        sa.Column('review_frequency', sa.String(length=32), nullable=True, comment="复审频次（如'3年'、'无需复审'）"),
        sa.Column('first_review_deadline', sa.Date(), nullable=True, comment='第一次复审截止日期（监护人证用）'),
        sa.Column('second_review_deadline', sa.Date(), nullable=True, comment='第二次复审截止日期（监护人证用）'),
        sa.Column('should_renew_date', sa.Date(), nullable=True, comment='应换证日期（监护人证用）'),
        sa.Column('renewed_date', sa.Date(), nullable=True, comment='已换证日期（监护人证用，回填后以 renewed_date 为新 issue_date 重算下一周期）'),
        sa.Column('certificate_file_path', sa.String(length=500), nullable=True, comment='证件附件路径'),
        sa.Column('notes', sa.Text(), nullable=True, comment='备注'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='safety',
        comment='人员持证台账（Bitable 镜像 + 预警计算输入）'
    )
    # 部分唯一索引（软删除/空 record_id 不参与唯一约束）
    op.create_index(
        'uq_person_certs_feishu_rid', 'person_certificates', ['feishu_record_id'],
        unique=True, schema='safety',
        postgresql_where=sa.text('is_deleted = false AND feishu_record_id IS NOT NULL')
    )
    # 查询索引
    op.create_index('ix_person_certs_next_review', 'person_certificates', ['next_review_date'], unique=False, schema='safety')
    op.create_index('ix_person_certs_should_renew', 'person_certificates', ['should_renew_date'], unique=False, schema='safety')
    op.create_index('ix_person_certs_first_review', 'person_certificates', ['first_review_deadline'], unique=False, schema='safety')
    op.create_index('ix_person_certs_dept', 'person_certificates', ['department'], unique=False, schema='safety')
    op.create_index('ix_person_certs_category', 'person_certificates', ['cert_category'], unique=False, schema='safety')
    op.create_index('ix_person_certs_feishu', 'person_certificates', ['feishu_record_id'], unique=False, schema='safety')


def downgrade() -> None:
    # 按 upgrade 反序 drop（先 drop 索引，再 drop 表）
    op.drop_index('ix_person_certs_feishu', table_name='person_certificates', schema='safety')
    op.drop_index('ix_person_certs_category', table_name='person_certificates', schema='safety')
    op.drop_index('ix_person_certs_dept', table_name='person_certificates', schema='safety')
    op.drop_index('ix_person_certs_first_review', table_name='person_certificates', schema='safety')
    op.drop_index('ix_person_certs_should_renew', table_name='person_certificates', schema='safety')
    op.drop_index('ix_person_certs_next_review', table_name='person_certificates', schema='safety')
    op.drop_index('uq_person_certs_feishu_rid', table_name='person_certificates', schema='safety', postgresql_where=sa.text('is_deleted = false AND feishu_record_id IS NOT NULL'))
    op.drop_table('person_certificates', schema='safety')