"""route_nodes 新增 name 路线内唯一约束，stage_name 改为 NOT NULL

Revision ID: 0fb346de3256
Revises: d839dfd9e62a
Create Date: 2026-08-07 10:44:33.706627
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0fb346de3256'
down_revision: Union[str, None] = 'd839dfd9e62a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 处理存量重名 name：同 route_id 下追加数字后缀
    op.execute("""
        WITH duplicates AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY route_id, name
                       ORDER BY created_at
                   ) AS rn
            FROM production.route_nodes
            WHERE is_deleted = false
        )
        UPDATE production.route_nodes rn
        SET name = rn.name || '_' || (d.rn - 1)::text
        FROM duplicates d
        WHERE rn.id = d.id AND d.rn > 1
    """)
    # 存量 NULL stage_name 补默认值
    op.execute("""
        UPDATE production.route_nodes
        SET stage_name = '未分组'
        WHERE stage_name IS NULL
    """)
    # stage_name NOT NULL + 更新注释
    op.alter_column(
        'route_nodes', 'stage_name',
        existing_type=sa.VARCHAR(length=100),
        nullable=False,
        comment='工序所属工段分组标签（如发酵/提炼/精制）',
        existing_comment='工段分组标签（发酵/提炼/精制），纯展示',
        existing_nullable=True,
        schema='production',
    )
    # 新增 name 唯一索引
    op.create_index(
        'uq_route_nodes_name', 'route_nodes',
        ['route_id', 'name'], unique=True,
        schema='production',
        postgresql_where=sa.text('is_deleted = false'),
    )


def downgrade() -> None:
    op.drop_index(
        'uq_route_nodes_name', table_name='route_nodes',
        schema='production',
        postgresql_where=sa.text('is_deleted = false'),
    )
    op.alter_column(
        'route_nodes', 'stage_name',
        existing_type=sa.VARCHAR(length=100),
        nullable=True,
        comment='工段分组标签（发酵/提炼/精制），纯展示',
        existing_comment='工序所属工段分组标签（如发酵/提炼/精制）',
        existing_nullable=False,
        schema='production',
    )
