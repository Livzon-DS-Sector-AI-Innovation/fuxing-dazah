"""中间体 API — 只做 HTTP 层（字典 + 批次台账 + 追溯）。"""

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.production.schemas import (
    IntermediateTypeCreate,
    IntermediateTypeUpdate,
)
from app.modules.production.service import intermediate_service
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission

router = APIRouter()
_manage = require_permission("production:process:manage")
_read = require_permission("production:batch:read")


# ── 中间体字典 ──

@router.get("/intermediate-types", summary="中间体字典列表")
async def list_intermediate_types(
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items, total = await intermediate_service.list_intermediate_types_paged(
        db, keyword, page, page_size
    )
    return paginated_response(
        [i.model_dump(mode="json") for i in items],
        page,
        page_size,
        total,
    )


@router.post("/intermediate-types", summary="新增中间体字典")
async def create_intermediate_type(
    payload: IntermediateTypeCreate,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    out = await intermediate_service.create_intermediate_type(db, payload, user)
    return success_response(out.model_dump(mode="json"))


@router.get("/intermediate-types/{type_id}", summary="中间体字典详情")
async def get_intermediate_type(
    type_id: uuid.UUID,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    out = await intermediate_service.get_intermediate_type_detail(db, type_id)
    return success_response(data=out.model_dump(mode="json"))


@router.put("/intermediate-types/{type_id}", summary="编辑中间体字典")
async def update_intermediate_type(
    type_id: uuid.UUID,
    payload: IntermediateTypeUpdate,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    out = await intermediate_service.update_intermediate_type(db, type_id, payload, user)
    return success_response(out.model_dump(mode="json"))


@router.delete("/intermediate-types/{type_id}", summary="删除中间体字典")
async def delete_intermediate_type(
    type_id: uuid.UUID,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await intermediate_service.delete_intermediate_type(db, type_id, user)
    return success_response()


# ── 批次中间体台账 ──


@router.get("/intermediates/available-outputs", summary="可用中间体产出列表（跨批次消耗选择）")
async def list_available_outputs(
    intermediate_type_id: uuid.UUID | None = None,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    outputs = await intermediate_service.get_available_outputs(db, intermediate_type_id)
    return success_response([o.model_dump(mode="json") for o in outputs])


@router.get("/batches/{batch_id}/intermediates/outputs", summary="批次中间体产出列表")
async def list_batch_intermediate_outputs(
    batch_id: uuid.UUID,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    outputs = await intermediate_service.get_batch_outputs(db, batch_id)
    return success_response([o.model_dump(mode="json") for o in outputs])


@router.get("/batches/{batch_id}/intermediates/consumptions", summary="批次中间体消耗列表")
async def list_batch_intermediate_consumptions(
    batch_id: uuid.UUID,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    consumptions = await intermediate_service.get_batch_consumptions(db, batch_id)
    return success_response([c.model_dump(mode="json") for c in consumptions])


@router.get("/intermediates/outputs/{output_id}/trace", summary="中间体物料流向追溯")
async def trace_intermediate(
    output_id: uuid.UUID,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """给定一个中间体产出 ID，返回该产出本身及其下游消耗记录。"""
    result = await intermediate_service.trace_intermediate_output(db, output_id)
    return success_response({
        "output": result["output"].model_dump(mode="json"),
        "consumptions": [c.model_dump(mode="json") for c in result["consumptions"]],
    })
