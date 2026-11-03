"""QA 文件台账与版本仓储。"""

from __future__ import annotations

import uuid

from sqlalchemy import and_, func, or_, select
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
)
from app.modules.qa.repository.processing import current_text_segment_condition
from app.shared.sql import escape_like


async def get_document_type(
    db: AsyncSession, type_id: uuid.UUID
) -> DocumentType | None:
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


# 台账可排序字段白名单。传白名单外的值回落到编号，不接受任意列名。
DOCUMENT_SORT_COLUMNS = {
    "document_no": Document.document_no,
    "title": Document.title,
}


async def list_documents(
    db: AsyncSession,
    *,
    keyword: str | None = None,
    document_type_id: uuid.UUID | None = None,
    responsible_department_id: str | None = None,
    status: str | None = None,
    include_inactive: bool = False,
    has_current_version: bool | None = None,
    sort_by: str = "document_no",
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Document], int]:
    conditions: list[ColumnElement[bool]] = [Document.is_deleted.is_(False)]
    if not include_inactive:
        conditions.append(Document.status == "active")
    if document_type_id:
        conditions.append(Document.document_type_id == document_type_id)
    if responsible_department_id:
        conditions.append(
            Document.responsible_department_id == responsible_department_id
        )
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
                            select(DocumentFile.version_id)
                            .join(
                                DocumentTextSegment,
                                DocumentTextSegment.file_id == DocumentFile.id,
                            )
                            .where(
                                or_(
                                    DocumentTextSegment.retrieval_text.ilike(
                                        term, escape="\\"
                                    ),
                                    # 只有没有派生文本的 legacy 行才回退
                                    # raw；新行的空 retrieval_text 可能是
                                    # 空锚点，不能再次把 HTML 属性当正文检索。
                                    and_(
                                        DocumentTextSegment.retrieval_text.is_(None),
                                        DocumentTextSegment.content.ilike(
                                            term, escape="\\"
                                        ),
                                    ),
                                ),
                                DocumentTextSegment.is_deleted.is_(False),
                                DocumentFile.is_deleted.is_(False),
                                current_text_segment_condition(),
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
        (
            await db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
    )
    # 二级按编号：标题可重复，只按标题排时分页边界会飘，同一份文件可能出现在两页。
    result = await db.execute(
        base.order_by(
            DOCUMENT_SORT_COLUMNS.get(sort_by, Document.document_no),
            Document.document_no,
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars()), total


async def get_versions(
    db: AsyncSession, document_id: uuid.UUID
) -> list[DocumentVersion]:
    result = await db.execute(
        select(DocumentVersion)
        .where(
            DocumentVersion.document_id == document_id,
            DocumentVersion.is_deleted.is_(False),
        )
        .order_by(DocumentVersion.version_sequence.desc())
    )
    return list(result.scalars())


async def get_version(
    db: AsyncSession, version_id: uuid.UUID
) -> DocumentVersion | None:
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


async def get_links(
    db: AsyncSession, version_id: uuid.UUID
) -> list[DocumentMasterLink]:
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
