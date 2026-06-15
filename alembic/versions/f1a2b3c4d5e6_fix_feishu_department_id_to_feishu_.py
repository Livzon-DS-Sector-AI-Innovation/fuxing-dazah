"""fix feishu_department_id to feishu_department_ids

Revision ID: f1a2b3c4d5e6
Revises: c70602651fd7
Create Date: 2026-06-10 19:40:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'c70602651fd7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the singular column if it exists (may have been removed already)
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='identity' AND table_name='users' "
            "AND column_name='feishu_department_id'"
        )
    )
    if result.fetchone():
        op.drop_column('users', 'feishu_department_id', schema='identity')

    # Add the plural column (JSON array) if not exists
    result = conn.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='identity' AND table_name='users' "
            "AND column_name='feishu_department_ids'"
        )
    )
    if not result.fetchone():
        op.add_column(
            'users',
            sa.Column(
                'feishu_department_ids',
                sa.Text(),
                nullable=True,
                comment='飞书部门ID列表，JSON数组'
            ),
            schema='identity'
        )


def downgrade() -> None:
    op.drop_column('users', 'feishu_department_ids', schema='identity')
    op.add_column(
        'users',
        sa.Column(
            'feishu_department_id',
            sa.String(length=64),
            nullable=True,
            comment='飞书部门ID'
        ),
        schema='identity'
    )
