"""add_sop_content_fields

Revision ID: 97bd41dc097a
Revises: 9825df3b20bb
Create Date: 2026-06-17 18:10:38.481450
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '97bd41dc097a'
down_revision: Union[str, None] = '9825df3b20bb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'operation_regulations',
        sa.Column('content', sa.Text(), nullable=True,
                  comment='标准化 Markdown 内容（9 章完整操规）'),
        schema='safety',
    )
    op.add_column(
        'operation_regulations',
        sa.Column('status', sa.String(length=20), server_default='draft', nullable=False,
                  comment='操规状态: draft/generated/reviewed/exported'),
        schema='safety',
    )
    op.add_column(
        'operation_regulations',
        sa.Column('source_document_path', sa.String(length=500), nullable=True,
                  comment='原始上传的旧版操规文件路径'),
        schema='safety',
    )


def downgrade() -> None:
    op.drop_column('operation_regulations', 'source_document_path', schema='safety')
    op.drop_column('operation_regulations', 'status', schema='safety')
    op.drop_column('operation_regulations', 'content', schema='safety')
