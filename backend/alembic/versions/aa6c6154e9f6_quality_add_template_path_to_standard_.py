"""quality add template path to standard documents

Revision ID: aa6c6154e9f6
Revises: fb6b53998d69
Create Date: 2026-09-03 17:33:33.107030
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aa6c6154e9f6'
down_revision: Union[str, None] = 'fb6b53998d69'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS quality")
    op.add_column('quality_standard_documents',
                  sa.Column('template_path', sa.String(length=500), nullable=True,
                            comment='绑定的 COA 报告模板路径（如 万古霉素/3205.docx）'),
                  schema='quality')


def downgrade() -> None:
    op.drop_column('quality_standard_documents', 'template_path', schema='quality')
