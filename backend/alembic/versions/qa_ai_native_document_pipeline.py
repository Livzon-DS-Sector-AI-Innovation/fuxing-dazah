"""add QA native document extraction, chunks and AI proposal infrastructure.

The migration is additive.  Existing ``document_text_segments`` rows remain
readable as legacy evidence (their extraction_run_id is NULL); new uploads use
the versioned raw-block/chunk pipeline.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.schema import SchemaItem

from alembic import op

revision: str = "qa_ai_native_pipeline_001"
down_revision: str | None = "29a6d85011bd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base_columns() -> list[SchemaItem]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
        sa.PrimaryKeyConstraint("id"),
    ]


def upgrade() -> None:
    op.add_column(
        "document_types",
        sa.Column("ai_source_policy", sa.String(24), server_default="authoritative", nullable=False,
                  comment="AI 来源策略：authoritative/reference/disabled"),
        schema="qa",
    )
    op.create_check_constraint(
        "ck_qa_document_types_ai_source_policy",
        "document_types",
        "ai_source_policy IN ('authoritative', 'reference', 'disabled')",
        schema="qa",
    )
    op.add_column("document_files", sa.Column("parser_mode", sa.String(32), server_default="native_text", nullable=False), schema="qa")
    op.add_column("document_files", sa.Column("parser_version", sa.String(64), nullable=True), schema="qa")
    op.add_column("document_files", sa.Column("current_extraction_run_id", sa.Uuid(), nullable=True), schema="qa")
    op.add_column("document_files", sa.Column("current_chunk_run_id", sa.Uuid(), nullable=True), schema="qa")
    op.add_column("document_files", sa.Column("extraction_worker_token", sa.String(128), nullable=True), schema="qa")
    op.add_column("document_files", sa.Column("extraction_lease_until", sa.DateTime(timezone=True), nullable=True), schema="qa")

    segment_columns = [
        ("extraction_run_id", sa.Uuid(), True),
        ("source_order", sa.Integer(), True),
        ("block_type", sa.String(32), False),
        ("row_index", sa.Integer(), True),
        ("column_index", sa.Integer(), True),
        ("heading_path", sa.JSON(), True),
        ("source_metadata", sa.JSON(), True),
    ]
    for name, column_type, nullable in segment_columns:
        op.add_column(
            "document_text_segments",
            sa.Column(name, column_type, server_default="paragraph" if name == "block_type" else None,
                      nullable=nullable, comment="raw block v2"),
            schema="qa",
        )

    op.create_index("ix_qa_document_text_segments_run_order", "document_text_segments", ["extraction_run_id", "source_order"], schema="qa")

    op.create_table(
        "document_extraction_runs",
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("parser_mode", sa.String(32), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("block_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("char_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("statistics", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_token", sa.String(128), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_count", sa.SmallInteger(), server_default="0", nullable=False),
        *_base_columns(),
        schema="qa",
    )
    op.create_index("ix_qa_document_extraction_runs_file", "document_extraction_runs", ["file_id", "created_at"], schema="qa")
    op.create_index("ix_qa_document_extraction_runs_queue", "document_extraction_runs", ["status", "lease_until"], schema="qa")
    op.create_index("ix_qa_document_extraction_runs_input", "document_extraction_runs", ["file_id", "input_hash"], schema="qa")

    op.create_table(
        "document_chunk_runs",
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_run_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_version", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("char_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("statistics", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_token", sa.String(128), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        *_base_columns(),
        schema="qa",
    )
    op.create_index("ix_qa_document_chunk_runs_file", "document_chunk_runs", ["file_id", "created_at"], schema="qa")
    op.create_index("ix_qa_document_chunk_runs_extraction", "document_chunk_runs", ["extraction_run_id"], schema="qa")
    op.create_index("ix_qa_document_chunk_runs_queue", "document_chunk_runs", ["status", "lease_until"], schema="qa")

    op.create_table(
        "document_text_chunks",
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_run_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_order", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("heading_path", sa.JSON(), nullable=True),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("source_start", sa.Integer(), nullable=True),
        sa.Column("source_end", sa.Integer(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        *_base_columns(),
        schema="qa",
    )
    op.create_index("uq_qa_document_text_chunks_order", "document_text_chunks", ["chunk_run_id", "chunk_order"], unique=True, schema="qa")
    op.create_index("ix_qa_document_text_chunks_file", "document_text_chunks", ["file_id", "chunk_order"], schema="qa")
    op.create_index("ix_qa_document_text_chunks_hash", "document_text_chunks", ["content_hash"], schema="qa")
    op.create_index("ix_qa_document_text_chunks_content_trgm", "document_text_chunks", ["content"], postgresql_using="gin", postgresql_ops={"content": "gin_trgm_ops"}, schema="qa")

    op.create_table(
        "document_chunk_blocks",
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("segment_id", sa.Uuid(), nullable=False),
        sa.Column("block_order", sa.Integer(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        *_base_columns(),
        schema="qa",
    )
    op.create_index("uq_qa_document_chunk_blocks_identity", "document_chunk_blocks", ["chunk_id", "segment_id"], unique=True, schema="qa")
    op.create_index("ix_qa_document_chunk_blocks_segment", "document_chunk_blocks", ["segment_id"], schema="qa")

    op.create_table(
        "document_ai_analysis_runs",
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_run_id", sa.Uuid(), nullable=True),
        sa.Column("chunk_run_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("catalog_fingerprint", sa.String(64), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("source_policy", sa.String(24), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("retry_count", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("entity_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("suggestion_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("proposal_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("processed_chunks", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_chunks", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_token", sa.String(128), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        *_base_columns(),
        schema="qa",
    )
    op.create_index("ix_qa_document_ai_analysis_runs_version", "document_ai_analysis_runs", ["version_id", "created_at"], schema="qa")
    op.create_index("ix_qa_document_ai_analysis_runs_queue", "document_ai_analysis_runs", ["status", "lease_until"], schema="qa")
    op.create_index("ix_qa_document_ai_analysis_runs_fingerprint", "document_ai_analysis_runs", ["version_id", "input_fingerprint"], schema="qa")

    op.create_table(
        "document_entity_observations",
        sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=True),
        sa.Column("raw_block_id", sa.Uuid(), nullable=True),
        sa.Column("mention_text", sa.String(500), nullable=False),
        sa.Column("normalized_text", sa.String(500), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False, comment="证据定位与片段内容的稳定哈希"),
        sa.Column("locator", sa.String(255), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("paragraph_index", sa.Integer(), nullable=True),
        sa.Column("table_index", sa.Integer(), nullable=True),
        sa.Column("row_index", sa.Integer(), nullable=True),
        sa.Column("column_index", sa.Integer(), nullable=True),
        sa.Column("source_order", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), server_default="0", nullable=False),
        sa.Column("extraction_method", sa.String(32), server_default="deterministic", nullable=False),
        sa.Column("normalization_hint", sa.String(500), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        *_base_columns(),
        schema="qa",
    )
    op.create_index("ix_qa_document_entity_observations_run", "document_entity_observations", ["analysis_run_id", "source_order"], schema="qa")
    op.create_index("ix_qa_document_entity_observations_normalized", "document_entity_observations", ["normalized_text"], schema="qa")
    op.create_index("ix_qa_document_entity_observations_evidence_hash", "document_entity_observations", ["evidence_hash"], schema="qa")

    op.create_table(
        "document_relation_suggestions",
        sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("observation_id", sa.Uuid(), nullable=False),
        sa.Column("master_object_id", sa.Uuid(), nullable=False),
        sa.Column("relation_type", sa.String(32), server_default="APPLIES_TO", nullable=False),
        sa.Column("match_method", sa.String(32), nullable=False),
        sa.Column("rank", sa.Integer(), server_default="1", nullable=False),
        sa.Column("confidence", sa.Float(), server_default="0", nullable=False),
        sa.Column("selected_by_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status", sa.String(24), server_default="pending", nullable=False),
        sa.Column("rationale", sa.String(1000), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        *_base_columns(),
        sa.CheckConstraint("relation_type = 'APPLIES_TO'", name="ck_qa_document_relation_suggestions_type"),
        schema="qa",
    )
    op.create_index(
        "uq_qa_document_relation_suggestions_identity",
        "document_relation_suggestions",
        ["analysis_run_id", "observation_id", "master_object_id"],
        unique=True,
        schema="qa",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index("ix_qa_document_relation_suggestions_run", "document_relation_suggestions", ["analysis_run_id", "status", "rank"], schema="qa")

    op.create_table(
        "master_object_proposals",
        sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("observation_id", sa.Uuid(), nullable=True),
        sa.Column("proposal_type", sa.String(24), nullable=False),
        sa.Column("target_master_object_id", sa.Uuid(), nullable=True),
        sa.Column("object_type", sa.String(32), nullable=False),
        sa.Column("proposed_payload", sa.JSON(), nullable=False),
        sa.Column("field_diffs", sa.JSON(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("conflicts", sa.JSON(), nullable=True),
        sa.Column("base_snapshot", sa.JSON(), nullable=True),
        sa.Column("base_fingerprint", sa.String(64), nullable=True),
        sa.Column("status", sa.String(24), server_default="pending", nullable=False),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        *_base_columns(),
        sa.CheckConstraint(
            "proposal_type IN ('create', 'update')",
            name="ck_qa_master_object_proposals_type",
        ),
        schema="qa",
    )
    op.create_index("ix_qa_master_object_proposals_status", "master_object_proposals", ["status", "created_at"], schema="qa")
    op.create_index("ix_qa_master_object_proposals_run", "master_object_proposals", ["analysis_run_id"], schema="qa")
    op.create_index("ix_qa_master_object_proposals_target", "master_object_proposals", ["target_master_object_id"], schema="qa")


def downgrade() -> None:
    for index_name, table in (
        ("ix_qa_master_object_proposals_target", "master_object_proposals"),
        ("ix_qa_master_object_proposals_run", "master_object_proposals"),
        ("ix_qa_master_object_proposals_status", "master_object_proposals"),
    ):
        op.drop_index(index_name, table_name=table, schema="qa")
    op.drop_table("master_object_proposals", schema="qa")
    for index_name, table in (
        ("ix_qa_document_relation_suggestions_run", "document_relation_suggestions"),
        ("uq_qa_document_relation_suggestions_identity", "document_relation_suggestions"),
    ):
        op.drop_index(index_name, table_name=table, schema="qa")
    op.drop_table("document_relation_suggestions", schema="qa")
    for index_name, table in (
        ("ix_qa_document_entity_observations_evidence_hash", "document_entity_observations"),
        ("ix_qa_document_entity_observations_normalized", "document_entity_observations"),
        ("ix_qa_document_entity_observations_run", "document_entity_observations"),
    ):
        op.drop_index(index_name, table_name=table, schema="qa")
    op.drop_table("document_entity_observations", schema="qa")
    for index_name, table in (
        ("ix_qa_document_ai_analysis_runs_fingerprint", "document_ai_analysis_runs"),
        ("ix_qa_document_ai_analysis_runs_queue", "document_ai_analysis_runs"),
        ("ix_qa_document_ai_analysis_runs_version", "document_ai_analysis_runs"),
    ):
        op.drop_index(index_name, table_name=table, schema="qa")
    op.drop_table("document_ai_analysis_runs", schema="qa")
    for index_name, table in (
        ("ix_qa_document_chunk_blocks_segment", "document_chunk_blocks"),
        ("uq_qa_document_chunk_blocks_identity", "document_chunk_blocks"),
    ):
        op.drop_index(index_name, table_name=table, schema="qa")
    op.drop_table("document_chunk_blocks", schema="qa")
    for index_name in ("ix_qa_document_text_chunks_content_trgm", "ix_qa_document_text_chunks_hash", "ix_qa_document_text_chunks_file", "uq_qa_document_text_chunks_order"):
        op.drop_index(index_name, table_name="document_text_chunks", schema="qa")
    op.drop_table("document_text_chunks", schema="qa")
    for index_name in ("ix_qa_document_chunk_runs_queue", "ix_qa_document_chunk_runs_extraction", "ix_qa_document_chunk_runs_file"):
        op.drop_index(index_name, table_name="document_chunk_runs", schema="qa")
    op.drop_table("document_chunk_runs", schema="qa")
    for index_name in ("ix_qa_document_extraction_runs_input", "ix_qa_document_extraction_runs_queue", "ix_qa_document_extraction_runs_file"):
        op.drop_index(index_name, table_name="document_extraction_runs", schema="qa")
    op.drop_table("document_extraction_runs", schema="qa")
    op.drop_index("ix_qa_document_text_segments_run_order", table_name="document_text_segments", schema="qa")
    for name in ("source_metadata", "heading_path", "column_index", "row_index", "block_type", "source_order", "extraction_run_id"):
        op.drop_column("document_text_segments", name, schema="qa")
    for name in ("extraction_lease_until", "extraction_worker_token", "current_chunk_run_id", "current_extraction_run_id", "parser_version", "parser_mode"):
        op.drop_column("document_files", name, schema="qa")
    op.drop_constraint("ck_qa_document_types_ai_source_policy", "document_types", schema="qa", type_="check")
    op.drop_column("document_types", "ai_source_policy", schema="qa")
