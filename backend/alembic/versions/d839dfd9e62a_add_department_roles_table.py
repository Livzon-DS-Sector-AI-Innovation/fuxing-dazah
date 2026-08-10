"""add_department_roles_table

Revision ID: d839dfd9e62a
Revises: a27cd8fceae4
Create Date: 2026-08-06 15:30:07.771138
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd839dfd9e62a'
down_revision: Union[str, None] = 'a27cd8fceae4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS permission")
    op.create_table('department_roles',
        sa.Column('feishu_department_id', sa.String(length=64), nullable=False, comment='飞书部门 open_department_id'),
        sa.Column('role_id', sa.Uuid(), nullable=False, comment='角色 ID'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('feishu_department_id', 'role_id', name='uq_department_roles_pair'),
        schema='permission'
    )


def downgrade() -> None:
    op.drop_table('department_roles', schema='permission')
