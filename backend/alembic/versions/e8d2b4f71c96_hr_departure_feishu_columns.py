"""hr_departure_feishu_columns

离职台账表补列：对接飞书「2026年离职人员管理」表同步所需的 13 个可空字段

Revision ID: e8d2b4f71c96
Revises: a3f8c1d60b42
Create Date: 2026-11-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8d2b4f71c96'
down_revision: Union[str, None] = 'a3f8c1d60b42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'departure_records'
_SCHEMA = 'hr'

# (列名, 类型, 注释)
_COLUMNS = [
    ('employee_number', sa.String(32), '工号（飞书离职人员管理表同步；关联员工档案）'),
    ('duty', sa.String(64), '职务'),
    ('rank', sa.String(16), '职级（如 S5）'),
    ('rank_category', sa.String(32), '岗位职级（职业技能岗位/技术职级等）'),
    ('degree_type', sa.String(32), '学位类型'),
    ('id_card_expiry', sa.Date(), '身份证有效期'),
    ('ethnicity', sa.String(32), '民族'),
    ('residence_address', sa.String(256), '居住地址（敏感，展示时脱敏）'),
    ('emergency_contact_name', sa.String(64), '紧急联系人姓名'),
    ('contract_start_date', sa.Date(), '合同开始日期'),
    ('contract_end_date', sa.Date(), '合同结束日期'),
    ('certificates', sa.Text(), '证书'),
]


def upgrade() -> None:
    for name, type_, comment in _COLUMNS:
        op.add_column(_TABLE, sa.Column(name, type_, nullable=True, comment=comment), schema=_SCHEMA)
    op.create_index('ix_departure_employee_number', _TABLE, ['employee_number'], schema=_SCHEMA)


def downgrade() -> None:
    op.drop_index('ix_departure_employee_number', table_name=_TABLE, schema=_SCHEMA)
    for name, _type_, _comment in reversed(_COLUMNS):
        op.drop_column(_TABLE, name, schema=_SCHEMA)
