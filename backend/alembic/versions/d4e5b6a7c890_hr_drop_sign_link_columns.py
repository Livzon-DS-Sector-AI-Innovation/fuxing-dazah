"""hr：下线员工线上签字链接（系统只在公司内网可达，外部链接没有意义）

2026-11-27 拍板：系统只部署在公司内网，员工在手机 / 外网打不开任何指向本系统的链接，
「签署链接 + 线上签字」整条链路删除：
1. hr.departure_records 删 cert_sign_token 列及其唯一索引 ix_departure_cert_sign_token。
   签收结果列（cert_sign_status / cert_signed_at / cert_sign_name / cert_sign_image）保留：
   员工到人事办公室在公司电脑上手写签名、或在纸质件上签字后由 HR 登记，继续写这几列。
2. hr.labor_contracts 删 sign_token_hash 列及索引 ix_labor_contracts_sign_token_hash，
   删 sign_confirmed_at 列：员工领取合同原件即签收，以 delivered_at 为准。
3. 两个签字页地址配置项（hr_offboarding.sign_page_base_url /
   hr_contract.sign_page_base_url）软删：代码已不再读取。

被删的列里不会有需要保留的业务数据：内网外打不开链接，线上签字事实上无法完成；
开发库核对过，仅有本地联调留下的 1 条待签 token、0 条签名图、0 条合同签字时间。
contract_notice_logs 里 kind='sign' 的历史留痕不删，展示时按「历史通知」兜底。

Revision ID: d4e5b6a7c890
Revises: bbada0b6db98
Create Date: 2026-11-27 14:35:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd4e5b6a7c890'
down_revision: str | None = 'bbada0b6db98'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = 'hr'

_SIGN_PAGE_SETTING_KEYS = (
    'hr_offboarding.sign_page_base_url',
    'hr_contract.sign_page_base_url',
)


def upgrade() -> None:
    op.drop_index('ix_departure_cert_sign_token', table_name='departure_records', schema=SCHEMA)
    op.drop_column('departure_records', 'cert_sign_token', schema=SCHEMA)
    op.drop_index('ix_labor_contracts_sign_token_hash', table_name='labor_contracts', schema=SCHEMA)
    op.drop_column('labor_contracts', 'sign_confirmed_at', schema=SCHEMA)
    op.drop_column('labor_contracts', 'sign_token_hash', schema=SCHEMA)
    op.execute(sa.text(
        'UPDATE hr.system_settings SET is_deleted = true '
        'WHERE key IN (:offboarding_key, :contract_key) AND is_deleted = false'
    ).bindparams(offboarding_key=_SIGN_PAGE_SETTING_KEYS[0], contract_key=_SIGN_PAGE_SETTING_KEYS[1]))


def downgrade() -> None:
    op.execute(sa.text(
        'UPDATE hr.system_settings SET is_deleted = false '
        'WHERE key IN (:offboarding_key, :contract_key)'
    ).bindparams(offboarding_key=_SIGN_PAGE_SETTING_KEYS[0], contract_key=_SIGN_PAGE_SETTING_KEYS[1]))
    op.add_column('labor_contracts', sa.Column(
        'sign_token_hash', sa.String(length=128), nullable=True,
        comment='签字一次性 token 的 sha256（确认后清空，重发即作废旧链接）',
    ), schema=SCHEMA)
    op.create_index(
        'ix_labor_contracts_sign_token_hash', 'labor_contracts', ['sign_token_hash'],
        unique=False, schema=SCHEMA,
    )
    op.add_column('labor_contracts', sa.Column(
        'sign_confirmed_at', sa.DateTime(timezone=True), nullable=True,
        comment='员工线上签字确认时间（已领取凭证）',
    ), schema=SCHEMA)
    op.add_column('departure_records', sa.Column(
        'cert_sign_token', sa.String(length=64), nullable=True, comment='签署链接 token',
    ), schema=SCHEMA)
    op.create_index(
        'ix_departure_cert_sign_token', 'departure_records', ['cert_sign_token'],
        unique=True, schema=SCHEMA,
    )
