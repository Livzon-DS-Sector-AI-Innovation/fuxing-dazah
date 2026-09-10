"""add bitable_connections, bitable_field_mappings, bitable_config_audits tables + seed

Revision ID: bitable001b2c3d4e5
Revises: sched003a1b2c3d4
Create Date: 2026-08-28 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bitable001b2c3d4e5"
down_revision: str | None = "sched003a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _connection_seed_rows() -> list[dict]:
    """播种 24 连接行 — 值单向导出自 registry.default_connection（禁止手抄）。"""
    from app.modules.safety.bitable_config.registry import iter_connection_kinds

    rows: list[dict] = []
    for domain, kind in iter_connection_kinds():
        conn = kind.default_connection
        assert conn is not None
        rows.append(
            {
                "domain": domain.key,
                "kind": kind.kind,
                "app_token": conn.app_token,
                "table_id": conn.table_id,
                "enabled": True,
                "extra_table_ids": list(conn.extra_table_ids) if conn.extra_table_ids else None,
                "note": conn.note or None,
            }
        )
    assert len(rows) == 24, f"registry 连接行数应为 24，实际 {len(rows)}"
    return rows


def _mapping_seed_rows() -> list[dict]:
    """播种 24 映射行（一行一域一 kind）— 值单向导出自 registry.default_mappings。"""
    from app.modules.safety.bitable_config.registry import iter_mapping_kinds

    rows: list[dict] = []
    for domain, kind in iter_mapping_kinds():
        rows.append(
            {
                "domain": domain.key,
                "kind": kind.kind,
                "mappings": list(kind.default_mappings),
            }
        )
    assert len(rows) == 24, f"registry 映射行数应为 24，实际 {len(rows)}"
    return rows


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS safety")

    bitable_connections = op.create_table(
        "bitable_connections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "domain",
            sa.String(64),
            nullable=False,
            comment="域 key（registry 注册，如 oh）",
        ),
        sa.Column(
            "kind",
            sa.String(64),
            nullable=False,
            comment="表类型 key（如 exam_registry）",
        ),
        sa.Column(
            "app_token",
            sa.String(128),
            nullable=False,
            comment="飞书多维表格 app_token（base/wiki 文档 token）",
        ),
        sa.Column(
            "table_id",
            sa.String(128),
            nullable=False,
            comment="表 table_id（central_alarm 为白名单主表）",
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default="true",
            comment="是否启用（为 false 时 store 不返回给 handler，视为停用）",
        ),
        sa.Column(
            "extra_table_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="仅 central_alarm：白名单其余表 table_id 列表（不含主表）",
        ),
        sa.Column(
            "note",
            sa.String(255),
            nullable=True,
            comment="备注",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.PrimaryKeyConstraint("id", name=op.f("bitable_connections_pkey")),
        schema="safety",
        comment="Bitable 连接配置表（一行一表，DB 为唯一权威）",
    )
    op.create_index(
        "uq_bitable_connections_domain_kind",
        "bitable_connections",
        ["domain", "kind"],
        unique=True,
        schema="safety",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_bitable_connections_domain",
        "bitable_connections",
        ["domain"],
        schema="safety",
    )

    bitable_field_mappings = op.create_table(
        "bitable_field_mappings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "domain",
            sa.String(64),
            nullable=False,
            comment="域 key",
        ),
        sa.Column(
            "kind",
            sa.String(64),
            nullable=False,
            comment="表类型 key",
        ),
        sa.Column(
            "mappings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="字段映射列表，见 backend-design §2.2 JSONB 结构",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.PrimaryKeyConstraint("id", name=op.f("bitable_field_mappings_pkey")),
        schema="safety",
        comment="Bitable 字段映射表（一行一域一 kind，JSONB 全量替换）",
    )
    op.create_index(
        "uq_bitable_field_mappings_domain_kind",
        "bitable_field_mappings",
        ["domain", "kind"],
        unique=True,
        schema="safety",
        postgresql_where=sa.text("is_deleted = false"),
    )

    op.create_table(
        "bitable_config_audits",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "domain",
            sa.String(64),
            nullable=False,
            comment="域 key",
        ),
        sa.Column(
            "kind",
            sa.String(64),
            nullable=False,
            comment="表类型 key（域级操作时为 '*'）",
        ),
        sa.Column(
            "action",
            sa.String(32),
            nullable=False,
            comment="动作: update/enable/disable/resubscribe 等",
        ),
        sa.Column(
            "before_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="变更前（compact）",
        ),
        sa.Column(
            "after_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="变更后（compact）",
        ),
        sa.Column(
            "operator_name",
            sa.String(128),
            nullable=True,
            comment="操作人 name",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.PrimaryKeyConstraint("id", name=op.f("bitable_config_audits_pkey")),
        schema="safety",
        comment="Bitable 配置变更审计表（append-only）",
    )
    op.create_index(
        "idx_bitable_config_audits_domain_created",
        "bitable_config_audits",
        ["domain", "created_at"],
        schema="safety",
    )

    # ── 播种：24 连接行 + 24 映射行（值从 registry 单向导出，勿手抄）──
    op.bulk_insert(bitable_connections, _connection_seed_rows())
    op.bulk_insert(bitable_field_mappings, _mapping_seed_rows())


def downgrade() -> None:
    op.drop_index(
        "idx_bitable_config_audits_domain_created",
        table_name="bitable_config_audits",
        schema="safety",
    )
    op.drop_table("bitable_config_audits", schema="safety")
    op.drop_index(
        "uq_bitable_field_mappings_domain_kind",
        table_name="bitable_field_mappings",
        schema="safety",
    )
    op.drop_table("bitable_field_mappings", schema="safety")
    op.drop_index(
        "ix_bitable_connections_domain",
        table_name="bitable_connections",
        schema="safety",
    )
    op.drop_index(
        "uq_bitable_connections_domain_kind",
        table_name="bitable_connections",
        schema="safety",
    )
    op.drop_table("bitable_connections", schema="safety")
