"""quality add lc template configs

Revision ID: 3f8915e11f07
Revises: aa6c6154e9f6
Create Date: 2026-09-08 18:00:00.789204
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '3f8915e11f07'
down_revision: Union[str, None] = 'aa6c6154e9f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    import json
    op.execute("CREATE SCHEMA IF NOT EXISTS quality")
    op.create_table(
        'quality_lc_template_configs',
        sa.Column('table_no', sa.String(length=50), nullable=False, comment='计算表表号，如 EX-HA-8329-002（模板识别键）'),
        sa.Column('product_name', sa.String(length=200), nullable=False, comment='产品名称（与标准库一致）'),
        sa.Column('description', sa.String(length=200), nullable=True, comment='模板描述'),
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='取值配置 JSON'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default='false', nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='quality',
    )
    op.create_index('uq_quality_lc_template_table_no', 'quality_lc_template_configs',
                    ['table_no'], unique=True, schema='quality',
                    postgresql_where=sa.text('is_deleted = false'))

    # 种子配置：万古霉素 5 模板 + 妥布霉素 Ph.Eur（结构已逐模板核对）
    seed_configs = [
        # 万古霉素系列：A 列组分名（含％），每组分 4 行（第一份/第二份各 2 行），
        # M 列为报告值（平均，百分比文本），无 M 的模板回落 L 列取两份平均
        ("EX-HA-5246-001", "盐酸万古霉素", "万古霉素冻干粉-USP", {"batch_label": "批号", "blocks": [{"kind": "paired_rows", "name_col": "A", "name_has": "%", "start_row": 21, "step": 4, "value_col": "M", "fallback_col": "L", "avg": True, "value_mode": "percent_text"}]}),
        ("EX-HA-8301-001", "盐酸万古霉素", "万古霉素冻干粉-USP(HNPL)", {"batch_label": "批号", "blocks": [{"kind": "paired_rows", "name_col": "A", "name_has": "%", "start_row": 21, "step": 4, "value_col": "M", "fallback_col": "L", "avg": True, "value_mode": "percent_text"}]}),
        ("EX-HA-5249-001", "盐酸万古霉素", "万古霉素-CP色谱纯度", {"batch_label": "批号", "blocks": [{"kind": "paired_rows", "name_col": "A", "name_has": "%", "start_row": 21, "step": 4, "value_col": "M", "fallback_col": "L", "avg": True, "value_mode": "percent_text"}]}),
        ("EX-HA-5231-001", "盐酸万古霉素", "万古霉素沉淀粉", {"batch_label": "批号", "blocks": [{"kind": "paired_rows", "name_col": "A", "name_has": "%", "start_row": 23, "step": 4, "value_col": "L", "avg": True, "value_mode": "percent_text"}]}),
        ("EX-HA-8329-002", "盐酸万古霉素", "万古霉素冻干粉-赞比亚/埃塞俄比亚", {"batch_label": "批号", "blocks": [{"kind": "paired_rows", "name_col": "A", "name_has": "%", "start_row": 22, "step": 4, "value_col": "M", "fallback_col": "L", "avg": True, "value_mode": "percent_text"}]}),
        ("EX-TO-5573-001", "妥布霉素", "妥布霉素含量与有关物质-Ph.Eur", {"batch_label": "批号", "blocks": [{"kind": "fixed_cell", "name": "含量", "cell": "L12", "value_mode": "percent_text"}, {"kind": "paired_rows", "name_col": "C", "name_has": "%", "start_row": 22, "step": 4, "value_col": "K", "avg": False, "value_mode": "percent_text"}]}),
    ]
    for table_no, product_name, description, config in seed_configs:
        op.execute(
            sa.text(
                "INSERT INTO quality.quality_lc_template_configs "
                "(id, table_no, product_name, description, config, created_at, updated_at, is_deleted) "
                "VALUES (gen_random_uuid(), :t, :p, :d, CAST(:c AS jsonb), now(), now(), false)"
            ).bindparams(t=table_no, p=product_name, d=description, c=json.dumps(config, ensure_ascii=False))
        )
    pass


def downgrade() -> None:
    op.drop_table('quality_lc_template_configs', schema='quality')
