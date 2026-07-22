"""Safety API — contractors endpoints."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.schemas import (
    ContractorCreate,
    ContractorResponse,
    ContractorUpdate,
    ContractorWorkRecordCreate,
    ContractorWorkRecordResponse,
    ContractorWorkRecordUpdate,
    EvaluateWorkRecordRequest,
)
from app.modules.safety.service import (
    SafetyService,
)

contractors_router = APIRouter()


@contractors_router.get("/contractors", response_model=ApiResponse, summary="获取承包商列表")
async def get_contractors(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    qualification_type: str | None = None,
    training_status: str | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取承包商列表"""
    service = SafetyService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_contractors(
        skip, page_size, status, qualification_type, training_status, keyword,
    )
    return ApiResponse(
        data=[ContractorResponse.model_validate(c) for c in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@contractors_router.get("/contractors/{contractor_id}", response_model=ApiResponse, summary="获取承包商详情")
async def get_contractor(
    contractor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取承包商详情（含施工记录）"""
    service = SafetyService(db)
    item = await service.get_contractor(contractor_id)
    if not item:
        return ApiResponse(code=404, message="承包商不存在")
    return ApiResponse(data=ContractorResponse.model_validate(item))


@contractors_router.post("/contractors", response_model=ApiResponse, summary="创建承包商")
async def create_contractor(
    data: ContractorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建承包商"""
    service = SafetyService(db)
    item = await service.create_contractor(data)
    await db.commit()
    return ApiResponse(data=ContractorResponse.model_validate(item))


@contractors_router.put("/contractors/{contractor_id}", response_model=ApiResponse, summary="更新承包商")
async def update_contractor(
    contractor_id: uuid.UUID,
    data: ContractorUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新承包商"""
    service = SafetyService(db)
    item = await service.update_contractor(contractor_id, data)
    if not item:
        return ApiResponse(code=404, message="承包商不存在")
    await db.commit()
    return ApiResponse(data=ContractorResponse.model_validate(item))


@contractors_router.delete("/contractors/{contractor_id}", response_model=ApiResponse, summary="删除承包商")
async def delete_contractor(
    contractor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除承包商（软删除）"""
    service = SafetyService(db)
    result = await service.delete_contractor(contractor_id)
    if not result:
        return ApiResponse(code=404, message="承包商不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


@contractors_router.post("/contractors/{contractor_id}/blacklist", response_model=ApiResponse, summary="加入黑名单")
async def blacklist_contractor(
    contractor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """将承包商加入黑名单"""
    service = SafetyService(db)
    item = await service.blacklist_contractor(contractor_id)
    if not item:
        return ApiResponse(code=404, message="承包商不存在")
    await db.commit()
    return ApiResponse(data=ContractorResponse.model_validate(item))


@contractors_router.post("/contractors/{contractor_id}/activate", response_model=ApiResponse, summary="激活承包商")
async def activate_contractor(
    contractor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """激活承包商（从停用或黑名单恢复）"""
    service = SafetyService(db)
    item = await service.activate_contractor(contractor_id)
    if not item:
        return ApiResponse(code=404, message="承包商不存在")
    await db.commit()
    return ApiResponse(data=ContractorResponse.model_validate(item))


@contractors_router.post(
    "/contractors/{contractor_id}/update-training",
    response_model=ApiResponse,
    summary="更新培训状态",
)
async def update_contractor_training(
    contractor_id: uuid.UUID,
    training_status: str = Query(..., description="培训状态: untrained/in_progress/passed/expired"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新承包商培训状态"""
    service = SafetyService(db)
    item = await service.update_contractor_training(contractor_id, training_status)
    if not item:
        return ApiResponse(code=404, message="承包商不存在")
    await db.commit()
    return ApiResponse(data=ContractorResponse.model_validate(item))


# ── 施工记录子表 ──


@contractors_router.get(
    "/contractors/{contractor_id}/work-records",
    response_model=ApiResponse,
    summary="获取承包商施工记录",
)
async def get_work_records(
    contractor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取承包商的施工记录列表"""
    service = SafetyService(db)
    items = await service.get_work_records(contractor_id)
    return ApiResponse(data=[ContractorWorkRecordResponse.model_validate(r) for r in items])


@contractors_router.post(
    "/contractors/{contractor_id}/work-records",
    response_model=ApiResponse,
    summary="创建施工记录",
)
async def create_work_record(
    contractor_id: uuid.UUID,
    data: ContractorWorkRecordCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建承包商的施工记录"""
    service = SafetyService(db)
    item = await service.create_work_record(contractor_id, data)
    await db.commit()
    return ApiResponse(data=ContractorWorkRecordResponse.model_validate(item))


@contractors_router.put(
    "/contractors/{contractor_id}/work-records/{record_id}",
    response_model=ApiResponse,
    summary="更新施工记录",
)
async def update_work_record(
    contractor_id: uuid.UUID,
    record_id: uuid.UUID,
    data: ContractorWorkRecordUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新施工记录"""
    service = SafetyService(db)
    item = await service.update_work_record(record_id, data)
    if not item:
        return ApiResponse(code=404, message="记录不存在")
    await db.commit()
    return ApiResponse(data=ContractorWorkRecordResponse.model_validate(item))


@contractors_router.delete(
    "/contractors/{contractor_id}/work-records/{record_id}",
    response_model=ApiResponse,
    summary="删除施工记录",
)
async def delete_work_record(
    contractor_id: uuid.UUID,
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除施工记录（软删除）"""
    service = SafetyService(db)
    result = await service.delete_work_record(record_id)
    if not result:
        return ApiResponse(code=404, message="记录不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


@contractors_router.post(
    "/contractors/{contractor_id}/work-records/{record_id}/evaluate",
    response_model=ApiResponse,
    summary="评价施工记录",
)
async def evaluate_work_record(
    contractor_id: uuid.UUID,
    record_id: uuid.UUID,
    data: EvaluateWorkRecordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """评价施工记录"""
    service = SafetyService(db)
    item = await service.evaluate_work_record(
        record_id, data.score, data.comments, data.evaluator,
    )
    if not item:
        return ApiResponse(code=404, message="记录不存在")
    await db.commit()
    return ApiResponse(data=ContractorWorkRecordResponse.model_validate(item))


