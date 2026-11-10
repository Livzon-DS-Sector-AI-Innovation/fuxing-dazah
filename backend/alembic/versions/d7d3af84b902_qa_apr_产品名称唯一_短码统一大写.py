"""qa apr 产品名称唯一、短码统一大写

Revision ID: d7d3af84b902
Revises: c7d31a90e4f2
Create Date: 2026-11-09 14:49:39.752068

产品目录此前只校验短码：名称可重名，短码大小写敏感（dt 与 DT 可并存）。
本次把存量短码统一转大写，并为名称补部分唯一索引（仅约束未删除行，
与短码同口径，避免「删除→重建」撞索引）。

若存量数据已存在「仅大小写不同」的短码或重名产品，迁移会报错并列出冲突值，
需先人工合并再重跑；不自动改名，避免静默改写业务数据。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd7d3af84b902'
down_revision: str | None = 'c7d31a90e4f2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. 转大写前先查冲突：仅大小写不同的短码转大写后会撞唯一索引。
    op.execute(
        """
        DO $$
        DECLARE dup text;
        BEGIN
            SELECT string_agg(upper_code, ', ') INTO dup FROM (
                SELECT upper(code) AS upper_code
                FROM qa.apr_products
                WHERE is_deleted = false
                GROUP BY upper(code)
                HAVING count(*) > 1
            ) t;
            IF dup IS NOT NULL THEN
                RAISE EXCEPTION 'APR 产品短码转大写后冲突，请先人工合并：%', dup;
            END IF;
        END
        $$;
        """
    )
    # 2. 建名称唯一索引前先查重名（软删除行不参与索引，也不参与本检查）。
    op.execute(
        """
        DO $$
        DECLARE dup text;
        BEGIN
            SELECT string_agg(name, ', ') INTO dup FROM (
                SELECT name
                FROM qa.apr_products
                WHERE is_deleted = false
                GROUP BY name
                HAVING count(*) > 1
            ) t;
            IF dup IS NOT NULL THEN
                RAISE EXCEPTION 'APR 产品名称重复，请先人工改名：%', dup;
            END IF;
        END
        $$;
        """
    )
    # 3. 存量短码统一大写（含软删除行，保持清理后数据口径一致）。
    op.execute(
        "UPDATE qa.apr_products SET code = upper(code) WHERE code <> upper(code)"
    )
    op.alter_column(
        'apr_products',
        'code',
        existing_type=sa.String(length=32),
        existing_nullable=False,
        comment='产品短码（批号前缀来源），大写，如 DT/KA/ST',
        schema='qa',
    )
    # 4. 名称部分唯一索引：仅约束未删除行，软删除后可复用同名。
    op.create_index(
        'uq_qa_apr_products_name',
        'apr_products',
        ['name'],
        unique=True,
        schema='qa',
        postgresql_where=sa.text('is_deleted = false'),
    )


def downgrade() -> None:
    op.drop_index(
        'uq_qa_apr_products_name',
        table_name='apr_products',
        schema='qa',
        postgresql_where=sa.text('is_deleted = false'),
    )
    op.alter_column(
        'apr_products',
        'code',
        existing_type=sa.String(length=32),
        existing_nullable=False,
        comment='产品短码（批号前缀来源），如 DT/KA/ST',
        schema='qa',
    )
