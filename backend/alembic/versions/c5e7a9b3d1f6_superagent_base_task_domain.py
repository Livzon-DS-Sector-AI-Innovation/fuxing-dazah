"""superagent 底座迁移 C —— 任务域 3 表（tasks/subscriptions/inputs）

- agent_tasks：阶段不落库（stage_facts 事实 + derive_stage 纯函数现算）
- agent_task_subscriptions：开单即订阅 origin Thread；(task,thread) 唯一
- agent_inputs：delivered_at/read_at 双时间戳（计入会话历史才算读）
播种：无

Revision ID: c5e7a9b3d1f6
Revises: b4d6f8a2c5e7
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "c5e7a9b3d1f6"
down_revision: str | None = "b4d6f8a2c5e7"
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
        "agent_tasks",
        _uuid_pk(),
        sa.Column("short_name", sa.String(128), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("executor", sa.String(64), nullable=False),
        sa.Column("origin_trigger_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("mandate", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column("stage_facts", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("outcome", sa.String(64), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=_SCHEMA,
        comment="任务（一次被授权的工作；阶段不落库）",
    )
    op.create_index("ix_agent_tasks_status", "agent_tasks", ["status"], schema=_SCHEMA)
    op.create_index(
        "ix_agent_tasks_origin_trigger", "agent_tasks", ["origin_trigger_id"], schema=_SCHEMA,
    )

    op.create_table(
        "agent_task_subscriptions",
        _uuid_pk(),
        sa.Column("task_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_key", sa.String(512), nullable=False),
        sa.Column("context_only", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("task_id", "thread_key", name="uq_agent_task_subscriptions"),
        schema=_SCHEMA,
        comment="任务订阅（ended 任务保留订阅，人的消息可唤醒）",
    )
    op.create_index(
        "ix_agent_task_subscriptions_thread", "agent_task_subscriptions", ["thread_key"],
        schema=_SCHEMA,
    )

    op.create_table(
        "agent_inputs",
        _uuid_pk(),
        sa.Column("task_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False, server_default="trigger"),
        sa.Column("payload", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=_SCHEMA,
        comment="任务输入（read_at=计入会话历史才算读）",
    )
    op.create_index(
        "ix_agent_inputs_task_read", "agent_inputs", ["task_id", "read_at"], schema=_SCHEMA,
    )
    op.create_index("ix_agent_inputs_trigger", "agent_inputs", ["trigger_id"], schema=_SCHEMA)


def downgrade() -> None:
    op.drop_table("agent_inputs", schema=_SCHEMA)
    op.drop_table("agent_task_subscriptions", schema=_SCHEMA)
    op.drop_table("agent_tasks", schema=_SCHEMA)
