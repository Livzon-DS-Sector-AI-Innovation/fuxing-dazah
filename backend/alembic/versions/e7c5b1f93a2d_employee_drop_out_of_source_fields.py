"""employee drop out-of-source fields

继续下线源数据表（飞书「员工信息表」）不提供的员工档案字段。这些字段自
新数据源切换后每轮对账都被置空，员工表侧无保留价值；培训名单
（hr.training_roster_profiles）的同名列是独立数据集，不受影响。

Revision ID: e7c5b1f93a2d
Revises: a9d4c2e77f10
Create Date: 2026-11-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e7c5b1f93a2d'
down_revision: Union[str, None] = 'a9d4c2e77f10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DROP_COLUMNS = [
    ('actual_department', sa.String(length=64), '实际部门'),
    ('team', sa.String(length=64), '班组'),
    ('concurrent_departments', sa.String(length=256), '兼任部门'),
    ('variety', sa.String(length=64), '品种'),
    ('concurrent_variety', sa.String(length=256), '兼任品种'),
    ('qualifications', sa.JSON(), '职称／职业资格'),
    ('qualification_type', sa.String(length=32), '职称类型'),
    ('factory_entry_date', sa.Date(), '进厂时间'),
    ('livo_entry_date', sa.Date(), '入丽珠时间'),
    ('contract_start_2', sa.Date(), '第二次合同起点'),
    ('contract_end_2', sa.Date(), '第二次合同终止'),
    ('contract_start_3', sa.Date(), '第三次合同起点'),
    ('contract_end_3', sa.Date(), '第三次合同终止'),
    ('contract_start_4', sa.Date(), '第四次合同起点'),
    ('contract_end_4', sa.Date(), '第四次合同终止'),
    ('dept_manager', sa.String(length=64), '部门管理者'),
    ('additional_manager', sa.String(length=64), '额外管理者'),
    ('dept_head_trainer', sa.String(length=64), '部门负责人/一级培训师'),
    ('training_id', sa.String(length=32), '培训档案编号'),
    ('safety_training_date', sa.Date(), '入职安全培训日期'),
    ('safety_training_score', sa.String(length=32), '入职安全培训成绩'),
    ('culture_training_date', sa.Date(), '企业文化培训日期'),
    ('gmp_training_date', sa.Date(), 'GMP基础培训时间'),
    ('remarks', sa.JSON(), '备注'),
]


def upgrade() -> None:
    for name, _type_, _comment in _DROP_COLUMNS:
        op.drop_column('employees', name, schema='hr')


def downgrade() -> None:
    for name, type_, _comment in reversed(_DROP_COLUMNS):
        op.add_column(
            'employees',
            sa.Column(name, type_, nullable=True, comment=_comment),
            schema='hr',
        )
