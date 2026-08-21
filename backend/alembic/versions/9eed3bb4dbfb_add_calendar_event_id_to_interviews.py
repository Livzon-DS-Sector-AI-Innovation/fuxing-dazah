"""add_calendar_event_id_to_interviews

Revision ID: 9eed3bb4dbfb
Revises: c8e237f1211c
Create Date: 2026-08-10 17:16:05.297128
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9eed3bb4dbfb'
down_revision: Union[str, None] = 'c8e237f1211c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS hr")
    op.add_column(
        'interviews',
        sa.Column('calendar_event_id', sa.String(128), nullable=True, comment='飞书日历事件ID'),
        schema='hr',
    )


def downgrade() -> None:
    op.drop_column('interviews', 'calendar_event_id', schema='hr')
