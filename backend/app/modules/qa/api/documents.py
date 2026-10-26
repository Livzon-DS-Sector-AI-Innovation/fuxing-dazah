"""QA 文件类型、文件台账与版本端点。"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AppException, NotFoundException
from app.core.response import paginated_response, success_response
from app.modules.qa import file_service, service
from app.modules.qa.api._deps import (
    config_manage,
    document_create,
    document_deactivate,
    document_update,
    qa_read,
    relation_manage,
    version_create,
    version_current,
    version_disable,
)
from app.modules.qa.repository import (
    get_document,
    get_versions,
    list_document_types,
)
from app.modules.qa.schemas import (
    DocumentCreate,
    DocumentTypeCreate,
    DocumentTypeOut,
    DocumentTypeUpdate,
    DocumentUpdate,
    RelationIn,
)
from app.platform.identity.models import User

router = APIRouter()


class RelationCompatRequest(BaseModel):
    """同时兼容规范的 relations 和前端早期的 master_object_ids。"""

    relations: list[RelationIn] | None = Field(default=None, max_length=200)
    master_object_ids: list[uuid.UUID] | None = Field(default=None, max_length=200)

    def to_relations(self) -> list[RelationIn]:
        if self.relations is not None:
            return self.relations
        return [RelationIn(master_object_id=i) for i in (self.master_object_ids or [])]


@router.get("/document-types", summary="文件类型列表")
async def get_document_types(
    user: User = Depends(qa_read),
    db: AsyncSession = Depends(get_db),
    include_inactive: bool = False,
) -> Any:
    rows = await list_document_types(db, include_inactive=include_inactive)
    return success_response(
        [DocumentTypeOut.model_validate(row).model_dump(mode="json") for row in rows]
    )


@router.post("/document-types", summary="创建文件类型")
async def post_document_type(
    payload: DocumentTypeCreate,
    user: User = Depends(config_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await service.create_document_type(db, payload, user)
    return success_response(DocumentTypeOut.model_validate(row).model_dump(mode="json"))


@router.put("/document-types/{type_id}", summary="更新文件类型")
async def put_document_type(
    type_id: uuid.UUID,
    payload: DocumentTypeUpdate,
    user: User = Depends(config_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await service.update_document_type(db, type_id, payload, user)
    return success_response(DocumentTypeOut.model_validate(row).model_dump(mode="json"))


@router.post("/document-types/{type_id}/activate", summary="启用文件类型")
async def activate_document_type(
    type_id: uuid.UUID,
    user: User = Depends(config_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await service.update_document_type(
        db, type_id, DocumentTypeUpdate(status="active"), user
    )
    return success_response(DocumentTypeOut.model_validate(row).model_dump(mode="json"))


@router.post("/document-types/{type_id}/deactivate", summary="停用文件类型")
async def deactivate_document_type(
    type_id: uuid.UUID,
    user: User = Depends(config_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await service.update_document_type(
        db, type_id, DocumentTypeUpdate(status="inactive"), user
    )
    return success_response(DocumentTypeOut.model_validate(row).model_dump(mode="json"))


@router.get("/documents", summary="质量文件台账列表")
async def get_documents(
    user: User = Depends(qa_read),
    db: AsyncSession = Depends(get_db),
    keyword: str | None = None,
    document_type_id: uuid.UUID | None = None,
    responsible_department_id: str | None = None,
    include_inactive: bool = False,
    include_history: bool = False,
    has_current_version: bool | None = None,
    sort_by: str = Query(
        "document_no", description="排序字段：document_no 编号 / title 标题"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Any:
    documents, total = await service.list_document_page(
        db,
        keyword=keyword,
        document_type_id=document_type_id,
        responsible_department_id=responsible_department_id,
        include_inactive=include_inactive,
        has_current_version=has_current_version,
        sort_by=sort_by,
        page=page,
        page_size=page_size,
    )
    result = []
    for document in documents:
        item = await service.document_list_item(db, document)
        if include_history:
            item["versions"] = [
                await service.version_to_dict(db, version)
                for version in await get_versions(db, document.id)
            ]
        item["is_active"] = item["status"] == "active"
        result.append(item)
    return paginated_response(result, page, page_size, total)


@router.post("/documents", summary="创建质量文件台账")
async def post_document(
    payload: DocumentCreate,
    user: User = Depends(document_create),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await service.create_document(db, payload, user)
    return success_response(
        await service.document_to_dict(db, row, include_versions=False)
    )


@router.get("/documents/{document_id}", summary="质量文件详情")
async def get_document_detail(
    document_id: uuid.UUID,
    user: User = Depends(qa_read),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await get_document(db, document_id)
    if row is None:
        raise NotFoundException("质量文件", str(document_id))
    return success_response(await service.document_to_dict(db, row))


@router.put("/documents/{document_id}", summary="更新质量文件台账")
async def put_document(
    document_id: uuid.UUID,
    payload: DocumentUpdate,
    user: User = Depends(document_update),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await service.update_document(db, document_id, payload, user)
    return success_response(
        await service.document_to_dict(db, row, include_versions=False)
    )


@router.post("/documents/{document_id}/activate", summary="启用质量文件")
async def activate_document(
    document_id: uuid.UUID,
    user: User = Depends(document_deactivate),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await service.set_document_status(db, document_id, "active", user)
    return success_response(
        await service.document_to_dict(db, row, include_versions=False)
    )


@router.post("/documents/{document_id}/deactivate", summary="停用质量文件")
async def deactivate_document(
    document_id: uuid.UUID,
    user: User = Depends(document_deactivate),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await service.set_document_status(db, document_id, "inactive", user)
    return success_response(
        await service.document_to_dict(db, row, include_versions=False)
    )


# ───────────────────────── 版本与关联 ─────────────────────────


@router.post("/documents/{document_id}/versions", summary="上传并登记质量文件版本")
async def post_document_version(
    document_id: uuid.UUID,
    version_label: str = Form(..., min_length=1, max_length=64),
    approved_declared: bool = Form(False),
    file: UploadFile = File(...),
    user: User = Depends(version_create),
    db: AsyncSession = Depends(get_db),
) -> Any:
    data = await file.read(file_service.MAX_FILE_SIZE + 1)
    try:
        row = await service.create_version(
            db,
            document_id,
            version_label=version_label,
            approved_declared=approved_declared,
            filename=file.filename,
            content_type=file.content_type,
            data=data,
            user=user,
        )
    except file_service.FileValidationError as exc:
        raise AppException(status_code=422, message=str(exc)) from exc
    return success_response(await service.version_to_dict(db, row))


@router.get("/documents/{document_id}/versions", summary="质量文件版本列表")
async def get_document_versions(
    document_id: uuid.UUID,
    user: User = Depends(qa_read),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await get_document(db, document_id)
    if row is None:
        raise NotFoundException("质量文件", str(document_id))
    versions = await get_versions(db, document_id)
    return success_response([await service.version_to_dict(db, v) for v in versions])


@router.put("/document-versions/{version_id}/relations", summary="维护文件版本关联")
async def put_version_relations(
    version_id: uuid.UUID,
    payload: RelationCompatRequest,
    user: User = Depends(relation_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    rows = await service.set_relations(db, version_id, payload.to_relations(), user)
    return success_response([await service._relation_dict(db, row) for row in rows])


@router.post(
    "/documents/{document_id}/versions/{version_id}/copy-relations",
    summary="显式复制上一当前版本关联",
)
async def post_copy_relations(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    user: User = Depends(relation_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    rows = await service.copy_current_relations(db, document_id, version_id, user)
    return success_response([await service._relation_dict(db, row) for row in rows])


@router.post(
    "/documents/{document_id}/versions/{version_id}/make-current",
    summary="将版本设为当前",
)
async def post_make_current(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    user: User = Depends(version_current),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await service.make_current(db, document_id, version_id, user)
    row = await get_document(db, document_id)
    if row is None:
        raise NotFoundException("质量文件", str(document_id))
    return success_response(await service.document_to_dict(db, row))


@router.post("/document-versions/{version_id}/activate", summary="启用质量文件版本")
async def activate_version(
    version_id: uuid.UUID,
    user: User = Depends(version_disable),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await service.activate_version(db, version_id, user)
    return success_response(await service.version_to_dict(db, row))


@router.post("/document-versions/{version_id}/deactivate", summary="停用质量文件版本")
async def deactivate_version(
    version_id: uuid.UUID,
    user: User = Depends(version_disable),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await service.disable_version(db, version_id, user)
    return success_response(await service.version_to_dict(db, row))
