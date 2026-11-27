"""SOP 培训二级表自定义分类支持多选

分类字段由单个分类名改为「；」连接的多分类展示串（如「班组长；管理人员」），
varchar(64) 拓宽到 256 容纳多个分类名。

Revision ID: b8d2e6a4c1f3
Revises: ff7e451f0f9c
Create Date: 2026-11-27 10:00:00.000000
"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b8d2e6a4c1f3'
down_revision: str | None = 'ff7e451f0f9c'
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.alter_column(
        'sop_training_entries',
        'classification',
        existing_type=sa.String(length=64),
        type_=sa.String(length=256),
        existing_nullable=True,
        comment='自定义分类，多选按「；」连接（对应创建人员工标签）',
        schema='hr',
    )


def downgrade() -> None:
    op.alter_column(
        'sop_training_entries',
        'classification',
        existing_type=sa.String(length=256),
        type_=sa.String(length=64),
        existing_nullable=True,
        comment='自定义分类（对应部门员工标签）',
        schema='hr',
    )
