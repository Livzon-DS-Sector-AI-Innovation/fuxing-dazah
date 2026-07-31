"""add_user_department_access_table

Revision ID: 3cb53e7c4a68
Revises: 483dc0c490d3
Create Date: 2026-07-30 19:28:59.632525
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3cb53e7c4a68'
down_revision: Union[str, None] = '483dc0c490d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'user_department_access' in inspector.get_table_names(schema='hr'):
        return
    op.create_table(
        'user_department_access',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False, comment='用户ID (identity.users)'),
        sa.Column('department', sa.String(length=128), nullable=False, comment='可访问的部门名称'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='hr',
    )
    op.create_index('ix_uda_user_id', 'user_department_access', ['user_id'], unique=False, schema='hr')
    op.create_index('uq_uda_user_dept_active', 'user_department_access', ['user_id', 'department'], unique=True, schema='hr', postgresql_where=sa.text('is_deleted = false'))


def downgrade() -> None:
    op.drop_index('ix_uda_user_id', table_name='user_department_access', schema='hr')
    op.drop_table('user_department_access', schema='hr')
