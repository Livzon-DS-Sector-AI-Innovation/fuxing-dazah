"""QA 文件台账模型：文件类型、文件、不可变版本、物理文件与主数据关联。"""

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

from app.modules.qa.models.master import RecordStatus
from app.shared.base_model import BaseModel


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


class AIAuthorityPolicy(enum.StrEnum):
    """文件类型允许 AI 产生的事实范围。"""

    AUTHORITATIVE = "authoritative"
    REFERENCE = "reference"
    DISABLED = "disabled"


class RelationType(enum.StrEnum):
    """V1 统一关联类型；字段保留后续扩展空间。"""

    APPLIES_TO = "APPLIES_TO"


class DocumentType(BaseModel):
    """质量文件类型字典。类型编码不可变，记录通过 status 停用。"""

    __tablename__ = "document_types"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_qa_document_types_status",
        ),
        CheckConstraint(
            "ai_source_policy IN ('authoritative', 'reference', 'disabled')",
            name="ck_qa_document_types_ai_source_policy",
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
    ai_source_policy: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=AIAuthorityPolicy.AUTHORITATIVE.value,
        server_default=AIAuthorityPolicy.AUTHORITATIVE.value,
        comment="AI 来源策略：authoritative/reference/disabled",
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
    parser_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="native_text",
        server_default="native_text",
        comment="解析模式；本期 native_text，预留 ocr",
    )
    parser_version: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="最近成功解析器版本；旧数据为空表示 legacy"
    )
    current_extraction_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, comment="当前有效解析运行 ID（逻辑引用）"
    )
    current_chunk_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, comment="当前有效分块运行 ID（逻辑引用）"
    )
    extraction_worker_token: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="解析任务租约 token"
    )
    extraction_lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="解析任务租约到期时间"
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
