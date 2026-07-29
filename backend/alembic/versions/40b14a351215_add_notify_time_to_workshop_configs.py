"""add_notify_time_to_workshop_configs

Revision ID: 40b14a351215
Revises: b30b2344705d
Create Date: 2026-07-27 13:49:31.776884
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '40b14a351215'
down_revision: Union[str, None] = 'b30b2344705d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'energy_workshop_configs',
        sa.Column('notify_time', sa.String(length=5), nullable=True,
                  comment='每日通知时间 HH:MM，如 09:00；NULL 表示使用全局默认时间'),
        schema='energy',
    )


def downgrade() -> None:
    op.drop_column('energy_workshop_configs', 'notify_time', schema='energy')
