"""add QA knowledge hub tables.

This migration creates the isolated ``qa`` schema.  References to production,
equipment, identity departments and other QA rows intentionally remain logical
references (there are no business foreign-key constraints).

Revision ID: 1b19dee8bb0f
Revises: aae52f0e112e
Create Date: 2026-09-14 13:40:52.171860
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.schema import SchemaItem

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1b19dee8bb0f"
down_revision: str | None = "aae52f0e112e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base_columns() -> list[SchemaItem]:
    """Return the common :class:`BaseModel` columns for a QA table.

    A helper keeps all nine tables aligned with ``app.shared.base_model`` while
    still leaving the migration self-contained and safe to run without loading
    application models.
    """

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
        sa.ForeignKeyConstraint(["created_by"], ["identity.users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["identity.users.id"]),
        sa.PrimaryKeyConstraint("id"),
    ]


def upgrade() -> None:
    # Alembic autogenerate does not create schemas.  pg_trgm is shared at the
    # database level and is safe to leave installed on downgrade.
    op.execute("CREATE SCHEMA IF NOT EXISTS qa")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "master_objects",
        sa.Column("object_type", sa.String(32), nullable=False, comment="主数据类型"),
        sa.Column("code", sa.String(128), nullable=False, comment="QA 业务编码（展示值）"),
        sa.Column(
            "normalized_code",
            sa.String(128),
            nullable=False,
            comment="规范化编码（trim + upper，供唯一性和检索）",
        ),
        sa.Column("name", sa.String(255), nullable=False, comment="主数据名称"),
        sa.Column("description", sa.Text(), nullable=True, comment="主数据描述"),
        sa.Column(
            "status",
            sa.String(16),
            server_default="active",
            nullable=False,
            comment="active/inactive",
        ),
        sa.Column(
            "responsible_department_id",
            sa.String(128),
            nullable=True,
            comment="责任部门飞书 ID（逻辑引用）",
        ),
        sa.Column(
            "responsible_department_name_snapshot",
            sa.String(255),
            nullable=True,
            comment="责任部门名称快照",
        ),
        sa.Column(
            "region_parent_id",
            sa.Uuid(),
            nullable=True,
            comment="区域父级 ID（仅 REGION 逻辑引用）",
        ),
        sa.Column("contact_name", sa.String(255), nullable=True, comment="供应商联系人"),
        sa.Column("contact_phone", sa.String(64), nullable=True, comment="供应商联系电话"),
        sa.Column("contact_email", sa.String(255), nullable=True, comment="供应商联系邮箱"),
        sa.Column("remark", sa.Text(), nullable=True, comment="备注"),
        *_base_columns(),
        sa.CheckConstraint(
            "object_type IN ('PRODUCT', 'MATERIAL', 'EQUIPMENT', 'SUPPLIER', 'REGION')",
            name="ck_qa_master_objects_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_qa_master_objects_status",
        ),
        sa.CheckConstraint(
            "object_type = 'REGION' OR region_parent_id IS NULL",
            name="ck_qa_master_objects_region_parent",
        ),
        schema="qa",
    )
    op.create_index(
        "uq_qa_master_objects_type_code",
        "master_objects",
        ["object_type", "normalized_code"],
        unique=True,
        schema="qa",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_qa_master_objects_code",
        "master_objects",
        ["normalized_code"],
        schema="qa",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_qa_master_objects_name_trgm",
        "master_objects",
        ["name"],
        schema="qa",
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_qa_master_objects_description_trgm",
        "master_objects",
        ["description"],
        schema="qa",
        postgresql_using="gin",
        postgresql_ops={"description": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_qa_master_objects_region_parent",
        "master_objects",
        ["region_parent_id"],
        schema="qa",
    )
    op.create_index(
        "ix_qa_master_objects_active",
        "master_objects",
        ["status"],
        schema="qa",
        postgresql_where=sa.text("is_deleted = false AND status = 'active'"),
    )

    op.create_table(
        "master_object_aliases",
        sa.Column(
            "master_object_id",
            sa.Uuid(),
            nullable=False,
            comment="QA 主数据 ID（逻辑引用）",
        ),
        sa.Column("alias", sa.String(255), nullable=False, comment="原始别名"),
        sa.Column(
            "normalized_alias",
            sa.String(255),
            nullable=False,
            comment="规范化别名（trim + upper）",
        ),
        *_base_columns(),
        sa.CheckConstraint(
            "length(btrim(alias)) > 0",
            name="ck_qa_master_object_aliases_alias",
        ),
        sa.CheckConstraint(
            "length(btrim(normalized_alias)) > 0",
            name="ck_qa_master_object_aliases_normalized",
        ),
        schema="qa",
    )
    op.create_index(
        "uq_qa_master_object_aliases_object_alias",
        "master_object_aliases",
        ["master_object_id", "normalized_alias"],
        unique=True,
        schema="qa",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_qa_master_object_aliases_object",
        "master_object_aliases",
        ["master_object_id"],
        schema="qa",
    )
    op.create_index(
        "ix_qa_master_object_aliases_alias_trgm",
        "master_object_aliases",
        ["alias"],
        schema="qa",
        postgresql_using="gin",
        postgresql_ops={"alias": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_qa_master_object_aliases_normalized",
        "master_object_aliases",
        ["normalized_alias"],
        schema="qa",
    )

    op.create_table(
        "master_object_sources",
        sa.Column(
            "master_object_id",
            sa.Uuid(),
            nullable=False,
            comment="QA 主数据 ID（逻辑引用）",
        ),
        sa.Column(
            "source_module",
            sa.String(64),
            nullable=False,
            comment="来源模块（如 production/equipment）",
        ),
        sa.Column("source_entity", sa.String(128), nullable=False, comment="来源实体类型"),
        sa.Column(
            "source_id",
            sa.Uuid(),
            nullable=False,
            comment="来源对象 ID（逻辑引用）",
        ),
        sa.Column("source_code_snapshot", sa.String(128), nullable=True, comment="来源编码快照"),
        sa.Column("source_name_snapshot", sa.String(255), nullable=True, comment="来源名称快照"),
        *_base_columns(),
        sa.CheckConstraint(
            "length(btrim(source_module)) > 0",
            name="ck_qa_master_object_sources_module",
        ),
        sa.CheckConstraint(
            "length(btrim(source_entity)) > 0",
            name="ck_qa_master_object_sources_entity",
        ),
        schema="qa",
    )
    op.create_index(
        "uq_qa_master_object_sources_identity",
        "master_object_sources",
        ["master_object_id", "source_module", "source_entity", "source_id"],
        unique=True,
        schema="qa",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_qa_master_object_sources_object",
        "master_object_sources",
        ["master_object_id"],
        schema="qa",
    )
    op.create_index(
        "ix_qa_master_object_sources_lookup",
        "master_object_sources",
        ["source_module", "source_entity", "source_id"],
        schema="qa",
    )

    op.create_table(
        "document_types",
        sa.Column("code", sa.String(64), nullable=False, comment="类型编码（不可变）"),
        sa.Column("name", sa.String(128), nullable=False, comment="类型名称"),
        sa.Column("description", sa.Text(), nullable=True, comment="类型说明"),
        sa.Column(
            "status",
            sa.String(16),
            server_default="active",
            nullable=False,
            comment="active/inactive",
        ),
        *_base_columns(),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_qa_document_types_status",
        ),
        schema="qa",
    )
    # Expression index enforces case-insensitive uniqueness even if a caller
    # bypasses the service-level normalization.
    op.execute(
        "CREATE UNIQUE INDEX uq_qa_document_types_code "
        "ON qa.document_types (upper(code)) WHERE is_deleted = false"
    )
    op.create_index(
        "ix_qa_document_types_active",
        "document_types",
        ["status"],
        schema="qa",
        postgresql_where=sa.text("is_deleted = false AND status = 'active'"),
    )

    op.create_table(
        "documents",
        sa.Column(
            "document_no",
            sa.String(128),
            nullable=False,
            comment="文件编号（不可修改）",
        ),
        sa.Column("title", sa.String(500), nullable=False, comment="文件标题"),
        sa.Column(
            "document_type_id",
            sa.Uuid(),
            nullable=False,
            comment="文件类型 ID（逻辑引用）",
        ),
        sa.Column(
            "responsible_department_id",
            sa.String(128),
            nullable=True,
            comment="责任部门飞书 ID（逻辑引用）",
        ),
        sa.Column(
            "responsible_department_name_snapshot",
            sa.String(255),
            nullable=True,
            comment="责任部门名称快照",
        ),
        sa.Column(
            "status",
            sa.String(16),
            server_default="active",
            nullable=False,
            comment="active/inactive",
        ),
        sa.Column(
            "current_version_id",
            sa.Uuid(),
            nullable=True,
            comment="默认当前版本 ID（逻辑引用）",
        ),
        *_base_columns(),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_qa_documents_status",
        ),
        sa.CheckConstraint(
            "length(btrim(document_no)) > 0",
            name="ck_qa_documents_no",
        ),
        sa.CheckConstraint(
            "length(btrim(title)) > 0",
            name="ck_qa_documents_title",
        ),
        schema="qa",
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_qa_documents_document_no "
        "ON qa.documents (upper(document_no)) WHERE is_deleted = false"
    )
    op.create_index(
        "ix_qa_documents_no",
        "documents",
        ["document_no"],
        schema="qa",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_qa_documents_title_trgm",
        "documents",
        ["title"],
        schema="qa",
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )
    op.create_index("ix_qa_documents_type", "documents", ["document_type_id"], schema="qa")
    op.create_index(
        "ix_qa_documents_current_version",
        "documents",
        ["current_version_id"],
        schema="qa",
    )
    op.create_index(
        "ix_qa_documents_active",
        "documents",
        ["status"],
        schema="qa",
        postgresql_where=sa.text("is_deleted = false AND status = 'active'"),
    )

    op.create_table(
        "document_versions",
        sa.Column(
            "document_id",
            sa.Uuid(),
            nullable=False,
            comment="所属文件台账 ID（逻辑引用）",
        ),
        sa.Column(
            "version_label",
            sa.String(64),
            nullable=False,
            comment="人工版本标签（不可修改）",
        ),
        sa.Column(
            "version_sequence",
            sa.Integer(),
            nullable=False,
            comment="系统递增版本序号",
        ),
        sa.Column(
            "approved_declared",
            sa.Boolean(),
            server_default="false",
            nullable=False,
            comment="上传人声明已由外部正式流程批准（非本系统审批）",
        ),
        sa.Column(
            "status",
            sa.String(16),
            server_default="registered",
            nullable=False,
            comment="registered/current/history/inactive（系统计算）",
        ),
        sa.Column(
            "locked_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="本次版本首次锁定时间",
        ),
        sa.Column(
            "first_locked_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="首次锁定时间（不可回退）",
        ),
        *_base_columns(),
        sa.CheckConstraint(
            "status IN ('registered', 'current', 'history', 'inactive')",
            name="ck_qa_document_versions_status",
        ),
        sa.CheckConstraint(
            "version_sequence > 0",
            name="ck_qa_document_versions_sequence",
        ),
        sa.CheckConstraint(
            "length(btrim(version_label)) > 0",
            name="ck_qa_document_versions_label",
        ),
        schema="qa",
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_qa_document_versions_document_label "
        "ON qa.document_versions (document_id, lower(version_label)) "
        "WHERE is_deleted = false"
    )
    op.create_index(
        "uq_qa_document_versions_document_sequence",
        "document_versions",
        ["document_id", "version_sequence"],
        unique=True,
        schema="qa",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "uq_qa_document_versions_current",
        "document_versions",
        ["document_id"],
        unique=True,
        schema="qa",
        postgresql_where=sa.text("is_deleted = false AND status = 'current'"),
    )
    op.create_index(
        "ix_qa_document_versions_document",
        "document_versions",
        ["document_id"],
        schema="qa",
    )
    op.create_index(
        "ix_qa_document_versions_status",
        "document_versions",
        ["status"],
        schema="qa",
    )

    op.create_table(
        "document_files",
        sa.Column(
            "version_id",
            sa.Uuid(),
            nullable=False,
            comment="所属版本 ID（逻辑引用）",
        ),
        sa.Column("storage_key", sa.String(512), nullable=False, comment="系统生成的私有存储键"),
        sa.Column("original_filename", sa.String(255), nullable=False, comment="用户上传的原文件名"),
        sa.Column(
            "extension",
            sa.String(16),
            nullable=False,
            comment="文件扩展名（pdf/docx/doc）",
        ),
        sa.Column("mime_type", sa.String(128), nullable=False, comment="上传时校验的 MIME 类型"),
        sa.Column(
            "size_bytes",
            sa.Integer(),
            nullable=False,
            comment="文件大小（字节，最大 50 MiB）",
        ),
        sa.Column("sha256", sa.String(64), nullable=False, comment="文件内容 SHA-256"),
        sa.Column(
            "extraction_status",
            sa.String(32),
            server_default="queued",
            nullable=False,
            comment="正文提取状态",
        ),
        sa.Column("extraction_error", sa.Text(), nullable=True, comment="最近一次正文提取失败原因"),
        sa.Column(
            "retry_count",
            sa.SmallInteger(),
            server_default="0",
            nullable=False,
            comment="自动重试次数（最多三次）",
        ),
        *_base_columns(),
        sa.CheckConstraint(
            "lower(extension) IN ('pdf', 'docx', 'doc')",
            name="ck_qa_document_files_extension",
        ),
        sa.CheckConstraint(
            "size_bytes >= 0 AND size_bytes <= 52428800",
            name="ck_qa_document_files_size",
        ),
        sa.CheckConstraint(
            "extraction_status IN ('queued', 'processing', 'ready', 'text_not_available', 'unsupported', 'failed')",
            name="ck_qa_document_files_extraction_status",
        ),
        sa.CheckConstraint("retry_count >= 0", name="ck_qa_document_files_retry_count"),
        schema="qa",
    )
    op.create_index(
        "uq_qa_document_files_version",
        "document_files",
        ["version_id"],
        unique=True,
        schema="qa",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "uq_qa_document_files_storage_key",
        "document_files",
        ["storage_key"],
        unique=True,
        schema="qa",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index("ix_qa_document_files_hash", "document_files", ["sha256"], schema="qa")
    op.create_index(
        "ix_qa_document_files_extraction_queue",
        "document_files",
        ["extraction_status", "updated_at"],
        schema="qa",
        postgresql_where=sa.text(
            "is_deleted = false AND extraction_status IN ('queued', 'processing', 'failed')"
        ),
    )

    op.create_table(
        "document_text_segments",
        sa.Column("file_id", sa.Uuid(), nullable=False, comment="所属文件 ID（逻辑引用）"),
        sa.Column(
            "locator",
            sa.String(255),
            nullable=False,
            comment="可读定位符（如 page:3/paragraph:12）",
        ),
        sa.Column("page_number", sa.Integer(), nullable=True, comment="PDF 页码（从 1 开始）"),
        sa.Column("paragraph_index", sa.Integer(), nullable=True, comment="DOCX 段落序号（从 0 开始）"),
        sa.Column("table_index", sa.Integer(), nullable=True, comment="DOCX 表格序号（从 0 开始）"),
        sa.Column("cell_index", sa.Integer(), nullable=True, comment="DOCX 表格单元序号（从 0 开始）"),
        sa.Column("content", sa.Text(), nullable=False, comment="正文片段"),
        sa.Column("text_hash", sa.String(64), nullable=False, comment="正文片段 SHA-256"),
        *_base_columns(),
        schema="qa",
    )
    op.create_index(
        "ix_qa_document_text_segments_file_locator",
        "document_text_segments",
        ["file_id", "locator"],
        schema="qa",
    )
    op.create_index(
        "ix_qa_document_text_segments_content_trgm",
        "document_text_segments",
        ["content"],
        schema="qa",
        postgresql_using="gin",
        postgresql_ops={"content": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_qa_document_text_segments_hash",
        "document_text_segments",
        ["text_hash"],
        schema="qa",
    )
    op.create_index(
        "ix_qa_document_text_segments_pdf_position",
        "document_text_segments",
        ["file_id", "page_number", "paragraph_index"],
        schema="qa",
    )

    op.create_table(
        "document_master_links",
        sa.Column("version_id", sa.Uuid(), nullable=False, comment="文件版本 ID（逻辑引用）"),
        sa.Column(
            "master_object_id",
            sa.Uuid(),
            nullable=False,
            comment="QA 主数据 ID（逻辑引用）",
        ),
        sa.Column(
            "relation_type",
            sa.String(32),
            server_default="APPLIES_TO",
            nullable=False,
            comment="V1 固定 APPLIES_TO（界面显示适用/关联）",
        ),
        sa.Column("code_snapshot", sa.String(128), nullable=False, comment="关联时主数据编码快照"),
        sa.Column("name_snapshot", sa.String(255), nullable=False, comment="关联时主数据名称快照"),
        *_base_columns(),
        sa.CheckConstraint(
            "relation_type = 'APPLIES_TO'",
            name="ck_qa_document_master_links_relation_type",
        ),
        schema="qa",
    )
    op.create_index(
        "uq_qa_document_master_links_identity",
        "document_master_links",
        ["version_id", "master_object_id", "relation_type"],
        unique=True,
        schema="qa",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "ix_qa_document_master_links_version",
        "document_master_links",
        ["version_id"],
        schema="qa",
    )
    op.create_index(
        "ix_qa_document_master_links_master",
        "document_master_links",
        ["master_object_id"],
        schema="qa",
    )

    # Seed the administrator-maintainable dictionary with common quality
    # document types. UUIDs are generated by this migration (not by a shared
    # database function), so the seed works on installations without pgcrypto.
    document_types = sa.table(
        "document_types",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.String(64)),
        sa.column("name", sa.String(128)),
        sa.column("description", sa.Text()),
        sa.column("status", sa.String(16)),
        sa.column("is_deleted", sa.Boolean()),
        schema="qa",
    )
    op.bulk_insert(
        document_types,
        [
            {"id": uuid.uuid4(), "code": "SOP", "name": "SOP", "status": "active", "is_deleted": False, "description": None},
            {"id": uuid.uuid4(), "code": "WI", "name": "工作指导书（WI）", "status": "active", "is_deleted": False, "description": None},
            {"id": uuid.uuid4(), "code": "SPECIFICATION", "name": "质量标准（Specification）", "status": "active", "is_deleted": False, "description": None},
            {"id": uuid.uuid4(), "code": "FORM", "name": "记录表单（Form）", "status": "active", "is_deleted": False, "description": None},
            {"id": uuid.uuid4(), "code": "VALIDATION_PROTOCOL", "name": "验证方案（Validation Protocol）", "status": "active", "is_deleted": False, "description": None},
            {"id": uuid.uuid4(), "code": "VALIDATION_REPORT", "name": "验证报告（Validation Report）", "status": "active", "is_deleted": False, "description": None},
            {"id": uuid.uuid4(), "code": "POLICY", "name": "质量政策（Policy）", "status": "active", "is_deleted": False, "description": None},
            {"id": uuid.uuid4(), "code": "QUALITY_AGREEMENT", "name": "质量协议（Quality Agreement）", "status": "active", "is_deleted": False, "description": None},
            {"id": uuid.uuid4(), "code": "AUDIT_REPORT", "name": "审计报告（Audit Report）", "status": "active", "is_deleted": False, "description": None},
            {"id": uuid.uuid4(), "code": "OTHER", "name": "其他（Other）", "status": "active", "is_deleted": False, "description": None},
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_qa_document_master_links_master",
        table_name="document_master_links",
        schema="qa",
    )
    op.drop_index(
        "ix_qa_document_master_links_version",
        table_name="document_master_links",
        schema="qa",
    )
    op.drop_index(
        "uq_qa_document_master_links_identity",
        table_name="document_master_links",
        schema="qa",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_table("document_master_links", schema="qa")

    op.drop_index(
        "ix_qa_document_text_segments_pdf_position",
        table_name="document_text_segments",
        schema="qa",
    )
    op.drop_index(
        "ix_qa_document_text_segments_hash",
        table_name="document_text_segments",
        schema="qa",
    )
    op.drop_index(
        "ix_qa_document_text_segments_content_trgm",
        table_name="document_text_segments",
        schema="qa",
    )
    op.drop_index(
        "ix_qa_document_text_segments_file_locator",
        table_name="document_text_segments",
        schema="qa",
    )
    op.drop_table("document_text_segments", schema="qa")

    op.drop_index(
        "ix_qa_document_files_extraction_queue",
        table_name="document_files",
        schema="qa",
    )
    op.drop_index("ix_qa_document_files_hash", table_name="document_files", schema="qa")
    op.drop_index(
        "uq_qa_document_files_storage_key",
        table_name="document_files",
        schema="qa",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_index(
        "uq_qa_document_files_version",
        table_name="document_files",
        schema="qa",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_table("document_files", schema="qa")

    op.drop_index(
        "ix_qa_document_versions_status",
        table_name="document_versions",
        schema="qa",
    )
    op.drop_index(
        "ix_qa_document_versions_document",
        table_name="document_versions",
        schema="qa",
    )
    op.drop_index(
        "uq_qa_document_versions_current",
        table_name="document_versions",
        schema="qa",
        postgresql_where=sa.text("is_deleted = false AND status = 'current'"),
    )
    op.drop_index(
        "uq_qa_document_versions_document_sequence",
        table_name="document_versions",
        schema="qa",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.execute("DROP INDEX IF EXISTS qa.uq_qa_document_versions_document_label")
    op.drop_table("document_versions", schema="qa")

    op.drop_index("ix_qa_documents_active", table_name="documents", schema="qa")
    op.drop_index(
        "ix_qa_documents_current_version",
        table_name="documents",
        schema="qa",
    )
    op.drop_index("ix_qa_documents_type", table_name="documents", schema="qa")
    op.drop_index("ix_qa_documents_title_trgm", table_name="documents", schema="qa")
    op.drop_index(
        "ix_qa_documents_no",
        table_name="documents",
        schema="qa",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.execute("DROP INDEX IF EXISTS qa.uq_qa_documents_document_no")
    op.drop_table("documents", schema="qa")

    op.drop_index("ix_qa_document_types_active", table_name="document_types", schema="qa")
    op.execute("DROP INDEX IF EXISTS qa.uq_qa_document_types_code")
    op.drop_table("document_types", schema="qa")

    op.drop_index(
        "ix_qa_master_object_sources_lookup",
        table_name="master_object_sources",
        schema="qa",
    )
    op.drop_index(
        "ix_qa_master_object_sources_object",
        table_name="master_object_sources",
        schema="qa",
    )
    op.drop_index(
        "uq_qa_master_object_sources_identity",
        table_name="master_object_sources",
        schema="qa",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_table("master_object_sources", schema="qa")

    op.drop_index(
        "ix_qa_master_object_aliases_normalized",
        table_name="master_object_aliases",
        schema="qa",
    )
    op.drop_index(
        "ix_qa_master_object_aliases_alias_trgm",
        table_name="master_object_aliases",
        schema="qa",
    )
    op.drop_index(
        "ix_qa_master_object_aliases_object",
        table_name="master_object_aliases",
        schema="qa",
    )
    op.drop_index(
        "uq_qa_master_object_aliases_object_alias",
        table_name="master_object_aliases",
        schema="qa",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_table("master_object_aliases", schema="qa")

    op.drop_index(
        "ix_qa_master_objects_active",
        table_name="master_objects",
        schema="qa",
    )
    op.drop_index(
        "ix_qa_master_objects_region_parent",
        table_name="master_objects",
        schema="qa",
    )
    op.drop_index(
        "ix_qa_master_objects_description_trgm",
        table_name="master_objects",
        schema="qa",
    )
    op.drop_index(
        "ix_qa_master_objects_name_trgm",
        table_name="master_objects",
        schema="qa",
    )
    op.drop_index(
        "ix_qa_master_objects_code",
        table_name="master_objects",
        schema="qa",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_index(
        "uq_qa_master_objects_type_code",
        table_name="master_objects",
        schema="qa",
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.drop_table("master_objects", schema="qa")
    op.execute("DROP SCHEMA IF EXISTS qa")
