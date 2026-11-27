"""qa apr 模板段段名同产品内唯一

Revision ID: fd8da0093c43
Revises: d7d3af84b902
Create Date: 2026-11-09 14:56:57.498384

模板段此前只校验产品归属，段名可重复，配置树里会出现两个「成品检验-USP」
无法区分。本次补 (product_id, name) 部分唯一索引：作用域是单个产品，
不同产品可同名（各自的药典/工序段），且只约束未删除行，删掉后可重新启用同名段。

存量若已有同产品重名段，迁移会报错并列出冲突值，需先人工改名再重跑。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'fd8da0093c43'
down_revision: str | None = 'd7d3af84b902'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. 建索引前先查同产品重名段（软删除行不参与索引，也不参与本检查）。
    op.execute(
        """
        DO $$
        DECLARE dup text;
        BEGIN
            SELECT string_agg(conflict, '; ') INTO dup FROM (
                SELECT p.name || ' / ' || s.name AS conflict
                FROM qa.apr_sections s
                JOIN qa.apr_products p ON p.id = s.product_id
                WHERE s.is_deleted = false
                GROUP BY s.product_id, p.name, s.name
                HAVING count(*) > 1
            ) t;
            IF dup IS NOT NULL THEN
                RAISE EXCEPTION 'APR 模板段同产品下段名重复，请先人工改名：%', dup;
            END IF;
        END
        $$;
        """
    )
    op.alter_column(
        'apr_sections',
        'name',
        existing_type=sa.String(length=100),
        existing_nullable=False,
        comment='段名（同一产品内唯一），如 菌种-摇瓶培养 / 成品检验-USP',
        schema='qa',
    )
    # 2. 段名唯一作用域 = 产品；仅约束未删除行，软删除后可复用同名。
    op.create_index(
        'uq_qa_apr_sections_product_name',
        'apr_sections',
        ['product_id', 'name'],
        unique=True,
        schema='qa',
        postgresql_where=sa.text('is_deleted = false'),
    )


def downgrade() -> None:
    op.drop_index(
        'uq_qa_apr_sections_product_name',
        table_name='apr_sections',
        schema='qa',
        postgresql_where=sa.text('is_deleted = false'),
    )
    op.alter_column(
        'apr_sections',
        'name',
        existing_type=sa.String(length=100),
        existing_nullable=False,
        comment='段名，如 菌种-摇瓶培养 / 成品检验-USP',
        schema='qa',
    )
