"""safety ehs_change_followup 三表 —— EHS 变更周度督办（周五提醒 + 周一总结）

DESIGN §7（docs/DESIGN-EHS变更域-周度督办周五提醒与周一总结-设计-20261124.md）：
rounds 一轮=一个周五 / dispatches 一行=一位安全员一张卡 / items 一行=一轮一项变更。
落库理由：周一比对周五进展快照、dispatch.send_status 防重启重发、
items 历史可溯「第 N 周督办」。无种子。

⚠️ down_revision 挂 o3a5c7e9b1d3（实施时点核实的主链头节点，
hardware_urgent_flag_closeout）。

Revision ID: d7f2b6e4a9c1
Revises: o3a5c7e9b1d3
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "d7f2b6e4a9c1"
down_revision: str | None = "o3a5c7e9b1d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
    ]


def _base_fks() -> list:
    return [
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
    ]


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS safety")
    op.create_table(
        "ehs_change_followup_rounds",
        sa.Column("year", sa.Integer(), nullable=False, comment="ISO 年"),
        sa.Column("week_no", sa.Integer(), nullable=False, comment="ISO 周号"),
        sa.Column("fired_on", sa.Date(), nullable=False, comment="触发日（周五）"),
        sa.Column(
            "status", sa.String(length=16), nullable=False,
            comment="sending/sent/summarized",
        ),
        sa.Column(
            "stats", JSONB(), nullable=True,
            comment="轮次统计快照（周五/周一各写一次）",
        ),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("year", "week_no", name="uq_ehs_change_followup_rounds_week"),
        *_base_fks(),
        schema="safety",
    )
    op.create_index(
        "ix_ehs_change_followup_rounds_fired_on",
        "ehs_change_followup_rounds", ["fired_on"], schema="safety",
    )

    op.create_table(
        "ehs_change_followup_dispatches",
        sa.Column(
            "round_id", sa.Uuid(), nullable=False,
            comment="所属轮次（safety.ehs_change_followup_rounds.id）",
        ),
        sa.Column("officer_name", sa.String(length=64), nullable=False, comment="分管安全员姓名"),
        sa.Column(
            "officer_open_id", sa.String(length=64), nullable=True,
            comment="安全应用作用域 open_id（发送锚点）",
        ),
        sa.Column(
            "officer_user_id", sa.String(length=64), nullable=True,
            comment="租户级 user_id（identity 来源时用它发送）",
        ),
        sa.Column(
            "departments", sa.String(length=256), nullable=False,
            comment="覆盖部门（逗号分隔；同人跨部门合一卡）",
        ),
        sa.Column("change_count", sa.Integer(), nullable=False, comment="卡内变更项数"),
        sa.Column(
            "send_status", sa.String(length=16), nullable=False,
            comment="pending/sent/failed/unresolved",
        ),
        sa.Column(
            "message_id", sa.String(length=64), nullable=True,
            comment="周五卡 message_id（om_…，PATCH 锚点）",
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("send_error", sa.Text(), nullable=True),
        sa.Column(
            "response_type", sa.String(length=16), nullable=True,
            comment="空=未反馈；unchanged=点了「进展不变」",
        ),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "category", sa.String(length=16), nullable=True,
            comment="周一判出的该安全员主分类（updated/unchanged/not_updated）",
        ),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["round_id"], ["safety.ehs_change_followup_rounds.id"], ondelete="CASCADE",
        ),
        *_base_fks(),
        schema="safety",
    )
    op.create_index(
        "ix_ehs_change_followup_dispatches_round",
        "ehs_change_followup_dispatches", ["round_id"], schema="safety",
    )

    op.create_table(
        "ehs_change_followup_items",
        sa.Column(
            "round_id", sa.Uuid(), nullable=False,
            comment="所属轮次（safety.ehs_change_followup_rounds.id）",
        ),
        sa.Column(
            "dispatch_id", sa.Uuid(), nullable=True,
            comment="所属卡（无人可发时为空）",
        ),
        sa.Column("record_id", sa.String(length=64), nullable=False, comment="审批表 record_id"),
        sa.Column("change_no", sa.String(length=64), nullable=False, comment="变更申请编号"),
        sa.Column("title", sa.String(length=256), nullable=True, comment="变更名称"),
        sa.Column(
            "department", sa.String(length=128), nullable=False,
            comment="申请部门（多部门逗号分隔）",
        ),
        sa.Column(
            "status_shown", sa.String(length=32), nullable=True,
            comment="「变更状态」原样留存（仅展示，不参与关闭判定）",
        ),
        sa.Column(
            "acceptance_note", sa.String(length=64), nullable=True,
            comment="排除项标注（验收单审批中/已撤回/疑似覆盖/未找到）",
        ),
        sa.Column(
            "progress_friday", sa.Text(), nullable=True,
            comment="周五时点「变更最新具体进展」全文",
        ),
        sa.Column("expected_start", sa.String(length=16), nullable=True, comment="预计实施日期"),
        sa.Column("approval_url", sa.String(length=512), nullable=True, comment="审批详情 applink"),
        sa.Column(
            "nag_weeks", sa.Integer(), nullable=False,
            comment="第 N 周督办（历史轮次同 record 计数+1）",
        ),
        sa.Column(
            "replied_progress", sa.Text(), nullable=True,
            comment="最近一次卡片提交的进展原文",
        ),
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replied_by", sa.String(length=64), nullable=True, comment="提交人标识"),
        sa.Column(
            "progress_monday", sa.Text(), nullable=True,
            comment="周一复查时点进展全文（未复查为空）",
        ),
        sa.Column(
            "outcome", sa.String(length=16), nullable=True,
            comment="closed/updated/unchanged/not_updated（周一写入）",
        ),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "round_id", "record_id",
            name="uq_ehs_change_followup_items_round_record",
        ),
        sa.ForeignKeyConstraint(
            ["round_id"], ["safety.ehs_change_followup_rounds.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dispatch_id"], ["safety.ehs_change_followup_dispatches.id"], ondelete="SET NULL",
        ),
        *_base_fks(),
        schema="safety",
    )
    op.create_index(
        "ix_ehs_change_followup_items_record",
        "ehs_change_followup_items", ["record_id"], schema="safety",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ehs_change_followup_items_record",
        table_name="ehs_change_followup_items", schema="safety",
    )
    op.drop_table("ehs_change_followup_items", schema="safety")
    op.drop_index(
        "ix_ehs_change_followup_dispatches_round",
        table_name="ehs_change_followup_dispatches", schema="safety",
    )
    op.drop_table("ehs_change_followup_dispatches", schema="safety")
    op.drop_index(
        "ix_ehs_change_followup_rounds_fired_on",
        table_name="ehs_change_followup_rounds", schema="safety",
    )
    op.drop_table("ehs_change_followup_rounds", schema="safety")
