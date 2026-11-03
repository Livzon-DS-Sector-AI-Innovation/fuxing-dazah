"""superagent 迁移 F —— decisions.eval_id 列（§5 字段补齐：同批研判分组 id）

Revision ID: f8b0d2e4a6c1
Revises: e7a9c3d5f1b8
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "f8b0d2e4a6c1"
down_revision: str | None = "e7a9c3d5f1b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "superagent"


def upgrade() -> None:
    op.add_column(
        "agent_decisions",
        sa.Column("eval_id", pg.UUID(as_uuid=True), nullable=True,
                  comment="同批研判分组 id"),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("agent_decisions", "eval_id", schema=_SCHEMA)
