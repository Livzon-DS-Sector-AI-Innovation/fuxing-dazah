"""add heads and auto_notify_enabled to meter departments

Revision ID: 7419e6f7039e
Revises: 515181afd401
Create Date: 2026-07-09 09:09:03.136030
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '7419e6f7039e'
down_revision: Union[str, None] = '515181afd401'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "departments",
        sa.Column(
            "heads",
            postgresql.JSONB,
            nullable=True,
            server_default=sa.text("'[]'::jsonb"),
            comment="负责人列表 JSON: [{\"name\": \"张三\", \"feishu_open_id\": \"ou_xxx\"}]",
        ),
        schema="meter",
    )
    op.add_column(
        "departments",
        sa.Column(
            "auto_notify_enabled",
            sa.Boolean,
            nullable=True,
            server_default=sa.text("false"),
            comment="部门级自动提醒开关",
        ),
        schema="meter",
    )


def downgrade() -> None:
    op.drop_column("departments", "auto_notify_enabled", schema="meter")
    op.drop_column("departments", "heads", schema="meter")
