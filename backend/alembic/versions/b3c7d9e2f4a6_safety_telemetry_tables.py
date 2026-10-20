"""safety telemetry 两表（时序快照/报警记录，facilities-p2）

DESIGN §3.2：telemetry_snapshots 唯一 (equipment_no, metric, recorded_at) =
采集幂等落库（PG 唯一索引对 NULL 不去重——pending_review 待补录行设备/指标
可空，天然走非幂等路径，由 raw_message_id 防重）；telemetry_alarm_records
dedupe_key = 设备|指标|级别|静默窗时间桶，唯一约束实现「同窗同源不重发」。
无种子。

Revision ID: b3c7d9e2f4a6
Revises: f1a2b3c4d5e6
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b3c7d9e2f4a6"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
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
        "telemetry_snapshots",
        sa.Column(
            "equipment_no", sa.String(length=64), nullable=True,
            comment="设备编号（pending_review 待归属行可空）",
        ),
        sa.Column(
            "metric", sa.String(length=64), nullable=True,
            comment="指标名（汽压/水位/炉膛温度…；待补录行可空）",
        ),
        sa.Column(
            "value", sa.Float(), nullable=True,
            comment="读数值（解析失败行可空，人工补录后回填）",
        ),
        sa.Column(
            "unit", sa.String(length=32), nullable=True,
            comment="单位（MPa/mm/℃…）",
        ),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), nullable=False,
            comment="读数时间（消息 create_time 或人工指定）",
        ),
        sa.Column(
            "raw_message_id", sa.String(length=64), nullable=True,
            comment="来源群消息 message_id（溯源回群）",
        ),
        sa.Column(
            "parse_method", sa.String(length=16), server_default="template",
            nullable=False, comment="解析方式：template / ai / manual",
        ),
        sa.Column(
            "raw_excerpt", sa.Text(), nullable=True,
            comment="原消息文本摘录（待补录列表展示）",
        ),
        sa.Column(
            "parse_status", sa.String(length=16), server_default="ok",
            nullable=False, comment="ok / pending_review（解析失败待人工补录）",
        ),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id"),
        *_base_fks(),
        schema="safety",
    )
    op.create_index(
        "uq_telemetry_snapshots_eq_metric_at",
        "telemetry_snapshots",
        ["equipment_no", "metric", "recorded_at"],
        schema="safety",
        unique=True,
    )
    op.create_index(
        "ix_telemetry_snapshots_raw_message",
        "telemetry_snapshots",
        ["raw_message_id"],
        schema="safety",
    )

    op.create_table(
        "telemetry_alarm_records",
        sa.Column("equipment_no", sa.String(length=64), nullable=False),
        sa.Column("metric", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Float(), nullable=True, comment="触发时读数"),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), nullable=False,
            comment="触发读数的快照时间",
        ),
        sa.Column(
            "rule_desc", sa.Text(), nullable=False,
            comment="命中规则的人读描述（如「汽压超上限 1.0MPa」）",
        ),
        sa.Column(
            "level", sa.String(length=16), nullable=False,
            comment="warning / alarm",
        ),
        sa.Column(
            "status", sa.String(length=16), server_default="firing", nullable=False,
            comment="firing / acked / resolved",
        ),
        sa.Column("acked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "acked_by", sa.String(length=64), nullable=True,
            comment="值班确认人（open_id / system）",
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "resolution_note", sa.Text(), nullable=True,
            comment="处置说明（resolved 必填）",
        ),
        sa.Column(
            "dedupe_key", sa.String(length=128), nullable=False,
            comment="设备|指标|级别|静默窗时间桶（同窗同源唯一，防刷屏）",
        ),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id"),
        *_base_fks(),
        schema="safety",
    )
    op.create_index(
        "uq_telemetry_alarm_dedupe",
        "telemetry_alarm_records",
        ["dedupe_key"],
        schema="safety",
        unique=True,
    )
    op.create_index(
        "ix_telemetry_alarm_status",
        "telemetry_alarm_records",
        ["status"],
        schema="safety",
    )
    op.create_index(
        "ix_telemetry_alarm_equipment",
        "telemetry_alarm_records",
        ["equipment_no"],
        schema="safety",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_telemetry_alarm_equipment",
        table_name="telemetry_alarm_records", schema="safety",
    )
    op.drop_index(
        "ix_telemetry_alarm_status",
        table_name="telemetry_alarm_records", schema="safety",
    )
    op.drop_index(
        "uq_telemetry_alarm_dedupe",
        table_name="telemetry_alarm_records", schema="safety",
    )
    op.drop_table("telemetry_alarm_records", schema="safety")
    op.drop_index(
        "ix_telemetry_snapshots_raw_message",
        table_name="telemetry_snapshots", schema="safety",
    )
    op.drop_index(
        "uq_telemetry_snapshots_eq_metric_at",
        table_name="telemetry_snapshots", schema="safety",
    )
    op.drop_table("telemetry_snapshots", schema="safety")
