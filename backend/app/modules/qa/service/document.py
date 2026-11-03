"""QA 文件类型与文件台账服务：创建/更新/启停、列表与序列化。"""

import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AppException,
    DuplicateException,
    NotFoundException,
)
from app.modules.qa import (
    file_service as file_service,  # 显式再导出，供 api 层与测试补丁使用
)
from app.modules.qa.models import (
    AIAuthorityPolicy,
    Document,
    DocumentType,
    RecordStatus,
)
from app.modules.qa.repository import (
    get_document,
    get_document_type,
    get_file_for_version,
    get_versions,
    list_documents,
)
from app.modules.qa.service._shared import (
    _actor_id,
    _audit,
    _require_text,
    _resolve_department_patch,
    _validate_department,
    normalize_code,
)
from app.modules.qa.service.version import version_to_dict
from app.platform.identity.models import User

logger = logging.getLogger(__name__)


async def create_document_type(
    db: AsyncSession, payload: Any, user: User | None = None
) -> DocumentType:
    code = normalize_code(_require_text(payload.code, "文件类型编码"))
    duplicate = await db.execute(
        select(DocumentType).where(func.upper(DocumentType.code) == code)
    )
    if duplicate.scalar_one_or_none() is not None:
        raise DuplicateException("文件类型编码", code)
    row = DocumentType(
        code=code,
        name=_require_text(payload.name, "文件类型名称"),
        description=(
            payload.description.strip()
            if getattr(payload, "description", None)
            else None
        ),
        ai_source_policy=getattr(
            payload, "ai_source_policy", AIAuthorityPolicy.AUTHORITATIVE.value
        ),
        status=RecordStatus.ACTIVE.value,
        created_by=_actor_id(user),
        updated_by=_actor_id(user),
    )
    db.add(row)
    await db.flush()
    await _audit(
        db,
        action="create",
        user=user,
        resource_type="document_type",
        resource_id=row.id,
        new_value={
            "code": row.code,
            "name": row.name,
            "description": row.description,
            "ai_source_policy": row.ai_source_policy,
        },
    )
    return row


async def update_document_type(
    db: AsyncSession,
    type_id: uuid.UUID,
    payload: Any,
    user: User | None = None,
) -> DocumentType:
    row = await get_document_type(db, type_id)
    if row is None:
        raise NotFoundException("文件类型", str(type_id))
    old = {
        "name": row.name,
        "status": row.status,
        "description": row.description,
        "ai_source_policy": row.ai_source_policy,
    }
    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        row.name = _require_text(data["name"], "文件类型名称")
    if "description" in data:
        row.description = data["description"].strip() if data["description"] else None
    if "ai_source_policy" in data and data["ai_source_policy"] is not None:
        row.ai_source_policy = data["ai_source_policy"]
    for key in ("status",):
        if key in data:
            setattr(row, key, data[key])
    row.updated_by = _actor_id(user)
    await db.flush()
    await _audit(
        db,
        action="update",
        user=user,
        resource_type="document_type",
        resource_id=row.id,
        old_value=old,
        new_value={
            "name": row.name,
            "status": row.status,
            "description": row.description,
            "ai_source_policy": row.ai_source_policy,
        },
    )
    # UPDATE 无 RETURNING：re-fetch 回填 updated_at，否则序列化时 MissingGreenlet
    return await get_document_type(db, type_id) or row


async def create_document(
    db: AsyncSession, payload: Any, user: User | None = None
) -> Document:
    document_no = normalize_code(_require_text(payload.document_no, "文件编号"))
    duplicate = await db.execute(
        select(Document).where(func.upper(Document.document_no) == document_no)
    )
    if duplicate.scalar_one_or_none() is not None:
        raise DuplicateException("文件编号", document_no)
    doc_type = await get_document_type(db, payload.document_type_id)
    if doc_type is None or doc_type.status != RecordStatus.ACTIVE.value:
        raise AppException(status_code=422, message="文件类型不存在或已停用")
    dept_id, dept_name = await _validate_department(
        db,
        payload.responsible_department_id,
        payload.responsible_department_name_snapshot,
    )
    row = Document(
        document_no=document_no,
        title=_require_text(payload.title, "文件标题"),
        document_type_id=payload.document_type_id,
        responsible_department_id=dept_id,
        responsible_department_name_snapshot=dept_name,
        status=RecordStatus.ACTIVE.value,
        created_by=_actor_id(user),
        updated_by=_actor_id(user),
    )
    db.add(row)
    await db.flush()
    await _audit(
        db,
        action="create",
        user=user,
        resource_type="document",
        resource_id=row.id,
        new_value={"document_no": row.document_no, "title": row.title},
    )
    return row


async def update_document(
    db: AsyncSession,
    document_id: uuid.UUID,
    payload: Any,
    user: User | None = None,
) -> Document:
    row = await get_document(db, document_id)
    if row is None:
        raise NotFoundException("质量文件", str(document_id))
    old = {
        "title": row.title,
        "document_type_id": str(row.document_type_id),
        "status": row.status,
        "responsible_department_id": row.responsible_department_id,
    }
    data = payload.model_dump(exclude_unset=True)
    if "title" in data:
        row.title = _require_text(data["title"], "文件标题")
    if "document_type_id" in data and data["document_type_id"] is not None:
        doc_type = await get_document_type(db, data["document_type_id"])
        if doc_type is None or doc_type.status != RecordStatus.ACTIVE.value:
            raise AppException(status_code=422, message="文件类型不存在或已停用")
        row.document_type_id = data["document_type_id"]
    if (
        "responsible_department_id" in data
        or "responsible_department_name_snapshot" in data
    ):
        dept_id, dept_name = await _resolve_department_patch(
            db,
            current_id=row.responsible_department_id,
            current_name=row.responsible_department_name_snapshot,
            data=data,
        )
        row.responsible_department_id, row.responsible_department_name_snapshot = (
            dept_id,
            dept_name,
        )
    row.updated_by = _actor_id(user)
    await db.flush()
    await _audit(
        db,
        action="update",
        user=user,
        resource_type="document",
        resource_id=row.id,
        old_value=old,
        new_value={"title": row.title, "status": row.status},
    )
    # UPDATE 无 RETURNING：re-fetch 回填 updated_at，否则序列化时 MissingGreenlet
    return await get_document(db, document_id) or row


async def set_document_status(
    db: AsyncSession, document_id: uuid.UUID, status: str, user: User | None = None
) -> Document:
    if status not in (RecordStatus.ACTIVE.value, RecordStatus.INACTIVE.value):
        raise AppException(status_code=422, message="状态只能是 active 或 inactive")
    row = await get_document(db, document_id)
    if row is None:
        raise NotFoundException("质量文件", str(document_id))
    old = row.status
    row.status = status
    row.updated_by = _actor_id(user)
    await db.flush()
    await _audit(
        db,
        action="activate" if status == "active" else "deactivate",
        user=user,
        resource_type="document",
        resource_id=row.id,
        old_value={"status": old},
        new_value={"status": status},
    )
    # UPDATE 无 RETURNING：re-fetch 回填 updated_at，否则序列化时 MissingGreenlet
    return await get_document(db, document_id) or row


# ───────────────────────── 版本、文件和关系 ─────────────────────────


async def document_to_dict(
    db: AsyncSession, document: Document, *, include_versions: bool = True
) -> dict[str, Any]:
    doc_type = await get_document_type(db, document.document_type_id)
    versions = await get_versions(db, document.id) if include_versions else []
    return {
        "id": document.id,
        "document_no": document.document_no,
        "title": document.title,
        "document_type_id": document.document_type_id,
        "document_type": (
            {
                "id": doc_type.id,
                "code": doc_type.code,
                "name": doc_type.name,
                "status": doc_type.status,
                "description": doc_type.description,
                "ai_source_policy": doc_type.ai_source_policy,
                "created_at": doc_type.created_at,
                "updated_at": doc_type.updated_at,
            }
            if doc_type
            else None
        ),
        "responsible_department_id": document.responsible_department_id,
        "responsible_department_name_snapshot": document.responsible_department_name_snapshot,
        "status": document.status,
        "is_active": document.status == RecordStatus.ACTIVE.value,
        "current_version_id": document.current_version_id,
        "created_at": document.created_at,
        "updated_at": document.updated_at,
        "versions": [await version_to_dict(db, v) for v in versions],
    }


async def document_list_item(db: AsyncSession, document: Document) -> dict[str, Any]:
    doc_type = await get_document_type(db, document.document_type_id)
    versions = await get_versions(db, document.id)
    current = next((v for v in versions if v.id == document.current_version_id), None)
    current_file = await get_file_for_version(db, current.id) if current else None
    return {
        "id": document.id,
        "document_no": document.document_no,
        "title": document.title,
        "document_type_id": document.document_type_id,
        "document_type_name": doc_type.name if doc_type else None,
        "document_type_code": doc_type.code if doc_type else None,
        "responsible_department_id": document.responsible_department_id,
        "responsible_department_name_snapshot": document.responsible_department_name_snapshot,
        "status": document.status,
        "is_active": document.status == RecordStatus.ACTIVE.value,
        "current_version_id": document.current_version_id,
        "current_version_label": current.version_label if current else None,
        "current_extraction_status": current_file.extraction_status
        if current_file
        else None,
        "version_count": len(versions),
        "created_at": document.created_at,
        "updated_at": document.updated_at,
    }


async def list_document_page(
    db: AsyncSession, **kwargs: Any
) -> tuple[list[Document], int]:
    return await list_documents(db, **kwargs)
