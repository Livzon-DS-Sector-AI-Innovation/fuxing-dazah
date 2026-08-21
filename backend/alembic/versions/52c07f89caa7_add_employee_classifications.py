"""add_employee_classifications

Revision ID: 52c07f89caa7
Revises: 7f710cf62ee3
Create Date: 2026-08-13 17:59:59.463371

员工自定义分类清单：培训管理员维护，员工档案以「下拉选项」形式选择分类。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '52c07f89caa7'
down_revision: Union[str, None] = '7f710cf62ee3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS hr")
    op.create_table(
        'employee_classifications',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.String(64), nullable=False, comment='创建人'),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('name', sa.String(64), nullable=False, comment='分类名称'),
        sa.PrimaryKeyConstraint('id'),
        schema='hr',
    )
    op.create_index('ix_employee_classifications_creator', 'employee_classifications', ['created_by'], schema='hr')


def downgrade() -> None:
    op.drop_table('employee_classifications', schema='hr')
