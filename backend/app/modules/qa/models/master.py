"""QA 主数据模型：产品/物料/设备/供应商/区域及别名与来源关联。"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import (
    CheckConstraint,
    Index,
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
        String(128),
        nullable=False,
        comment="规范化编码（trim + upper，供唯一性和检索）",
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
        CheckConstraint(
            "length(btrim(alias)) > 0", name="ck_qa_master_object_aliases_alias"
        ),
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
