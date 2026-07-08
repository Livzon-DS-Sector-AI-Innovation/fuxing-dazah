"""replace last_notify_date with last_sent_at in meter_settings

Revision ID: e76ca014a4dd
Revises: 82b66e023746
Create Date: 2026-07-08 09:45:26.501386
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e76ca014a4dd'
down_revision: Union[str, None] = '82b66e023746'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 添加 last_sent_at，记录上次实际发送的完整日期时间
    op.add_column(
        'meter_settings',
        sa.Column(
            'last_sent_at',
            sa.DateTime(timezone=True),
            nullable=True,
            comment="上次实际发送的日期时间，用于判断'今天+当前设定时间'是否已推送过",
        ),
        schema='meter',
    )
    # 更新 last_notify_date 注释，标记为废弃
    op.alter_column(
        'meter_settings', 'last_notify_date',
        existing_type=sa.Date(),
        comment='[DEPRECATED] 请使用 last_sent_at',
        existing_comment='上次发送日期，防止同一天重复发送',
        existing_nullable=True,
        schema='meter',
    )


def downgrade() -> None:
    op.alter_column(
        'meter_settings', 'last_notify_date',
        existing_type=sa.Date(),
        comment='上次发送日期，防止同一天重复发送',
        existing_comment='[DEPRECATED] 请使用 last_sent_at',
        existing_nullable=True,
        schema='meter',
    )
    op.drop_column('meter_settings', 'last_sent_at', schema='meter')
