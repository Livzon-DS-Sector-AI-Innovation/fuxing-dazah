"""qa coa standard template binding columns

COA 回填 docx：客户标准挂一份模板文件（存储键/原文件名/摘要）和人工确认后的
模板标注（字段→数据位、格式规则、固定文字格）。

Revision ID: 3371249cf36d
Revises: dada00079c92
Create Date: 2026-11-25 08:39:34.385149
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3371249cf36d'
down_revision: Union[str, None] = 'dada00079c92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('coa_standards', sa.Column('template_key', sa.String(length=255), nullable=True, comment='COA docx 模板文件存储键（QA 文件存储）'), schema='qa')
    op.add_column('coa_standards', sa.Column('template_filename', sa.String(length=255), nullable=True, comment='模板原始文件名'), schema='qa')
    op.add_column('coa_standards', sa.Column('template_sha256', sa.String(length=64), nullable=True, comment='模板文件摘要；标注与文件一致性守卫'), schema='qa')
    op.add_column('coa_standards', sa.Column('template_binding', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='人工确认后的模板标注（字段→数据位、格式规则、固定文字格）；未确认为空'), schema='qa')


def downgrade() -> None:
    op.drop_column('coa_standards', 'template_binding', schema='qa')
    op.drop_column('coa_standards', 'template_sha256', schema='qa')
    op.drop_column('coa_standards', 'template_filename', schema='qa')
    op.drop_column('coa_standards', 'template_key', schema='qa')
