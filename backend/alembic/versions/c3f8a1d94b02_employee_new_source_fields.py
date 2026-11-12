"""employee new source fields

员工档案对接新数据源（飞书「员工信息表」）新增 6 列：民族/省份全称/离职原因/
学位类型/毕业证书/人力资源分析。全部 nullable，无存量回填。

Revision ID: c3f8a1d94b02
Revises: hr_resume_screening_001
Create Date: 2026-11-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c3f8a1d94b02'
down_revision: Union[str, None] = 'hr_resume_screening_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = [
    ('ethnicity', sa.String(length=32), '民族'),
    ('province', sa.String(length=64), '省份全称'),
    ('hr_analysis', sa.String(length=32), '人力资源分析（生产辅助/后勤服务等）'),
    ('degree_type', sa.String(length=32), '学位类型'),
    ('graduation_certificate', sa.String(length=256), '毕业证书'),
    ('departure_reason', sa.String(length=64), '离职原因'),
]


def upgrade() -> None:
    for name, type_, comment in _COLUMNS:
        op.add_column(
            'employees',
            sa.Column(name, type_, nullable=True, comment=comment),
            schema='hr',
        )


def downgrade() -> None:
    for name, _type_, _comment in reversed(_COLUMNS):
        op.drop_column('employees', name, schema='hr')
