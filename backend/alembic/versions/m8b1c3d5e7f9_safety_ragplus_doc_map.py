"""safety ragplus_doc_map（外接知识层入库幂等映射表）

dazah 文档 ↔ ragplus-x 文档映射：(domain, biz_key) 唯一（软删除外）。
法规 biz_key=feishu_record_id；MSDS=collection_record_id（PDF 粒度）。
一期壳换芯（ragplus-x 接入设计 §5.1）。

Revision ID: m8b1c3d5e7f9
Revises: c9f2a8e4d6b1
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "m8b1c3d5e7f9"
down_revision: str | None = "c9f2a8e4d6b1"
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
        "ragplus_doc_map",
        sa.Column(
            "domain",
            sa.String(length=16),
            nullable=False,
            comment="业务域: regulation | msds",
        ),
        sa.Column(
            "biz_key",
            sa.String(length=128),
            nullable=False,
            comment="幂等键：法规=feishu_record_id / MSDS=collection_record_id",
        ),
        sa.Column(
            "dataset_name",
            sa.String(length=64),
            nullable=False,
            comment="ragplus 库名（安全法规标准/MSDS/已废止）",
        ),
        sa.Column(
            "kb_doc_id",
            sa.Integer(),
            nullable=True,
            comment="ragplus KBDocument id（管理端删除用）",
        ),
        sa.Column(
            "engine_doc_id",
            sa.String(length=128),
            nullable=True,
            comment="引擎文档 id（retrieval 命中 document_id）",
        ),
        sa.Column(
            "dataset_id",
            sa.String(length=128),
            nullable=True,
            comment="引擎 dataset id",
        ),
        sa.Column(
            "version",
            sa.Integer(),
            server_default="1",
            nullable=False,
            comment="入库版本号",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="active",
            nullable=False,
            comment="状态: active | archived | failed | deleted",
        ),
        sa.Column("title", sa.String(length=255), nullable=True, comment="对账用标题"),
        sa.Column(
            "file_name", sa.String(length=512), nullable=True, comment="上传文件名"
        ),
        sa.Column("last_error", sa.Text(), nullable=True, comment="最近失败原因"),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="最近同步成功时间",
        ),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id"),
        *_base_fks(),
        schema="safety",
    )
    op.create_index(
        "uq_ragplus_doc_map_domain_biz",
        "ragplus_doc_map",
        ["domain", "biz_key"],
        unique=True,
        schema="safety",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_ragplus_doc_map_status", "ragplus_doc_map", ["status"], schema="safety"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ragplus_doc_map_status", table_name="ragplus_doc_map", schema="safety"
    )
    op.drop_index(
        "uq_ragplus_doc_map_domain_biz",
        table_name="ragplus_doc_map",
        schema="safety",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_table("ragplus_doc_map", schema="safety")
