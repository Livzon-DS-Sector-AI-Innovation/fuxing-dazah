"""employee derive gender/birth from id card + drop legacy display fields

新数据源（飞书「员工信息表」）无性别列且基本无出生日期列，但身份证号
100% 覆盖：按第 17 位奇偶派生性别、第 7-14 位派生出生日期，回填存量。
同步链路（employee_sync.mapping._derive_from_id_card）已做同样的增量派生。

同时下线 9 个源表不提供、仅旧 Excel 时代展示用的字段。

Revision ID: a9d4c2e77f10
Revises: b5e2f8a01c74
Create Date: 2026-11-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a9d4c2e77f10'
down_revision: Union[str, None] = 'b5e2f8a01c74'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 出生日期段（第 7-14 位）合法性：年 19xx/20xx、月 01-12、日 01-31
_BIRTH = "^[0-9]{6}(19|20)[0-9]{2}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])[0-9]{3}[0-9Xx]$"

_DROP_COLUMNS = [
    ('political_status', '政治面貌'),
    ('age', '年龄（旧飞书公式）'),
    ('work_years', '工作年限（旧飞书公式）'),
    ('factory_tenure', '厂龄（旧飞书公式）'),
    ('province', '省份全称（源表无数据）'),
    ('id_card_address', '身份证地址'),
    ('contract_type', '合同类型'),
    ('email', '邮箱'),
    ('bank_account', '银行卡号'),
]


def upgrade() -> None:
    # 1) 存量回填：性别（第 17 位奇男偶女）
    op.execute("""
        UPDATE hr.employees
        SET gender = CASE
            WHEN CAST(substring(id_card from 17 for 1) AS int) % 2 = 1 THEN '男'
            ELSE '女'
        END
        WHERE gender IS NULL
          AND id_card ~ '^[0-9]{17}[0-9Xx]$'
    """)
    # 2) 存量回填：出生年/月/日（第 7-14 位，日期段合法才写）
    op.execute(f"""
        UPDATE hr.employees
        SET birth_year  = CAST(substring(id_card from 7 for 4) AS int),
            birth_month = CAST(substring(id_card from 11 for 2) AS int),
            birth_day   = CAST(substring(id_card from 13 for 2) AS int)
        WHERE birth_year IS NULL
          AND birth_month IS NULL
          AND id_card ~ '{_BIRTH}'
    """)
    # 3) 下线旧展示字段
    for name, _comment in _DROP_COLUMNS:
        op.drop_column('employees', name, schema='hr')


def downgrade() -> None:
    _ADD = [
        ('political_status', sa.String(length=32)),
        ('age', sa.Integer()),
        ('work_years', sa.Integer()),
        ('factory_tenure', sa.String(length=32)),
        ('province', sa.String(length=64)),
        ('id_card_address', sa.Text()),
        ('contract_type', sa.String(length=32)),
        ('email', sa.String(length=128)),
        ('bank_account', sa.String(length=32)),
    ]
    for name, type_ in reversed(_ADD):
        op.add_column('employees', sa.Column(name, type_, nullable=True), schema='hr')
