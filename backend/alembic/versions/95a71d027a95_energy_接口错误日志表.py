"""energy 接口错误日志表

Revision ID: 95a71d027a95
Revises: db50a555822f
Create Date: 2026-08-17 10:47:35.512635
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '95a71d027a95'
down_revision: Union[str, None] = 'db50a555822f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS energy")
    op.create_table(
        'energy_error_logs',
        sa.Column('method', sa.String(length=10), nullable=False, comment='HTTP 方法'),
        sa.Column('path', sa.String(length=500), nullable=False, comment='请求路径'),
        sa.Column('path_params', postgresql.JSONB(), nullable=False, comment='路径参数（如 log_id）'),
        sa.Column('query_params', postgresql.JSONB(), nullable=False, comment='查询参数'),
        sa.Column('exception_type', sa.String(length=200), nullable=False, comment='异常类型名'),
        sa.Column('message', sa.Text(), nullable=False, comment='异常消息'),
        sa.Column('traceback', sa.Text(), nullable=False, comment='完整堆栈'),
        sa.Column('request_id', sa.String(length=50), nullable=True, comment='请求ID，用于关联审计日志'),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.text('false'), comment='软删除标记'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['identity.users.id']),
        sa.ForeignKeyConstraint(['updated_by'], ['identity.users.id']),
        sa.PrimaryKeyConstraint('id'),
        schema='energy'
    )


def downgrade() -> None:
    op.drop_table('energy_error_logs', schema='energy')
