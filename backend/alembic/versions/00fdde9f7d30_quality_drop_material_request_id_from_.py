"""quality drop material_request_id from requests

Revision ID: 00fdde9f7d30
Revises: 7f2f90424dd6
Create Date: 2026-10-22 15:46:02.395256
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '00fdde9f7d30'
down_revision: str | None = '7f2f90424dd6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 请验单模型上的复制粘贴遗留列（挂单字段只属于容器表），删除
    op.drop_column("quality_material_requests", "material_request_id", schema="quality")


def downgrade() -> None:
    op.add_column(
        "quality_material_requests",
        sa.Column("material_request_id", sa.Uuid(), nullable=True),
        schema="quality",
    )
