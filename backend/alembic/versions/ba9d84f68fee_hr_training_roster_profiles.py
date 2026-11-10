"""hr training roster profiles

培训人员名单（脱敏独立数据集）：人员增减跟随员工档案，字段值独立维护。

Revision ID: ba9d84f68fee
Revises: f1a9c22e7d60
Create Date: 2026-11-10 14:41:03.149655

说明：autogenerate 吸入了其他模块与本库的历史 drift（本地库与其他模块
模型存在大量无关差异），已按规范清理，只保留本模块 DDL + 存量回填。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'ba9d84f68fee'
down_revision: Union[str, None] = 'f1a9c22e7d60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('training_roster_profiles',
    sa.Column('employee_number', sa.String(length=32), nullable=False, comment='工号（关联键）'),
    sa.Column('name', sa.String(length=64), nullable=False, comment='姓名'),
    sa.Column('department', sa.String(length=64), nullable=False, comment='体现部门'),
    sa.Column('actual_department', sa.String(length=64), nullable=True, comment='实际部门'),
    sa.Column('team', sa.String(length=64), nullable=True, comment='班组'),
    sa.Column('position', sa.String(length=64), nullable=False, comment='职位'),
    sa.Column('duty', sa.String(length=64), nullable=True, comment='职务'),
    sa.Column('job_category', sa.String(length=32), nullable=True, comment='岗位类别'),
    sa.Column('level', sa.String(length=32), nullable=True, comment='级别'),
    sa.Column('concurrent_departments', sa.String(length=256), nullable=True, comment='兼任部门'),
    sa.Column('education', sa.String(length=16), nullable=True, comment='学历'),
    sa.Column('graduation_date', sa.Date(), nullable=True, comment='毕业时间'),
    sa.Column('status_category', sa.String(length=32), nullable=True, comment='用工性质'),
    sa.Column('status', sa.String(length=16), server_default='在职', nullable=False, comment='人员状态'),
    sa.Column('work_start_date', sa.Date(), nullable=True, comment='参加工作时间'),
    sa.Column('factory_entry_date', sa.Date(), nullable=True, comment='进厂时间'),
    sa.Column('livo_entry_date', sa.Date(), nullable=True, comment='入丽珠时间'),
    sa.Column('hire_date', sa.Date(), nullable=True, comment='入职日期'),
    sa.Column('departure_date', sa.Date(), nullable=True, comment='离职时间'),
    sa.Column('certificates', sa.String(length=512), nullable=True, comment='证书'),
    sa.Column('qualifications', sa.JSON(), nullable=True, comment='职称／职业资格（多选）'),
    sa.Column('training_id', sa.String(length=32), nullable=True, comment='培训档案编号'),
    sa.Column('dept_head_trainer', sa.String(length=64), nullable=True, comment='部门负责人/一级培训师'),
    sa.Column('safety_training_date', sa.Date(), nullable=True, comment='入职安全培训日期'),
    sa.Column('safety_training_score', sa.String(length=32), nullable=True, comment='入职安全培训成绩'),
    sa.Column('culture_training_date', sa.Date(), nullable=True, comment='企业文化培训日期'),
    sa.Column('gmp_training_date', sa.Date(), nullable=True, comment='GMP基础培训时间'),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['identity.users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('employee_number'),
    schema='hr'
    )
    op.create_index('ix_training_roster_profiles_department', 'training_roster_profiles', ['department'], unique=False, schema='hr')
    op.create_index('ix_training_roster_profiles_employee_number', 'training_roster_profiles', ['employee_number'], unique=True, schema='hr')

    # 存量回填：当前有效员工按白名单字段复制初值进入名单
    op.execute("""
        INSERT INTO hr.training_roster_profiles (
            id, employee_number, name, department, actual_department, team, position,
            duty, job_category, level, concurrent_departments, education, graduation_date,
            status_category, status, work_start_date, factory_entry_date, livo_entry_date,
            hire_date, departure_date, certificates, qualifications, training_id,
            dept_head_trainer, safety_training_date, safety_training_score,
            culture_training_date, gmp_training_date, created_at, updated_at
        )
        SELECT gen_random_uuid(), e.employee_number, e.name, e.department,
               e.actual_department, e.team, e.position, e.duty, e.job_category,
               e.level, e.concurrent_departments, e.education, e.graduation_date,
               e.status_category, COALESCE(NULLIF(e.status, ''), '在职'), e.work_start_date,
               e.factory_entry_date, e.livo_entry_date, e.hire_date, e.departure_date,
               e.certificates, e.qualifications, e.training_id, e.dept_head_trainer,
               e.safety_training_date, e.safety_training_score, e.culture_training_date,
               e.gmp_training_date, now(), now()
        FROM hr.employees e
        WHERE e.is_deleted = false
    """)


def downgrade() -> None:
    op.drop_index(op.f('ix_training_roster_profiles_employee_number'), table_name='training_roster_profiles', schema='hr')
    op.drop_index(op.f('ix_training_roster_profiles_department'), table_name='training_roster_profiles', schema='hr')
    op.drop_table('training_roster_profiles', schema='hr')
