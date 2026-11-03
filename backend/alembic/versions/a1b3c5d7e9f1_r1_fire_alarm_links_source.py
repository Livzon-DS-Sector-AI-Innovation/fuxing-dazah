"""R1 报警联动（消防域）—— links 瘦身表 + cron_scan 源实例播种（默认停用）

- safety.alarm_hazard_links：报警↔隐患业务关联映射（§9.2 瘦身版，状态由
  decision 处置派生不自管；部分唯一索引=幂等第三道保险）
- superagent.agent_sources 播种 safety.fire_alarm.r1（kind=cron_scan，
  17:15 cron / 7 天窗口 / 三字段指纹 / evaluate=true，enabled=false——
  开关链三层全默认关）
播种一律 ON CONFLICT DO NOTHING（幂等播种铁律）。

Revision ID: a1b3c5d7e9f1
Revises: f8b0d2e4a6c1
Create Date: 2026-11-03
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "a1b3c5d7e9f1"
down_revision: str | None = "f8b0d2e4a6c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOURCE_CONFIG = {
    "schedule": {
        "strategy": "cron",
        "expression": "15 17 * * *",
        "timezone": "Asia/Shanghai",
    },
    "window_days": 7,
    "relevant_fields": ["报警性质", "报警原因分类", "处理情况"],
    "evaluate": True,
    "thread_prefix": "fire_alarm",
}


def upgrade() -> None:
    op.create_table(
        "alarm_hazard_links",
        sa.Column("id", UUID(), server_default=sa.text("gen_random_uuid()"),
                  nullable=False, primary_key=True),
        sa.Column("alarm_domain", sa.String(16), nullable=False),
        sa.Column("alarm_record_id", sa.String(64), nullable=False),
        sa.Column("alarm_fingerprint", sa.String(32), nullable=True),
        sa.Column("hazard_record_id", sa.String(64), nullable=True),
        sa.Column("hazard_no", sa.String(64), nullable=True),
        sa.Column("task_id", UUID(), nullable=True),
        sa.Column("decided_by", sa.String(128), nullable=True),
        sa.Column("alarm_snapshot", JSONB(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"),
                  nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("created_by", UUID(), nullable=True),
        sa.Column("updated_by", UUID(), nullable=True),
        schema="safety",
    )
    op.create_index(
        "ix_alarm_hazard_links_task", "alarm_hazard_links", ["task_id"], schema="safety",
    )
    op.create_index(
        "uq_alarm_hazard_links", "alarm_hazard_links",
        ["alarm_domain", "alarm_record_id"], schema="safety",
        unique=True, postgresql_where=sa.text("is_deleted = false"),
    )
    op.execute(
        """
        INSERT INTO superagent.agent_sources (kind, name, config, enabled)
        VALUES (
            'cron_scan', 'safety.fire_alarm.r1',
            '{config}'::jsonb,
            false
        )
        ON CONFLICT (name) DO NOTHING
        """.format(
            config=json.dumps(_SOURCE_CONFIG, ensure_ascii=False).replace("'", "''")
        )
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM superagent.agent_sources WHERE name = 'safety.fire_alarm.r1'"
    )
    op.drop_index("uq_alarm_hazard_links", table_name="alarm_hazard_links", schema="safety")
    op.drop_index("ix_alarm_hazard_links_task", table_name="alarm_hazard_links", schema="safety")
    op.drop_table("alarm_hazard_links", schema="safety")
