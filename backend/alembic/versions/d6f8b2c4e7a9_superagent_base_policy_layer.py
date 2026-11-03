"""superagent 底座迁移 D —— 策略层 2 表（policies/decisions）

- agent_policies：版本不可变（version_hash 唯一）；当前版本=最新 created_at 行
- agent_decisions：observe 回放数据源（would_accept/policy_version/replay）
播种：无（首个 Policy 由部署侧 apply_new_policy 落，冒烟③随 T08 落）

Revision ID: d6f8b2c4e7a9
Revises: c5e7a9b3d1f6
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "d6f8b2c4e7a9"
down_revision: str | None = "c5e7a9b3d1f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "superagent"


def _uuid_pk() -> sa.Column:
    return sa.Column(
        "id", pg.UUID(as_uuid=True), primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def upgrade() -> None:
    op.create_table(
        "agent_policies",
        _uuid_pk(),
        sa.Column("version_hash", sa.String(64), nullable=False),
        sa.Column("rules", pg.JSONB(), nullable=False, server_default="[]"),
        sa.Column("accept_mode", sa.String(16), nullable=False, server_default="observe"),
        sa.Column("admission", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("version_hash", name="uq_agent_policies_version"),
        schema=_SCHEMA,
        comment="Policy 版本（不可变；rules+accept_mode+admission 哈希成版本号）",
    )

    op.create_table(
        "agent_decisions",
        _uuid_pk(),
        sa.Column("trigger_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_id", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("would_accept", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("reason", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("replay", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=_SCHEMA,
        comment="研判决策（observe 回放数据源）",
    )
    op.create_index(
        "ix_agent_decisions_trigger", "agent_decisions", ["trigger_id"], schema=_SCHEMA,
    )
    op.create_index(
        "ix_agent_decisions_replay", "agent_decisions", ["replay", "created_at"], schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("agent_decisions", schema=_SCHEMA)
    op.drop_table("agent_policies", schema=_SCHEMA)
