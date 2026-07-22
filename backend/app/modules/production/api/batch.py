"""批次 API — 只做 HTTP 层。"""

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.production.schemas import (
    BatchCreate,
    BatchOut,
    DeriveIn,
    MergeIn,
)
from app.modules.production.service import batch_service, trace_service
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission

router = APIRouter()
_submit = require_permission("production:batch:submit")
_read = require_permission("production:batch:read")


@router.get("/batches", summary="批次列表")
async def list_batches(
    product_id: uuid.UUID | None = None,
    status: str | None = None,
    keyword: str | None = None,
    entry_node_filter: str | None = Query(None, pattern="^(root|derived)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    order_by: str = Query("created_at", pattern="^(batch_no|created_at)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items, total = await batch_service.list_batches_paged(
        db, product_id, status, keyword, entry_node_filter, page, page_size, order_by, order
    )
    return paginated_response(
        [BatchOut.model_validate(i).model_dump(mode="json") for i in items],
        page,
        page_size,
        total,
    )


@router.post("/batches", summary="创建起始批次")
async def create_batch(
    payload: BatchCreate,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    batch = await batch_service.create_batch(db, payload, user)
    return success_response(BatchOut.model_validate(batch).model_dump(mode="json"))


@router.get("/batches/{batch_id}", summary="批次详情（含执行时间线）")
async def get_batch_detail(
    batch_id: uuid.UUID,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    detail = await batch_service.get_batch_detail(db, batch_id)
    return success_response(detail.model_dump(mode="json"))


@router.post("/batches/{batch_id}/derive", summary="分裂 / 1→1 换号")
async def derive_batches(
    batch_id: uuid.UUID,
    payload: DeriveIn,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    children = await batch_service.derive_batches(db, batch_id, payload, user)
    return success_response(
        [BatchOut.model_validate(c).model_dump(mode="json") for c in children]
    )


@router.post("/batches/merge", summary="合并批次")
async def merge_batches(
    payload: MergeIn,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    child = await batch_service.merge_batches(db, payload, user)
    return success_response(BatchOut.model_validate(child).model_dump(mode="json"))


@router.post("/batches/{batch_id}/complete", summary="批次完成")
async def complete_batch(
    batch_id: uuid.UUID,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    batch = await batch_service.complete_batch(db, batch_id, user)
    return success_response(BatchOut.model_validate(batch).model_dump(mode="json"))


@router.post("/batches/{batch_id}/cancel", summary="批次报废")
async def cancel_batch(
    batch_id: uuid.UUID,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    batch = await batch_service.cancel_batch(db, batch_id, user)
    return success_response(BatchOut.model_validate(batch).model_dump(mode="json"))


@router.get("/batches/{batch_id}/trace", summary="全链路溯源")
async def get_trace(
    batch_id: uuid.UUID,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    trace = await trace_service.get_trace(db, batch_id)
    return success_response(trace.model_dump(mode="json"))
