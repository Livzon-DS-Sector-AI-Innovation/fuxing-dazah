"""Safety API — oh_hazard_monitors endpoints."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.schemas import (
    OhHazardMonitorCreate,
    OhHazardMonitorResponse,
    OhHazardMonitorUpdate,
    VerifyMonitorRequest,
)
from app.modules.safety.service import (
    OhHazardMonitorService,
)

oh_hazard_monitors_router = APIRouter()


@oh_hazard_monitors_router.get("/oh-hazard-monitors", response_model=ApiResponse, summary="获取职业危害因素监测列表")
async def get_oh_hazard_monitors(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    detection_type: str | None = None,
    workplace: str | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取职业危害因素监测列表，支持多条件筛选"""
    service = OhHazardMonitorService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_monitors(
        skip, page_size, status, detection_type, workplace, keyword
    )
    return ApiResponse(
        data=[OhHazardMonitorResponse.model_validate(i) for i in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@oh_hazard_monitors_router.post("/oh-hazard-monitors", response_model=ApiResponse, summary="创建职业危害因素监测")
async def create_oh_hazard_monitor(
    data: OhHazardMonitorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建职业危害因素监测记录"""
    service = OhHazardMonitorService(db)
    item = await service.create_monitor(data)
    await db.commit()
    return ApiResponse(data=OhHazardMonitorResponse.model_validate(item))


@oh_hazard_monitors_router.get("/oh-hazard-monitors/{monitor_id}", response_model=ApiResponse, summary="获取职业危害因素监测详情")
async def get_oh_hazard_monitor(
    monitor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取职业危害因素监测详情"""
    service = OhHazardMonitorService(db)
    item = await service.get_monitor(monitor_id)
    if not item:
        return ApiResponse(code=404, message="监测记录不存在")
    return ApiResponse(data=OhHazardMonitorResponse.model_validate(item))


@oh_hazard_monitors_router.put("/oh-hazard-monitors/{monitor_id}", response_model=ApiResponse, summary="更新职业危害因素监测")
async def update_oh_hazard_monitor(
    monitor_id: uuid.UUID,
    data: OhHazardMonitorUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新职业危害因素监测"""
    service = OhHazardMonitorService(db)
    item = await service.update_monitor(monitor_id, data)
    if not item:
        return ApiResponse(code=404, message="监测记录不存在")
    await db.commit()
    return ApiResponse(data=OhHazardMonitorResponse.model_validate(item))


@oh_hazard_monitors_router.delete("/oh-hazard-monitors/{monitor_id}", response_model=ApiResponse, summary="删除职业危害因素监测")
async def delete_oh_hazard_monitor(
    monitor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除职业危害因素监测（软删除）"""
    service = OhHazardMonitorService(db)
    ok = await service.delete_monitor(monitor_id)
    if not ok:
        return ApiResponse(code=404, message="监测记录不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


# ── Monitor Workflow ──


@oh_hazard_monitors_router.post("/oh-hazard-monitors/{monitor_id}/start", response_model=ApiResponse, summary="开始监测")
async def start_oh_hazard_monitor(
    monitor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """开始监测（草稿→检测中）"""
    service = OhHazardMonitorService(db)
    item = await service.start_monitoring(monitor_id)
    if not item:
        return ApiResponse(code=400, message="无法开始监测，当前状态不允许")
    await db.commit()
    return ApiResponse(data=OhHazardMonitorResponse.model_validate(item))


@oh_hazard_monitors_router.post("/oh-hazard-monitors/{monitor_id}/complete", response_model=ApiResponse, summary="完成监测")
async def complete_oh_hazard_monitor(
    monitor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """完成监测（检测中→已完成），自动计算OEL合规状态"""
    service = OhHazardMonitorService(db)
    item = await service.complete_monitoring(monitor_id)
    if not item:
        return ApiResponse(code=400, message="无法完成监测，当前状态不允许")
    await db.commit()
    return ApiResponse(data=OhHazardMonitorResponse.model_validate(item))


@oh_hazard_monitors_router.post("/oh-hazard-monitors/{monitor_id}/verify", response_model=ApiResponse, summary="验证监测")
async def verify_oh_hazard_monitor(
    monitor_id: uuid.UUID,
    data: VerifyMonitorRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """验证监测（已完成→已验证）"""
    service = OhHazardMonitorService(db)
    item = await service.verify_monitoring(monitor_id, data.verified_by, data.comments)
    if not item:
        return ApiResponse(code=400, message="无法验证，当前状态不允许")
    await db.commit()
    return ApiResponse(data=OhHazardMonitorResponse.model_validate(item))


# ── Monitor JSON Sub-records ──


@oh_hazard_monitors_router.post("/oh-hazard-monitors/{monitor_id}/detection-results", response_model=ApiResponse, summary="添加检测结果")
async def add_detection_result(
    monitor_id: uuid.UUID,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """追加检测结果到监测记录"""
    service = OhHazardMonitorService(db)
    item = await service.add_detection_result(monitor_id, data)
    if not item:
        return ApiResponse(code=404, message="监测记录不存在")
    await db.commit()
    return ApiResponse(data=OhHazardMonitorResponse.model_validate(item))


@oh_hazard_monitors_router.put("/oh-hazard-monitors/{monitor_id}/detection-results/{index}", response_model=ApiResponse, summary="更新检测结果")
async def update_detection_result(
    monitor_id: uuid.UUID,
    index: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新指定索引的检测结果"""
    service = OhHazardMonitorService(db)
    item = await service.update_detection_result(monitor_id, index, data)
    if not item:
        return ApiResponse(code=400, message="无法更新，监测记录不存在或索引无效")
    await db.commit()
    return ApiResponse(data=OhHazardMonitorResponse.model_validate(item))


@oh_hazard_monitors_router.delete("/oh-hazard-monitors/{monitor_id}/detection-results/{index}", response_model=ApiResponse, summary="删除检测结果")
async def delete_detection_result(
    monitor_id: uuid.UUID,
    index: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除指定索引的检测结果"""
    service = OhHazardMonitorService(db)
    item = await service.remove_detection_result(monitor_id, index)
    if not item:
        return ApiResponse(code=400, message="无法删除，监测记录不存在或索引无效")
    await db.commit()
    return ApiResponse(data=OhHazardMonitorResponse.model_validate(item))


@oh_hazard_monitors_router.post("/oh-hazard-monitors/{monitor_id}/abnormality-records", response_model=ApiResponse, summary="添加异常处置记录")
async def add_monitor_abnormality_record(
    monitor_id: uuid.UUID,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """追加异常处置记录到监测"""
    service = OhHazardMonitorService(db)
    item = await service.add_abnormality_record(monitor_id, data)
    if not item:
        return ApiResponse(code=404, message="监测记录不存在")
    await db.commit()
    return ApiResponse(data=OhHazardMonitorResponse.model_validate(item))


@oh_hazard_monitors_router.put("/oh-hazard-monitors/{monitor_id}/abnormality-records/{index}", response_model=ApiResponse, summary="更新异常处置状态")
async def update_monitor_abnormality_status(
    monitor_id: uuid.UUID,
    index: int,
    status: str = Query(..., description="状态: open/investigating/corrected/closed"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新异常处置记录状态"""
    service = OhHazardMonitorService(db)
    item = await service.update_abnormality_record_status(monitor_id, index, status)
    if not item:
        return ApiResponse(code=400, message="无法更新，监测记录不存在或索引无效")
    await db.commit()
    return ApiResponse(data=OhHazardMonitorResponse.model_validate(item))


