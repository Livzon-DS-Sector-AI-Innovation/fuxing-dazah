"""drop quality standard document library tables

Revision ID: 8366b089eadd
Revises: c8ce652b75c2
Create Date: 2026-09-02 17:28:09.751006
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8366b089eadd'
down_revision: Union[str, None] = 'c8ce652b75c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 标准文档库整体下线：功能与报告生成流程无关，按业务决定移除
    op.drop_table("standard_documents", schema="quality")
    op.drop_table("document_categories", schema="quality")


def downgrade() -> None:
    # 不下沉重建（表结构见 a640beeddd5c），如需恢复从历史迁移重建
    pass
