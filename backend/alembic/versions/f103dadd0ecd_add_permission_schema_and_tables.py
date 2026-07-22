"""add permission schema and tables

Revision ID: f103dadd0ecd
Revises: 00b1b23aab64
Create Date: 2026-06-26 10:36:41.462612
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f103dadd0ecd'
down_revision: Union[str, None] = '00b1b23aab64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS permission")

    # --- permissions ---
    op.create_table(
        'permissions',
        sa.Column('code', sa.String(length=100), nullable=False, comment='权限编码，如 equipment:inspection:create'),
        sa.Column('name', sa.String(length=200), nullable=False, comment='显示名称，如 创建巡检'),
        sa.Column('module', sa.String(length=50), nullable=False, comment='所属模块编码'),
        sa.Column('resource', sa.String(length=50), nullable=False, comment='资源类型'),
        sa.Column('action', sa.String(length=50), nullable=False, comment='操作类型: read/create/update/delete/approve/manage'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_system', sa.Boolean(), server_default='false', nullable=False, comment='系统内置权限不可删除'),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code', name='uq_permission_permissions_code'),
        schema='permission',
    )

    # --- roles ---
    op.create_table(
        'roles',
        sa.Column('code', sa.String(length=50), nullable=False, comment='角色编码，如 equipment_inspector'),
        sa.Column('name', sa.String(length=100), nullable=False, comment='显示名称'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('data_scope', sa.String(length=30), server_default='department', nullable=False, comment='默认数据范围: all/department/department_and_children/self_only'),
        sa.Column('is_system', sa.Boolean(), server_default='false', nullable=False, comment='系统内置角色不可删除'),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code', name='uq_permission_roles_code'),
        schema='permission',
    )

    # --- role_permissions ---
    op.create_table(
        'role_permissions',
        sa.Column('role_id', sa.UUID(), nullable=False, comment='角色 ID'),
        sa.Column('permission_id', sa.UUID(), nullable=False, comment='权限 ID'),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('role_id', 'permission_id', name='uq_role_permissions_pair'),
        schema='permission',
    )

    # --- user_roles ---
    op.create_table(
        'user_roles',
        sa.Column('user_id', sa.UUID(), nullable=False, comment='用户 ID (identity.users)'),
        sa.Column('role_id', sa.UUID(), nullable=False, comment='角色 ID'),
        sa.Column('department_id', sa.UUID(), nullable=True, comment='可选：限定角色在某部门生效，NULL=全局'),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'role_id', 'department_id', name='uq_user_roles_triple'),
        schema='permission',
    )

    # --- role_data_scope_overrides ---
    op.create_table(
        'role_data_scope_overrides',
        sa.Column('role_id', sa.UUID(), nullable=False, comment='角色 ID'),
        sa.Column('module', sa.String(length=50), nullable=False, comment='模块编码'),
        sa.Column('data_scope', sa.String(length=30), nullable=False, comment='覆盖后的数据范围'),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('role_id', 'module', name='uq_role_data_scope_module'),
        schema='permission',
    )


def downgrade() -> None:
    op.drop_table('role_data_scope_overrides', schema='permission')
    op.drop_table('user_roles', schema='permission')
    op.drop_table('role_permissions', schema='permission')
    op.drop_table('roles', schema='permission')
    op.drop_table('permissions', schema='permission')
    op.execute("DROP SCHEMA IF EXISTS permission CASCADE")
