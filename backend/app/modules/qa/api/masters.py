"""QA 主数据端点：创建/更新/启停、别名与来源关联。"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundException
from app.core.response import paginated_response, success_response
from app.modules.qa import service
from app.modules.qa.api._deps import (
    master_create,
    master_deactivate,
    master_update,
    qa_read,
)
from app.modules.qa.repository import (
    get_master,
)
from app.modules.qa.schemas import (
    AliasIn,
    MasterObjectCreate,
    MasterObjectSourceOut,
    MasterObjectStatusIn,
    MasterObjectUpdate,
    SourceLinkIn,
)
from app.platform.identity.models import User

router = APIRouter()


class AliasUpdateRequest(BaseModel):
    aliases: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("aliases")
    @classmethod
    def validate_aliases(cls, values: list[str]) -> list[str]:
        return [AliasIn(alias=value).alias for value in values]


class SourceUpdateRequest(BaseModel):
    sources: list[SourceLinkIn] = Field(default_factory=list, max_length=50)


def _master_input_compat(payload: MasterObjectCreate) -> MasterObjectCreate:
    return payload


@router.get("/master-objects", summary="QA主数据列表")
async def list_master_objects(
    user: User = Depends(qa_read),
    db: AsyncSession = Depends(get_db),
    kind: str | None = Query(default=None),
    object_type: str | None = None,
    keyword: str | None = None,
    status: str | None = None,
    include_inactive: bool = False,
    include_deleted: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Any:
    selected_type = object_type or kind
    items, total = await service.list_master_page(
        db,
        object_type=selected_type.upper() if selected_type else None,
        keyword=keyword,
        status=status if status else (None if include_inactive else "active"),
        include_deleted=include_deleted,
        page=page,
        page_size=page_size,
    )
    result = await service.master_to_dict_batch(db, items, user=user)
    for item in result:
        # 前端兼容字段；规范字段仍保留。
        item["kind"] = item["object_type"]
        item["is_active"] = item["status"] == "active"
    return paginated_response(result, page, page_size, total)


@router.post("/master-objects", summary="创建QA主数据")
async def create_master_object(
    payload: MasterObjectCreate,
    user: User = Depends(master_create),
    db: AsyncSession = Depends(get_db),
) -> Any:
    obj = await service.create_master(db, payload, user)
    return success_response(await service.master_to_dict(db, obj, user=user))


@router.get("/master-objects/{object_id}", summary="QA主数据详情")
async def get_master_object(
    object_id: uuid.UUID,
    user: User = Depends(qa_read),
    db: AsyncSession = Depends(get_db),
) -> Any:
    obj = await get_master(db, object_id)
    if obj is None:
        raise NotFoundException("QA主数据", str(object_id))
    data = await service.master_to_dict(db, obj, user=user)
    data["kind"] = data["object_type"]
    data["is_active"] = data["status"] == "active"
    return success_response(data)


@router.put("/master-objects/{object_id}", summary="更新QA主数据")
async def update_master_object(
    object_id: uuid.UUID,
    payload: MasterObjectUpdate,
    user: User = Depends(master_update),
    db: AsyncSession = Depends(get_db),
) -> Any:
    obj = await service.update_master(db, object_id, payload, user)
    return success_response(await service.master_to_dict(db, obj, user=user))


@router.post("/master-objects/{object_id}/status", summary="切换QA主数据状态")
async def change_master_status(
    object_id: uuid.UUID,
    payload: MasterObjectStatusIn,
    user: User = Depends(master_deactivate),
    db: AsyncSession = Depends(get_db),
) -> Any:
    obj = await service.set_master_status(db, object_id, payload.status, user)
    return success_response(await service.master_to_dict(db, obj, user=user))


@router.post("/master-objects/{object_id}/activate", summary="启用QA主数据")
async def activate_master_object(
    object_id: uuid.UUID,
    user: User = Depends(master_deactivate),
    db: AsyncSession = Depends(get_db),
) -> Any:
    obj = await service.set_master_status(db, object_id, "active", user)
    return success_response(await service.master_to_dict(db, obj, user=user))


@router.post("/master-objects/{object_id}/deactivate", summary="停用QA主数据")
async def deactivate_master_object(
    object_id: uuid.UUID,
    user: User = Depends(master_deactivate),
    db: AsyncSession = Depends(get_db),
) -> Any:
    obj = await service.set_master_status(db, object_id, "inactive", user)
    return success_response(await service.master_to_dict(db, obj, user=user))


@router.put("/master-objects/{object_id}/aliases", summary="替换QA主数据别名")
async def replace_master_aliases(
    object_id: uuid.UUID,
    payload: AliasUpdateRequest,
    user: User = Depends(master_update),
    db: AsyncSession = Depends(get_db),
) -> Any:
    rows = await service.replace_master_aliases(db, object_id, payload.aliases, user)
    return success_response(
        [
            {"id": row.id, "alias": row.alias, "normalized_alias": row.normalized_alias}
            for row in rows
        ]
    )


@router.post("/master-objects/{object_id}/aliases", summary="新增QA主数据别名")
async def add_master_aliases(
    object_id: uuid.UUID,
    payload: AliasUpdateRequest,
    user: User = Depends(master_update),
    db: AsyncSession = Depends(get_db),
) -> Any:
    rows = await service.add_master_aliases(db, object_id, payload.aliases, user)
    return success_response([{"id": row.id, "alias": row.alias} for row in rows])


@router.put("/master-objects/{object_id}/sources", summary="替换QA主数据来源关联")
async def replace_master_sources(
    object_id: uuid.UUID,
    payload: SourceUpdateRequest,
    user: User = Depends(master_update),
    db: AsyncSession = Depends(get_db),
) -> Any:
    rows = await service.replace_master_sources(db, object_id, payload.sources, user)
    return success_response(
        [
            MasterObjectSourceOut.model_validate(row).model_dump(mode="json")
            for row in rows
        ]
    )


@router.post("/master-objects/{object_id}/sources", summary="新增QA主数据来源关联")
async def add_master_source_links(
    object_id: uuid.UUID,
    payload: SourceUpdateRequest,
    user: User = Depends(master_update),
    db: AsyncSession = Depends(get_db),
) -> Any:
    rows = await service.add_master_sources(db, object_id, payload.sources, user)
    return success_response(
        [
            MasterObjectSourceOut.model_validate(row).model_dump(mode="json")
            for row in rows
        ]
    )


# ───────────────────────── 引用选择器 ─────────────────────────
