"""add_sop_training_records_and_rework_entries

Revision ID: 7f710cf62ee3
Revises: 5d53122ff1cb
Create Date: 2026-08-13 16:21:59.437064

新增培训文件登记表；二级表改为按登记记录（master_id→record_id，去掉 sop_ids，增加 complete_time）；
内训师台账增加任期列。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7f710cf62ee3'
down_revision: Union[str, None] = '5d53122ff1cb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 培训文件登记表 ──
    op.create_table(
        'sop_training_records',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.String(64), nullable=True, comment='登记人'),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('year', sa.String(4), nullable=False, comment='登记年份，如 2026'),
        sa.Column('training_date', sa.String(32), nullable=True, comment='培训日期，如 01.05'),
        sa.Column('file_name', sa.String(512), nullable=False, comment='文件名称'),
        sa.Column('file_no', sa.String(128), nullable=True, comment='文件编号（SOP编号，(CA)前缀=草案）'),
        sa.Column('effective_date', sa.String(32), nullable=True, comment='生效日期，草案填——'),
        sa.Column('method', sa.String(4), nullable=True, comment='培训方式：R（按完成时间）/ T（按课时）'),
        sa.Column('complete_time', sa.String(64), nullable=True, comment='R：培训完成时间；T：培训课时（日期+时段）'),
        sa.Column('trainer', sa.String(64), nullable=True, comment='培训师（集中培训时填写）'),
        sa.Column('trainees', sa.String(256), nullable=True, comment='培训对象，默认「X部门全体员工及相关部门培训师」'),
        sa.Column('involved_departments', sa.Text(), nullable=True, comment='培训涉及部门，JSON 数组'),
        sa.Column('change_note', sa.Text(), nullable=True, comment='变更内容（新制订/修改原因）'),
        sa.Column('color', sa.String(8), nullable=False, server_default='新增', comment='新增/撤销/修改'),
        sa.Column('status', sa.String(16), nullable=False, server_default='草稿', comment='草稿/已提交'),
        sa.Column('initiator_department', sa.String(128), nullable=True, comment='发起部门（主办部门）'),
        sa.PrimaryKeyConstraint('id'),
        schema='hr',
    )
    op.create_index('ix_sop_record_year', 'sop_training_records', ['year'], schema='hr')
    op.create_index('ix_sop_record_status', 'sop_training_records', ['status'], schema='hr')

    # ── 二级表改造：master_id → record_id ──
    op.alter_column('sop_training_entries', 'master_id', new_column_name='record_id', schema='hr')
    op.execute("DROP INDEX IF EXISTS hr.ix_sop_entry_master")
    op.create_index('ix_sop_entry_record', 'sop_training_entries', ['record_id'], schema='hr')
    op.drop_column('sop_training_entries', 'sop_ids', schema='hr')
    op.add_column(
        'sop_training_entries',
        sa.Column('complete_time', sa.String(64), nullable=True, comment='该部门培训完成时间/课时'),
        schema='hr',
    )

    # ── 内训师任期 ──
    op.add_column(
        'trainers',
        sa.Column('period', sa.String(64), nullable=True, comment='任期（如 2023.03.01起）'),
        schema='hr',
    )


def downgrade() -> None:
    op.drop_column('trainers', 'period', schema='hr')
    op.drop_column('sop_training_entries', 'complete_time', schema='hr')
    op.add_column(
        'sop_training_entries',
        sa.Column('sop_ids', sa.Text(), nullable=True, comment='关联 SOP 条目 ID，JSON 数组'),
        schema='hr',
    )
    op.drop_index('ix_sop_entry_record', table_name='sop_training_entries', schema='hr')
    op.create_index('ix_sop_entry_master', 'sop_training_entries', ['record_id'], schema='hr')
    op.alter_column('sop_training_entries', 'record_id', new_column_name='master_id', schema='hr')
    op.drop_table('sop_training_records', schema='hr')
