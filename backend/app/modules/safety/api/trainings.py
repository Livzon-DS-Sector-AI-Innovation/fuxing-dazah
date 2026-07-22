"""Safety API — trainings endpoints."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.schemas import (
    SafetyTrainingCreate,
    SafetyTrainingResponse,
    SafetyTrainingUpdate,
    TrainingRecordCreate,
    TrainingRecordResponse,
    TrainingRecordUpdate,
)
from app.modules.safety.service import (
    SafetyService,
)

trainings_router = APIRouter()


@trainings_router.get("/trainings", response_model=ApiResponse, summary="获取安全培训列表")
async def get_trainings(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    training_type: str | None = None,
    department: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取安全培训列表"""
    service = SafetyService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_trainings(skip, page_size, status, training_type, department)
    return ApiResponse(
        data=[SafetyTrainingResponse.model_validate(t) for t in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@trainings_router.get("/trainings/{training_id}", response_model=ApiResponse, summary="获取安全培训详情")
async def get_training(
    training_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取安全培训详情"""
    service = SafetyService(db)
    item = await service.get_training(training_id)
    if not item:
        return ApiResponse(code=404, message="培训不存在")
    return ApiResponse(data=SafetyTrainingResponse.model_validate(item))


@trainings_router.post("/trainings", response_model=ApiResponse, summary="创建安全培训")
async def create_training(
    data: SafetyTrainingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建安全培训"""
    service = SafetyService(db)
    item = await service.create_training(data)
    await db.commit()
    return ApiResponse(data=SafetyTrainingResponse.model_validate(item))


@trainings_router.put("/trainings/{training_id}", response_model=ApiResponse, summary="更新安全培训")
async def update_training(
    training_id: uuid.UUID,
    data: SafetyTrainingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新安全培训"""
    service = SafetyService(db)
    item = await service.update_training(training_id, data)
    if not item:
        return ApiResponse(code=404, message="培训不存在")
    await db.commit()
    return ApiResponse(data=SafetyTrainingResponse.model_validate(item))


@trainings_router.post("/trainings/{training_id}/start", response_model=ApiResponse, summary="开始培训")
async def start_training(
    training_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """开始培训（草稿→进行中）"""
    service = SafetyService(db)
    item = await service.start_training(training_id)
    if not item:
        return ApiResponse(code=400, message="无法开始培训，当前状态不允许")
    await db.commit()
    return ApiResponse(data=SafetyTrainingResponse.model_validate(item))


@trainings_router.post("/trainings/{training_id}/complete", response_model=ApiResponse, summary="完成培训")
async def complete_training(
    training_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """完成培训"""
    service = SafetyService(db)
    item = await service.complete_training(training_id)
    if not item:
        return ApiResponse(code=400, message="无法完成培训，当前状态不允许")
    await db.commit()
    return ApiResponse(data=SafetyTrainingResponse.model_validate(item))


@trainings_router.delete("/trainings/{training_id}", response_model=ApiResponse, summary="删除安全培训")
async def delete_training(
    training_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除安全培训"""
    service = SafetyService(db)
    result = await service.delete_training(training_id)
    if not result:
        return ApiResponse(code=404, message="培训不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


# ==================== 培训记录 Routes ====================


@trainings_router.get(
    "/trainings/{training_id}/records",
    response_model=ApiResponse,
    summary="获取培训签到记录列表",
)
async def get_training_records(
    training_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取培训签到记录列表"""
    service = SafetyService(db)
    items = await service.get_training_records(training_id)
    return ApiResponse(data=[TrainingRecordResponse.model_validate(r) for r in items])


@trainings_router.post(
    "/trainings/{training_id}/records",
    response_model=ApiResponse,
    summary="添加培训签到记录",
)
async def create_training_record(
    training_id: uuid.UUID,
    data: TrainingRecordCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """添加培训签到记录"""
    service = SafetyService(db)
    data.training_id = training_id
    item = await service.create_training_record(data)
    await db.commit()
    return ApiResponse(data=TrainingRecordResponse.model_validate(item))


@trainings_router.put(
    "/training-records/{record_id}",
    response_model=ApiResponse,
    summary="更新培训签到记录",
)
async def update_training_record(
    record_id: uuid.UUID,
    data: TrainingRecordUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新培训签到记录"""
    service = SafetyService(db)
    item = await service.update_training_record(record_id, data)
    if not item:
        return ApiResponse(code=404, message="记录不存在")
    await db.commit()
    return ApiResponse(data=TrainingRecordResponse.model_validate(item))


@trainings_router.delete(
    "/training-records/{record_id}",
    response_model=ApiResponse,
    summary="删除培训签到记录",
)
async def delete_training_record(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除培训签到记录"""
    service = SafetyService(db)
    result = await service.delete_training_record(record_id)
    if not result:
        return ApiResponse(code=404, message="记录不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


# ==================== 培训证书接口 ====================


@trainings_router.get("/training-certificates", response_model=ApiResponse, summary="获取证书列表")
async def get_training_certificates(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    certificate_status: str | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取所有培训证书列表（含即将到期/已过期筛选）"""
    service = SafetyService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_training_certificates(
        skip, page_size, certificate_status, keyword,
    )
    return ApiResponse(
        data=[TrainingRecordResponse.model_validate(r) for r in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@trainings_router.get("/training-certificates/expiring", response_model=ApiResponse, summary="获取即将到期证书")
async def get_expiring_certificates(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取30天内即将到期的证书"""
    service = SafetyService(db)
    items = await service.get_expiring_certificates()
    return ApiResponse(data=[TrainingRecordResponse.model_validate(r) for r in items])


