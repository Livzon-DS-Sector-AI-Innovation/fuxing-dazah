"""add knowledge_graph_nodes and knowledge_graph_edges tables

Revision ID: a3b4c5d6e7f8
Revises: 5929fcca8939
Create Date: 2026-07-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, None] = '5929fcca8939'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table: str, schema: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = :schema AND table_name = :table"
        ),
        {"schema": schema, "table": table},
    )
    return result.scalar() is not None


def upgrade() -> None:
    schema = "safety"

    # ── knowledge_graph_nodes ──
    if not _table_exists("knowledge_graph_nodes", schema):
        op.create_table(
            "knowledge_graph_nodes",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("name", sa.String(500), nullable=False, comment="节点名称（规范术语）"),
            sa.Column("node_type", sa.String(32), nullable=False, comment="节点类型: document/clause/entity/category/concept"),
            sa.Column("aliases", postgresql.ARRAY(sa.Text()), nullable=True, comment="同义词/别名列表"),
            sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=True, index=True, comment="关联 knowledge_articles.id"),
            sa.Column("entity_type", sa.String(32), nullable=True, comment="实体类别"),
            sa.Column("ai_summary", sa.Text(), nullable=True, comment="AI 生成摘要"),
            sa.Column("confidence", sa.Double(), nullable=True, comment="AI 置信度"),
            sa.Column("status", sa.String(32), nullable=False, server_default="ai_generated", comment="节点状态"),
            sa.Column("merged_into_id", postgresql.UUID(as_uuid=True), nullable=True, comment="合并目标节点 ID"),
            sa.Column("metadata", postgresql.JSONB(), nullable=True, comment="扩展元数据"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), server_default="false", default=False),
            schema=schema,
        )
        op.create_index("ix_graph_nodes_type", "knowledge_graph_nodes", ["node_type"], schema=schema)
        op.create_index("ix_graph_nodes_article", "knowledge_graph_nodes", ["article_id"], schema=schema)

    # ── knowledge_graph_edges ──
    if not _table_exists("knowledge_graph_edges", schema):
        op.create_table(
            "knowledge_graph_edges",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("source_node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("safety.knowledge_graph_nodes.id", ondelete="CASCADE"), nullable=False, index=True, comment="源节点 ID"),
            sa.Column("target_node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("safety.knowledge_graph_nodes.id", ondelete="CASCADE"), nullable=False, index=True, comment="目标节点 ID"),
            sa.Column("relation_type", sa.String(32), nullable=False, index=True, comment="关系类型"),
            sa.Column("description", sa.Text(), nullable=True, comment="AI 对关系的简短解释"),
            sa.Column("evidence_text", sa.Text(), nullable=True, comment="支持该关系的原文片段"),
            sa.Column("confidence", sa.Double(), nullable=True, comment="AI 置信度"),
            sa.Column("status", sa.String(32), nullable=False, server_default="ai_generated", comment="边状态"),
            sa.Column("metadata", postgresql.JSONB(), nullable=True, comment="扩展元数据"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), server_default="false", default=False),
            sa.UniqueConstraint("source_node_id", "target_node_id", "relation_type"),
            schema=schema,
        )
        op.create_index("ix_graph_edges_source", "knowledge_graph_edges", ["source_node_id"], schema=schema)
        op.create_index("ix_graph_edges_target", "knowledge_graph_edges", ["target_node_id"], schema=schema)
        op.create_index("ix_graph_edges_type", "knowledge_graph_edges", ["relation_type"], schema=schema)


def downgrade() -> None:
    schema = "safety"

    for table in ("knowledge_graph_edges", "knowledge_graph_nodes"):
        if _table_exists(table, schema):
            op.drop_table(table, schema=schema)
