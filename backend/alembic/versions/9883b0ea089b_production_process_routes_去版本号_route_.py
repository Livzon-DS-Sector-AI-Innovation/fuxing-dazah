"""production: process_routes 去版本号,route_name 产品内唯一

Revision ID: 9883b0ea089b
Revises: ff497f1c138b
Create Date: 2026-08-05 14:01:20.527281
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '9883b0ea089b'
down_revision: Union[str, None] = 'ff497f1c138b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 新增 route_name 列（先允许 NULL，填充数据后再收紧）
    op.add_column(
        'process_routes',
        sa.Column('route_name', sa.String(length=200), nullable=True,
                  comment='路线名称，产品内唯一，兼作路径标识'),
        schema='production',
    )
    # 2. 存量数据收拢：每个产品只保留最新 published（无 published 取最新创建），其余软删。
    #    唯一约束 (product_id, route_name) 只对 is_deleted=false 生效，必须保证同产品无重名存活记录。
    op.execute("""
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY product_id
                       ORDER BY (status = 'published') DESC, created_at DESC
                   ) AS rn
            FROM production.process_routes
            WHERE is_deleted = false
        )
        UPDATE production.process_routes pr
        SET is_deleted = true
        FROM ranked r
        WHERE pr.id = r.id AND r.rn > 1
    """)
    op.execute("""
        UPDATE production.process_routes
        SET route_name = COALESCE(NULLIF(name, ''), '默认工艺')
        WHERE route_name IS NULL
    """)
    # 3. 换唯一索引
    op.drop_index(
        op.f('uq_production_routes_product_version'),
        table_name='process_routes', schema='production',
        postgresql_where='(is_deleted = false)',
    )
    op.create_index(
        'uq_production_routes_product_name', 'process_routes',
        ['product_id', 'route_name'], unique=True,
        schema='production', postgresql_where=sa.text('is_deleted = false'),
    )
    # 4. 收紧 NOT NULL，删除旧列
    op.alter_column('process_routes', 'route_name',
                    existing_type=sa.String(length=200), nullable=False,
                    schema='production')
    op.drop_column('process_routes', 'name', schema='production')
    op.drop_column('process_routes', 'version', schema='production')


def downgrade() -> None:
    op.add_column('process_routes',
                  sa.Column('version', sa.INTEGER(), autoincrement=False,
                            nullable=False, comment='版本号，同产品内递增'),
                  schema='production')
    op.add_column('process_routes',
                  sa.Column('name', sa.VARCHAR(length=200), autoincrement=False,
                            nullable=False, comment='路线名称'),
                  schema='production')
    op.execute("""
        UPDATE production.process_routes
        SET name = route_name
        WHERE is_deleted = false
    """)
    op.drop_index('uq_production_routes_product_name',
                  table_name='process_routes', schema='production',
                  postgresql_where=sa.text('is_deleted = false'))
    op.create_index(
        op.f('uq_production_routes_product_version'), 'process_routes',
        ['product_id', 'version'], unique=True, schema='production',
        postgresql_where='(is_deleted = false)',
    )
    op.drop_column('process_routes', 'route_name', schema='production')
