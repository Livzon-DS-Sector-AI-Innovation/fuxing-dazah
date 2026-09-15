"""QA 模块数据访问层。

本文件只负责 SQL 查询和持久化；状态、跨模块校验及审计由 service 编排。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.modules.qa.models import (
    Document,
    DocumentFile,
    DocumentMasterLink,
    DocumentTextSegment,
    DocumentType,
    DocumentVersion,
    MasterObject,
    MasterObjectAlias,
    MasterObjectSource,
)
from app.shared.sql import escape_like


async def get_master(db: AsyncSession, object_id: uuid.UUID) -> MasterObject | None:
    result = await db.execute(
        select(MasterObject).where(
            MasterObject.id == object_id,
            MasterObject.is_deleted.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def list_masters(
    db: AsyncSession,
    *,
    object_type: str | None = None,
    keyword: str | None = None,
    status: str | None = None,
    include_deleted: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[MasterObject], int]:
    conditions: list[ColumnElement[bool]] = []
    if not include_deleted:
        conditions.append(MasterObject.is_deleted.is_(False))
    if object_type:
        conditions.append(MasterObject.object_type == object_type)
    if status:
        conditions.append(MasterObject.status == status)
    if keyword:
        # 用户输入的 % / _ 是字面量；不转义时 keyword="%" 会命中全表。
        term = f"%{escape_like(keyword.strip())}%"
        conditions.append(
            or_(
                MasterObject.code.ilike(term, escape="\\"),
                MasterObject.name.ilike(term, escape="\\"),
                MasterObject.normalized_code.ilike(term, escape="\\"),
                MasterObject.id.in_(
                    select(MasterObjectAlias.master_object_id).where(
                        MasterObjectAlias.normalized_alias.ilike(term, escape="\\"),
                        MasterObjectAlias.is_deleted.is_(False),
                    )
                ),
            )
        )
    base = select(MasterObject).where(*conditions)
    total = int(
        (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    )
    result = await db.execute(
        base.order_by(MasterObject.object_type, MasterObject.code)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars()), total


async def get_aliases(db: AsyncSession, object_id: uuid.UUID) -> list[MasterObjectAlias]:
    result = await db.execute(
        select(MasterObjectAlias)
        .where(
            MasterObjectAlias.master_object_id == object_id,
            MasterObjectAlias.is_deleted.is_(False),
        )
        .order_by(MasterObjectAlias.alias)
    )
    return list(result.scalars())


async def get_sources(db: AsyncSession, object_id: uuid.UUID) -> list[MasterObjectSource]:
    result = await db.execute(
        select(MasterObjectSource)
        .where(
            MasterObjectSource.master_object_id == object_id,
            MasterObjectSource.is_deleted.is_(False),
        )
        .order_by(MasterObjectSource.source_module, MasterObjectSource.source_entity)
    )
    return list(result.scalars())


async def get_aliases_for_masters(
    db: AsyncSession, object_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[MasterObjectAlias]]:
    """批量取别名，供列表页一次查完（逐行查会变成 N+1）。"""
    if not object_ids:
        return {}
    result = await db.execute(
        select(MasterObjectAlias)
        .where(
            MasterObjectAlias.master_object_id.in_(object_ids),
            MasterObjectAlias.is_deleted.is_(False),
        )
        .order_by(MasterObjectAlias.alias)
    )
    grouped: dict[uuid.UUID, list[MasterObjectAlias]] = {}
    for row in result.scalars():
        grouped.setdefault(row.master_object_id, []).append(row)
    return grouped


async def get_sources_for_masters(
    db: AsyncSession, object_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[MasterObjectSource]]:
    """批量取外部来源，供列表页一次查完（逐行查会变成 N+1）。"""
    if not object_ids:
        return {}
    result = await db.execute(
        select(MasterObjectSource)
        .where(
            MasterObjectSource.master_object_id.in_(object_ids),
            MasterObjectSource.is_deleted.is_(False),
        )
        .order_by(MasterObjectSource.source_module, MasterObjectSource.source_entity)
    )
    grouped: dict[uuid.UUID, list[MasterObjectSource]] = {}
    for row in result.scalars():
        grouped.setdefault(row.master_object_id, []).append(row)
    return grouped


async def get_document_type(db: AsyncSession, type_id: uuid.UUID) -> DocumentType | None:
    result = await db.execute(
        select(DocumentType).where(
            DocumentType.id == type_id,
            DocumentType.is_deleted.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def list_document_types(
    db: AsyncSession, *, include_inactive: bool = False
) -> list[DocumentType]:
    stmt = select(DocumentType).where(DocumentType.is_deleted.is_(False))
    if not include_inactive:
        stmt = stmt.where(DocumentType.status == "active")
    result = await db.execute(stmt.order_by(DocumentType.code))
    return list(result.scalars())


async def get_document(db: AsyncSession, document_id: uuid.UUID) -> Document | None:
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.is_deleted.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def list_documents(
    db: AsyncSession,
    *,
    keyword: str | None = None,
    document_type_id: uuid.UUID | None = None,
    responsible_department_id: str | None = None,
    status: str | None = None,
    include_inactive: bool = False,
    has_current_version: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Document], int]:
    conditions: list[ColumnElement[bool]] = [Document.is_deleted.is_(False)]
    if not include_inactive:
        conditions.append(Document.status == "active")
    if document_type_id:
        conditions.append(Document.document_type_id == document_type_id)
    if responsible_department_id:
        conditions.append(Document.responsible_department_id == responsible_department_id)
    if status:
        conditions.append(Document.status == status)
    if has_current_version is not None:
        # 首页「已设当前版本」统计用：拿 total 即可，不必逐页拉台账。
        conditions.append(
            Document.current_version_id.is_not(None)
            if has_current_version
            else Document.current_version_id.is_(None)
        )
    if keyword:
        # 用户输入的 % / _ 是字面量；不转义时 keyword="%" 会命中全表。
        term = f"%{escape_like(keyword.strip())}%"
        conditions.append(
            or_(
                Document.document_no.ilike(term, escape="\\"),
                Document.title.ilike(term, escape="\\"),
                Document.id.in_(
                    select(DocumentVersion.document_id).where(
                        DocumentVersion.id.in_(
                            select(DocumentFile.version_id).where(
                                DocumentFile.id.in_(
                                    select(DocumentTextSegment.file_id).where(
                                        DocumentTextSegment.content.ilike(
                                            term, escape="\\"
                                        ),
                                        DocumentTextSegment.is_deleted.is_(False),
                                    )
                                ),
                                DocumentFile.is_deleted.is_(False),
                            )
                        ),
                        DocumentVersion.is_deleted.is_(False),
                    )
                ),
                Document.id.in_(
                    select(DocumentVersion.document_id).where(
                        DocumentVersion.id.in_(
                            select(DocumentMasterLink.version_id).where(
                                DocumentMasterLink.master_object_id.in_(
                                    select(MasterObject.id).where(
                                        or_(
                                            MasterObject.code.ilike(term, escape="\\"),
                                            MasterObject.name.ilike(term, escape="\\"),
                                        ),
                                        MasterObject.is_deleted.is_(False),
                                    )
                                ),
                                DocumentMasterLink.is_deleted.is_(False),
                            )
                        ),
                        DocumentVersion.is_deleted.is_(False),
                    )
                ),
            )
        )
    base = select(Document).where(*conditions)
    total = int(
        (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    )
    result = await db.execute(
        base.order_by(Document.document_no).offset((page - 1) * page_size).limit(page_size)
    )
    return list(result.scalars()), total


async def get_versions(db: AsyncSession, document_id: uuid.UUID) -> list[DocumentVersion]:
    result = await db.execute(
        select(DocumentVersion)
        .where(
            DocumentVersion.document_id == document_id,
            DocumentVersion.is_deleted.is_(False),
        )
        .order_by(DocumentVersion.version_sequence.desc())
    )
    return list(result.scalars())


async def get_version(db: AsyncSession, version_id: uuid.UUID) -> DocumentVersion | None:
    result = await db.execute(
        select(DocumentVersion).where(
            DocumentVersion.id == version_id,
            DocumentVersion.is_deleted.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def get_file_for_version(
    db: AsyncSession, version_id: uuid.UUID
) -> DocumentFile | None:
    result = await db.execute(
        select(DocumentFile).where(
            DocumentFile.version_id == version_id,
            DocumentFile.is_deleted.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def get_file(db: AsyncSession, file_id: uuid.UUID) -> DocumentFile | None:
    result = await db.execute(
        select(DocumentFile).where(
            DocumentFile.id == file_id,
            DocumentFile.is_deleted.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def get_segments(db: AsyncSession, file_id: uuid.UUID) -> list[DocumentTextSegment]:
    result = await db.execute(
        select(DocumentTextSegment)
        .where(DocumentTextSegment.file_id == file_id, DocumentTextSegment.is_deleted.is_(False))
        .order_by(DocumentTextSegment.page_number, DocumentTextSegment.paragraph_index, DocumentTextSegment.id)
    )
    return list(result.scalars())


async def get_links(db: AsyncSession, version_id: uuid.UUID) -> list[DocumentMasterLink]:
    result = await db.execute(
        select(DocumentMasterLink)
        .where(
            DocumentMasterLink.version_id == version_id,
            DocumentMasterLink.is_deleted.is_(False),
        )
        .order_by(DocumentMasterLink.code_snapshot)
    )
    return list(result.scalars())


async def get_links_for_master(
    db: AsyncSession, object_id: uuid.UUID, *, include_history: bool = False
) -> list[DocumentMasterLink]:
    stmt = select(DocumentMasterLink).where(
        DocumentMasterLink.master_object_id == object_id,
        DocumentMasterLink.is_deleted.is_(False),
    )
    if not include_history:
        stmt = stmt.where(
            DocumentMasterLink.version_id.in_(
                select(Document.current_version_id).where(
                    Document.current_version_id.is_not(None),
                    Document.is_deleted.is_(False),
                )
            )
        )
    result = await db.execute(stmt)
    return list(result.scalars())
