"""ensure_hr_user_department_access_table

部分环境（如生产服务器）因 alembic_version 指向仓库谱系之外的版本，
跳过了 3cb53e7c4a68 的建表迁移，导致 hr.user_department_access 缺失。
本迁移幂等重建该表（结构与原迁移一致），已建表的环境会自动跳过。

Revision ID: 9a81aa44045c
Revises: f9cccc30f41a
Create Date: 2026-07-31 15:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a81aa44045c'
down_revision: Union[str, None] = 'f9cccc30f41a'
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
    op.drop_index('uq_uda_user_dept_active', table_name='user_department_access', schema='hr')
    op.drop_index('ix_uda_user_id', table_name='user_department_access', schema='hr')
    op.drop_table('user_department_access', schema='hr')
