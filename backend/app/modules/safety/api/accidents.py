"""Safety API — accidents endpoints."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.schemas import (
    AccidentCreate,
    AccidentResponse,
    AccidentUpdate,
)
from app.modules.safety.service import (
    SafetyService,
)

accidents_router = APIRouter()


@accidents_router.get("/accidents", response_model=ApiResponse, summary="获取事故列表")
async def get_accidents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    accident_type: str | None = None,
    accident_level: str | None = None,
    department: str | None = Query(None, description="部门"),
    date_from: str | None = Query(None, description="发生时间起 (YYYY-MM-DD)"),
    date_to: str | None = Query(None, description="发生时间止 (YYYY-MM-DD)"),
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取事故列表"""
    service = SafetyService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_accidents(
        skip, page_size, status, accident_type, accident_level,
        department,
        datetime.fromisoformat(date_from) if date_from else None,
        datetime.fromisoformat(date_to) if date_to else None,
        keyword,
    )
    return ApiResponse(
        data=[AccidentResponse.model_validate(a) for a in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@accidents_router.get("/accidents/{accident_id}", response_model=ApiResponse, summary="获取事故详情")
async def get_accident(
    accident_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取事故详情"""
    service = SafetyService(db)
    item = await service.get_accident(accident_id)
    if not item:
        return ApiResponse(code=404, message="事故不存在")
    return ApiResponse(data=AccidentResponse.model_validate(item))


@accidents_router.post("/accidents", response_model=ApiResponse, summary="创建事故")
async def create_accident(
    data: AccidentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建事故"""
    service = SafetyService(db)
    item = await service.create_accident(data)
    await db.commit()
    return ApiResponse(data=AccidentResponse.model_validate(item))


@accidents_router.put("/accidents/{accident_id}", response_model=ApiResponse, summary="更新事故")
async def update_accident(
    accident_id: uuid.UUID,
    data: AccidentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新事故"""
    service = SafetyService(db)
    item = await service.update_accident(accident_id, data)
    if not item:
        return ApiResponse(code=404, message="事故不存在")
    await db.commit()
    return ApiResponse(data=AccidentResponse.model_validate(item))


@accidents_router.post(
    "/accidents/{accident_id}/investigate",
    response_model=ApiResponse,
    summary="开始调查事故",
)
async def investigate_accident(
    accident_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """开始调查事故"""
    service = SafetyService(db)
    user_id = current_user.id if current_user else None
    user_name = current_user.name if current_user else None
    item = await service.investigate_accident(accident_id, user_id, user_name)
    if not item:
        return ApiResponse(code=400, message="无法开始调查，当前状态不允许")
    await db.commit()
    return ApiResponse(data=AccidentResponse.model_validate(item))


@accidents_router.post(
    "/accidents/{accident_id}/resolve",
    response_model=ApiResponse,
    summary="完成调查事故",
)
async def resolve_accident(
    accident_id: uuid.UUID,
    direct_cause: str = Query(..., description="直接原因"),
    root_cause: str = Query(..., description="根本原因"),
    handling_measures: str = Query(..., description="处理措施"),
    corrective_actions: str | None = Query(None, description="纠正预防措施"),
    investigation_findings: str | None = Query(None, description="调查发现"),
    investigation_method: str | None = Query(None, description="调查方法"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """完成调查事故"""
    service = SafetyService(db)
    item = await service.resolve_accident(
        accident_id, direct_cause, root_cause, handling_measures, corrective_actions,
        investigation_findings, investigation_method,
    )
    if not item:
        return ApiResponse(code=400, message="无法完成调查，当前状态不允许")
    await db.commit()
    return ApiResponse(data=AccidentResponse.model_validate(item))


@accidents_router.post(
    "/accidents/{accident_id}/start-capa",
    response_model=ApiResponse,
    summary="启动CAPA",
)
async def start_capa(
    accident_id: uuid.UUID,
    corrective_action_deadline: str = Query(..., description="CAPA截止日期 (YYYY-MM-DD)"),
    corrective_action_responsible: str = Query(..., description="CAPA责任人"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """启动CAPA: investigated → capa_in_progress"""
    service = SafetyService(db)
    item = await service.start_capa(
        accident_id,
        datetime.fromisoformat(corrective_action_deadline),
        corrective_action_responsible,
    )
    if not item:
        return ApiResponse(code=400, message="无法启动CAPA，当前状态不允许")
    await db.commit()
    return ApiResponse(data=AccidentResponse.model_validate(item))


@accidents_router.post(
    "/accidents/{accident_id}/verify-capa",
    response_model=ApiResponse,
    summary="验证CAPA并关闭事故",
)
async def verify_capa(
    accident_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """验证CAPA并关闭事故: capa_in_progress → closed"""
    service = SafetyService(db)
    user_id = current_user.id if current_user else None
    user_name = current_user.name if current_user else None
    item = await service.verify_capa(accident_id, user_id, user_name)
    if not item:
        return ApiResponse(code=400, message="无法验证CAPA，当前状态不允许")
    await db.commit()
    return ApiResponse(data=AccidentResponse.model_validate(item))


@accidents_router.post(
    "/accidents/{accident_id}/close",
    response_model=ApiResponse,
    summary="直接关闭事故",
)
async def close_accident(
    accident_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """直接关闭事故（无CAPA时）"""
    service = SafetyService(db)
    item = await service.close_accident(accident_id)
    if not item:
        return ApiResponse(code=400, message="无法关闭，当前状态不允许")
    await db.commit()
    return ApiResponse(data=AccidentResponse.model_validate(item))


@accidents_router.delete("/accidents/{accident_id}", response_model=ApiResponse, summary="删除事故")
async def delete_accident(
    accident_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除事故"""
    service = SafetyService(db)
    result = await service.delete_accident(accident_id)
    if not result:
        return ApiResponse(code=404, message="事故不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


