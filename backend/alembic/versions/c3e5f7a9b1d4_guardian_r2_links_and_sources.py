"""R2 监护人资格追踪 —— links 表 + 双源播种 + 旧持证预警任务停用

- safety.guardian_qualification_links：资格状态权威表（提醒计数/资格流转/
  考核事件流；UNIQUE(record_id) WHERE is_deleted=false 幂等第三道保险）
- superagent.agent_sources 播种两源（enabled=false，三层开关默认全关）：
  * safety.guardian.r2（kind=guardian_cert_scan 应用侧自定义 cron 门控，
    每日 08:00 扫监护人 A/B 证表——"cron_scan" kind 已被 R1 消防源占用）
  * safety.guardian.score（kind=guardian_score_poll 应用侧子类，
    扫《理论考试分数表》）
- safety.scheduler_task_configs upsert：「持证到期预警」enabled=false
  （拍板⑤：特种作业证退出追踪，监护人走 R2 链路，避免双重提醒）
播种/停用幂等可重跑（源 ON CONFLICT DO NOTHING；任务行仅缺失时插入）。

Revision ID: c3e5f7a9b1d4
Revises: d4e7a1c35b82
Create Date: 2026-11-04
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "c3e5f7a9b1d4"
down_revision: str | None = "d4e7a1c35b82"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CERT_SOURCE_CONFIG = {
    "schedule": {
        "strategy": "cron",
        "expression": "0 8 * * *",
        "timezone": "Asia/Shanghai",
    },
    "evaluate": True,
    "thread_prefix": "guardian_cert",
}

_SCORE_SOURCE_CONFIG = {
    "fetcher": "guardian_score_ledger",
    "relevant_fields": ["姓名", "报名考试类型", "考试分数", "是否合格", "参加考试日期"],
    "evaluate": True,
    "thread_prefix": "guardian_score",
}

_OLD_JOB_NAME = "持证到期预警"


def _seed_source(name: str, kind: str, config: dict) -> None:
    op.execute(
        """
        INSERT INTO superagent.agent_sources (kind, name, config, enabled)
        VALUES ('{kind}', '{name}', '{config}'::jsonb, false)
        ON CONFLICT (name) DO NOTHING
        """.format(
            kind=kind,
            name=name,
            config=json.dumps(config, ensure_ascii=False).replace("'", "''"),
        )
    )


def upgrade() -> None:
    op.create_table(
        "guardian_qualification_links",
        sa.Column("id", UUID(), server_default=sa.text("gen_random_uuid()"),
                  nullable=False, primary_key=True),
        sa.Column("record_id", sa.String(64), nullable=False),
        sa.Column("person_name", sa.String(64), nullable=False),
        sa.Column("department", sa.String(64), nullable=True),
        sa.Column("cert_category", sa.String(16), nullable=False),
        sa.Column("remind_count", sa.Integer(), server_default=sa.text("0"),
                  nullable=False),
        sa.Column("last_reminded_month", sa.String(7), nullable=True),
        sa.Column("qualification_status", sa.String(16),
                  server_default=sa.text("'active'"), nullable=False),
        sa.Column("revoked_reason", sa.String(128), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.String(128), nullable=True),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by", sa.String(128), nullable=True),
        sa.Column("current_node", sa.String(16), nullable=True),
        sa.Column("node_deadline", sa.Date(), nullable=True),
        sa.Column("exam_history", JSONB(), server_default=sa.text("'[]'::jsonb"),
                  nullable=False),
        sa.Column("last_score_event", JSONB(), nullable=True),
        sa.Column("task_id", UUID(), nullable=True),
        sa.Column("snapshot", JSONB(), server_default=sa.text("'{}'::jsonb"),
                  nullable=False),
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
        "uq_guardian_qualification_links", "guardian_qualification_links",
        ["record_id"], schema="safety", unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_guardian_qual_links_status", "guardian_qualification_links",
        ["qualification_status"], schema="safety",
    )
    _seed_source("safety.guardian.r2", "guardian_cert_scan", _CERT_SOURCE_CONFIG)
    _seed_source("safety.guardian.score", "guardian_score_poll", _SCORE_SOURCE_CONFIG)
    # 旧「持证到期预警」任务停用（拍板⑤）：行缺失插入 / 已存在则置 false
    # （本迁移即停用动作本体；人工日后重启改回 true 不受影响——迁移只跑一次）。
    # id 无 server_default 需显式给。
    op.execute(
        """
        INSERT INTO safety.scheduler_task_configs (id, job_name, enabled)
        VALUES (gen_random_uuid(), '{name}', false)
        ON CONFLICT DO UPDATE SET enabled = false
        """.format(name=_OLD_JOB_NAME)
    )


def downgrade() -> None:
    # 只删本迁移插入的停用行（若人工改过配置则保留）
    op.execute(
        """
        DELETE FROM safety.scheduler_task_configs
        WHERE job_name = '{name}' AND enabled = false
        """.format(name=_OLD_JOB_NAME)
    )
    op.execute(
        "DELETE FROM superagent.agent_sources WHERE name IN "
        "('safety.guardian.r2', 'safety.guardian.score')"
    )
    op.drop_index(
        "ix_guardian_qual_links_status", table_name="guardian_qualification_links",
        schema="safety",
    )
    op.drop_index(
        "uq_guardian_qualification_links", table_name="guardian_qualification_links",
        schema="safety",
    )
    op.drop_table("guardian_qualification_links", schema="safety")
