"""QA 模块的 ORM 数据模型。

QA 模块故意不声明业务外键或跨模块 relationship。主数据和文件是 QA
自己的稳定身份；生产、设备及飞书组织架构只通过逻辑 UUID/字符串引用，
由 service 层在写入时校验并保存快照。这样既保持 schema 隔离，也允许
来源模块后续演进而不破坏 QA 历史记录。
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class MasterObjectType(enum.StrEnum):
    """QA 自有主数据类型。"""

    PRODUCT = "PRODUCT"
    MATERIAL = "MATERIAL"
    EQUIPMENT = "EQUIPMENT"
    SUPPLIER = "SUPPLIER"
    REGION = "REGION"


class RecordStatus(enum.StrEnum):
    """可停用但不可物理删除的记录状态。"""

    ACTIVE = "active"
    INACTIVE = "inactive"


class VersionStatus(enum.StrEnum):
    """文件版本的系统计算状态。"""

    REGISTERED = "registered"
    CURRENT = "current"
    HISTORY = "history"
    INACTIVE = "inactive"


class ExtractionStatus(enum.StrEnum):
    """正文提取任务状态。"""

    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    TEXT_NOT_AVAILABLE = "text_not_available"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class RelationType(enum.StrEnum):
    """V1 统一关联类型；字段保留后续扩展空间。"""

    APPLIES_TO = "APPLIES_TO"


class MasterObject(BaseModel):
    """QA 自有质量主数据（产品、物料、设备、供应商、区域）。"""

    __tablename__ = "master_objects"
    __table_args__ = (
        CheckConstraint(
            "object_type IN ('PRODUCT', 'MATERIAL', 'EQUIPMENT', 'SUPPLIER', 'REGION')",
            name="ck_qa_master_objects_type",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_qa_master_objects_status",
        ),
        CheckConstraint(
            "object_type = 'REGION' OR region_parent_id IS NULL",
            name="ck_qa_master_objects_region_parent",
        ),
        # normalized_code 由 service 统一 trim + upper 后写入；保留原始
        # code 便于展示/迁移时追溯，并避免数据库依赖 locale 的 upper 行为。
        Index(
            "uq_qa_master_objects_type_code",
            "object_type",
            "normalized_code",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "ix_qa_master_objects_code",
            "normalized_code",
            postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "ix_qa_master_objects_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
        Index(
            "ix_qa_master_objects_description_trgm",
            "description",
            postgresql_using="gin",
            postgresql_ops={"description": "gin_trgm_ops"},
        ),
        Index("ix_qa_master_objects_region_parent", "region_parent_id"),
        Index(
            "ix_qa_master_objects_active",
            "status",
            postgresql_where=text("is_deleted = false AND status = 'active'"),
        ),
        {"schema": "qa"},
    )

    object_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="主数据类型"
    )
    code: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="QA 业务编码（展示值）"
    )
    normalized_code: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="规范化编码（trim + upper，供唯一性和检索）"
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="主数据名称")
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="主数据描述"
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=RecordStatus.ACTIVE.value,
        server_default=RecordStatus.ACTIVE.value,
        comment="active/inactive",
    )
    responsible_department_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="责任部门飞书 ID（逻辑引用）"
    )
    responsible_department_name_snapshot: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="责任部门名称快照"
    )
    region_parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, comment="区域父级 ID（仅 REGION 逻辑引用）"
    )
    contact_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="供应商联系人"
    )
    contact_phone: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="供应商联系电话"
    )
    contact_email: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="供应商联系邮箱"
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")


class MasterObjectAlias(BaseModel):
    """主数据别名；保留原始展示值和规范化检索值。"""

    __tablename__ = "master_object_aliases"
    __table_args__ = (
        CheckConstraint("length(btrim(alias)) > 0", name="ck_qa_master_object_aliases_alias"),
        CheckConstraint(
            "length(btrim(normalized_alias)) > 0",
            name="ck_qa_master_object_aliases_normalized",
        ),
        Index(
            "uq_qa_master_object_aliases_object_alias",
            "master_object_id",
            "normalized_alias",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_qa_master_object_aliases_object", "master_object_id"),
        Index(
            "ix_qa_master_object_aliases_alias_trgm",
            "alias",
            postgresql_using="gin",
            postgresql_ops={"alias": "gin_trgm_ops"},
        ),
        Index("ix_qa_master_object_aliases_normalized", "normalized_alias"),
        {"schema": "qa"},
    )

    master_object_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="QA 主数据 ID（逻辑引用）"
    )
    alias: Mapped[str] = mapped_column(String(255), nullable=False, comment="原始别名")
    normalized_alias: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="规范化别名（trim + upper）"
    )


class MasterObjectSource(BaseModel):
    """QA 主数据与其他模块对象的来源关联及快照。"""

    __tablename__ = "master_object_sources"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(source_module)) > 0",
            name="ck_qa_master_object_sources_module",
        ),
        CheckConstraint(
            "length(btrim(source_entity)) > 0",
            name="ck_qa_master_object_sources_entity",
        ),
        Index(
            "uq_qa_master_object_sources_identity",
            "master_object_id",
            "source_module",
            "source_entity",
            "source_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_qa_master_object_sources_object", "master_object_id"),
        Index(
            "ix_qa_master_object_sources_lookup",
            "source_module",
            "source_entity",
            "source_id",
        ),
        {"schema": "qa"},
    )

    master_object_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="QA 主数据 ID（逻辑引用）"
    )
    source_module: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="来源模块（如 production/equipment）"
    )
    source_entity: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="来源实体类型"
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="来源对象 ID（逻辑引用）"
    )
    source_code_snapshot: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="来源编码快照"
    )
    source_name_snapshot: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="来源名称快照"
    )


class DocumentType(BaseModel):
    """质量文件类型字典。类型编码不可变，记录通过 status 停用。"""

    __tablename__ = "document_types"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_qa_document_types_status",
        ),
        # code 由 service 规范化；表达式索引再次保护大小写不敏感唯一性。
        Index(
            "uq_qa_document_types_code",
            text("upper(code)"),
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "ix_qa_document_types_active",
            "status",
            postgresql_where=text("is_deleted = false AND status = 'active'"),
        ),
        {"schema": "qa"},
    )

    code: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="类型编码（不可变）"
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="类型名称")
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="类型说明"
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=RecordStatus.ACTIVE.value,
        server_default=RecordStatus.ACTIVE.value,
        comment="active/inactive",
    )


class Document(BaseModel):
    """文件台账；业务字段严格限定为编号、标题、类型和责任部门。"""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_qa_documents_status",
        ),
        CheckConstraint("length(btrim(document_no)) > 0", name="ck_qa_documents_no"),
        CheckConstraint("length(btrim(title)) > 0", name="ck_qa_documents_title"),
        Index(
            "uq_qa_documents_document_no",
            text("upper(document_no)"),
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "ix_qa_documents_no",
            "document_no",
            postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "ix_qa_documents_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index("ix_qa_documents_type", "document_type_id"),
        Index("ix_qa_documents_current_version", "current_version_id"),
        Index(
            "ix_qa_documents_active",
            "status",
            postgresql_where=text("is_deleted = false AND status = 'active'"),
        ),
        {"schema": "qa"},
    )

    document_no: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="文件编号（不可修改）"
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False, comment="文件标题")
    document_type_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="文件类型 ID（逻辑引用）"
    )
    responsible_department_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="责任部门飞书 ID（逻辑引用）"
    )
    responsible_department_name_snapshot: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="责任部门名称快照"
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=RecordStatus.ACTIVE.value,
        server_default=RecordStatus.ACTIVE.value,
        comment="active/inactive",
    )
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, comment="默认当前版本 ID（逻辑引用）"
    )


class DocumentVersion(BaseModel):
    """文件版本；原文件及版本标签在创建后不可覆盖。"""

    __tablename__ = "document_versions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('registered', 'current', 'history', 'inactive')",
            name="ck_qa_document_versions_status",
        ),
        CheckConstraint(
            "version_sequence > 0",
            name="ck_qa_document_versions_sequence",
        ),
        CheckConstraint(
            "length(btrim(version_label)) > 0",
            name="ck_qa_document_versions_label",
        ),
        Index(
            "uq_qa_document_versions_document_label",
            "document_id",
            text("lower(version_label)"),
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "uq_qa_document_versions_document_sequence",
            "document_id",
            "version_sequence",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "uq_qa_document_versions_current",
            "document_id",
            unique=True,
            postgresql_where=text("is_deleted = false AND status = 'current'"),
        ),
        Index("ix_qa_document_versions_document", "document_id"),
        Index("ix_qa_document_versions_status", "status"),
        {"schema": "qa"},
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="所属文件台账 ID（逻辑引用）"
    )
    version_label: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="人工版本标签（不可修改）"
    )
    version_sequence: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="系统递增版本序号"
    )
    approved_declared: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        server_default="false",
        comment="上传人声明已由外部正式流程批准（非本系统审批）",
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=VersionStatus.REGISTERED.value,
        server_default=VersionStatus.REGISTERED.value,
        comment="registered/current/history/inactive（系统计算）",
    )
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="本次版本首次锁定时间"
    )
    first_locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="首次锁定时间（不可回退）"
    )


class DocumentFile(BaseModel):
    """版本的主文件及正文提取状态。每个版本最多一个主文件。"""

    __tablename__ = "document_files"
    __table_args__ = (
        CheckConstraint(
            "lower(extension) IN ('pdf', 'docx', 'doc')",
            name="ck_qa_document_files_extension",
        ),
        CheckConstraint(
            "size_bytes >= 0 AND size_bytes <= 52428800",
            name="ck_qa_document_files_size",
        ),
        CheckConstraint(
            "extraction_status IN ('queued', 'processing', 'ready', 'text_not_available', 'unsupported', 'failed')",
            name="ck_qa_document_files_extraction_status",
        ),
        CheckConstraint("retry_count >= 0", name="ck_qa_document_files_retry_count"),
        Index(
            "uq_qa_document_files_version",
            "version_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "uq_qa_document_files_storage_key",
            "storage_key",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_qa_document_files_hash", "sha256"),
        Index(
            "ix_qa_document_files_extraction_queue",
            "extraction_status",
            "updated_at",
            postgresql_where=text(
                "is_deleted = false AND extraction_status IN ('queued', 'processing', 'failed')"
            ),
        ),
        {"schema": "qa"},
    )

    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="所属版本 ID（逻辑引用）"
    )
    storage_key: Mapped[str] = mapped_column(
        String(512), nullable=False, comment="系统生成的私有存储键"
    )
    original_filename: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="用户上传的原文件名"
    )
    extension: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="文件扩展名（pdf/docx/doc）"
    )
    mime_type: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="上传时校验的 MIME 类型"
    )
    size_bytes: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="文件大小（字节，最大 50 MiB）"
    )
    sha256: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="文件内容 SHA-256"
    )
    extraction_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ExtractionStatus.QUEUED.value,
        server_default=ExtractionStatus.QUEUED.value,
        comment="正文提取状态",
    )
    extraction_error: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="最近一次正文提取失败原因"
    )
    retry_count: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=0,
        server_default="0",
        comment="自动重试次数（最多三次）",
    )


class DocumentTextSegment(BaseModel):
    """可定位正文片段（PDF 页、DOCX 段落/表格单元）。"""

    __tablename__ = "document_text_segments"
    __table_args__ = (
        Index("ix_qa_document_text_segments_file_locator", "file_id", "locator"),
        Index(
            "ix_qa_document_text_segments_content_trgm",
            "content",
            postgresql_using="gin",
            postgresql_ops={"content": "gin_trgm_ops"},
        ),
        Index("ix_qa_document_text_segments_hash", "text_hash"),
        Index(
            "ix_qa_document_text_segments_pdf_position",
            "file_id",
            "page_number",
            "paragraph_index",
        ),
        {"schema": "qa"},
    )

    file_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="所属文件 ID（逻辑引用）"
    )
    locator: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="可读定位符（如 page:3/paragraph:12）"
    )
    page_number: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="PDF 页码（从 1 开始）"
    )
    paragraph_index: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="DOCX 段落序号（从 0 开始）"
    )
    table_index: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="DOCX 表格序号（从 0 开始）"
    )
    cell_index: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="DOCX 表格单元序号（从 0 开始）"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="正文片段")
    text_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="正文片段 SHA-256"
    )


class DocumentMasterLink(BaseModel):
    """文件版本与 QA 主数据的版本级关联及名称快照。"""

    __tablename__ = "document_master_links"
    __table_args__ = (
        CheckConstraint(
            "relation_type = 'APPLIES_TO'",
            name="ck_qa_document_master_links_relation_type",
        ),
        Index(
            "uq_qa_document_master_links_identity",
            "version_id",
            "master_object_id",
            "relation_type",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_qa_document_master_links_version", "version_id"),
        Index("ix_qa_document_master_links_master", "master_object_id"),
        {"schema": "qa"},
    )

    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="文件版本 ID（逻辑引用）"
    )
    master_object_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, comment="QA 主数据 ID（逻辑引用）"
    )
    relation_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=RelationType.APPLIES_TO.value,
        server_default=RelationType.APPLIES_TO.value,
        comment="V1 固定 APPLIES_TO（界面显示适用/关联）",
    )
    code_snapshot: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="关联时主数据编码快照"
    )
    name_snapshot: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="关联时主数据名称快照"
    )


# 早期 service/repository 代码常使用简短的 TextSegment 名称；保留别名
# 不会创建额外表，便于模块内部渐进迁移。
TextSegment = DocumentTextSegment


__all__ = [
    "Document",
    "DocumentFile",
    "DocumentMasterLink",
    "DocumentTextSegment",
    "DocumentType",
    "DocumentVersion",
    "ExtractionStatus",
    "MasterObject",
    "MasterObjectAlias",
    "MasterObjectSource",
    "MasterObjectType",
    "RecordStatus",
    "RelationType",
    "TextSegment",
    "VersionStatus",
]
