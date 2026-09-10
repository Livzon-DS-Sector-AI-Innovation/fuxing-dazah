"""add entity_ids to regulation_chunks

Revision ID: a7b8c9d0e1f2
Revises: c1d2e3f4a5b6
Create Date: 2026-07-07 12:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, UUID

from alembic import op

revision: str = 'a7b8c9d0e1f2'
down_revision: str | None = 'c1d2e3f4a5b6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'regulation_chunks',
        sa.Column(
            'entity_ids',
            ARRAY(UUID(as_uuid=True)),
            nullable=True,
            comment='关联的知识图谱实体节点 ID（用于图谱导航后过滤 chunks）',
        ),
        schema='safety',
    )


def downgrade() -> None:
    op.drop_column('regulation_chunks', 'entity_ids', schema='safety')
