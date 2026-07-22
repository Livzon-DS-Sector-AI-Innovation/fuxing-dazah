"""Safety API — ehs_changes endpoints."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.schemas import (
    ApproveEhsChangeRequest,
    CloseEhsChangeRequest,
    EhsChangeCreate,
    EhsChangeResponse,
    EhsChangeUpdate,
)
from app.modules.safety.service import (
    EhsChangeService,
)

ehs_changes_router = APIRouter()


@ehs_changes_router.get("/ehs-changes", response_model=ApiResponse, summary="获取EHS变更列表")
async def get_ehs_changes(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    change_type: str | None = None,
    change_grade: str | None = None,
    change_duration: str | None = None,
    department: str | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取EHS变更列表，支持多条件筛选"""
    service = EhsChangeService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_ehs_changes(
        skip, page_size, status, change_type, change_grade, change_duration, department, keyword
    )
    return ApiResponse(
        data=[EhsChangeResponse.model_validate(i) for i in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@ehs_changes_router.post("/ehs-changes", response_model=ApiResponse, summary="创建EHS变更")
async def create_ehs_change(
    data: EhsChangeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建EHS变更申请"""
    service = EhsChangeService(db)
    item = await service.create_ehs_change(data)
    await db.commit()
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


@ehs_changes_router.get("/ehs-changes/{change_id}", response_model=ApiResponse, summary="获取EHS变更详情")
async def get_ehs_change(
    change_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取EHS变更详情"""
    service = EhsChangeService(db)
    item = await service.get_ehs_change(change_id)
    if not item:
        return ApiResponse(code=404, message="变更不存在")
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


@ehs_changes_router.put("/ehs-changes/{change_id}", response_model=ApiResponse, summary="更新EHS变更")
async def update_ehs_change(
    change_id: uuid.UUID,
    data: EhsChangeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新EHS变更"""
    service = EhsChangeService(db)
    item = await service.update_ehs_change(change_id, data)
    if not item:
        return ApiResponse(code=404, message="变更不存在")
    await db.commit()
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


@ehs_changes_router.delete("/ehs-changes/{change_id}", response_model=ApiResponse, summary="删除EHS变更")
async def delete_ehs_change(
    change_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除EHS变更（软删除）"""
    service = EhsChangeService(db)
    ok = await service.delete_ehs_change(change_id)
    if not ok:
        return ApiResponse(code=404, message="变更不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


# ── EHS变更 工作流 Routes ──


@ehs_changes_router.post("/ehs-changes/{change_id}/submit", response_model=ApiResponse, summary="提交EHS变更")
async def submit_ehs_change(
    change_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """提交变更（草稿→审核中；紧急变更自动批准）"""
    service = EhsChangeService(db)
    item = await service.submit_change(change_id)
    if not item:
        return ApiResponse(code=400, message="无法提交，当前状态不允许")
    await db.commit()
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


@ehs_changes_router.post("/ehs-changes/{change_id}/approve", response_model=ApiResponse, summary="审批EHS变更")
async def approve_ehs_change(
    change_id: uuid.UUID,
    data: ApproveEhsChangeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """审批变更（审核中→已批准/已驳回）"""
    service = EhsChangeService(db)
    item = await service.approve_change(change_id, data.decision, data.comments)
    if not item:
        return ApiResponse(code=400, message="无法审批，当前状态不允许")
    await db.commit()
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


@ehs_changes_router.post("/ehs-changes/{change_id}/reject", response_model=ApiResponse, summary="驳回EHS变更")
async def reject_ehs_change(
    change_id: uuid.UUID,
    comments: str | None = Query(None, description="驳回原因"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """驳回变更（审核中→已驳回）"""
    service = EhsChangeService(db)
    item = await service.reject_change(change_id, comments)
    if not item:
        return ApiResponse(code=400, message="无法驳回，当前状态不允许")
    await db.commit()
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


@ehs_changes_router.post("/ehs-changes/{change_id}/start-implementation", response_model=ApiResponse, summary="开始实施EHS变更")
async def start_implementation_ehs_change(
    change_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """开始实施变更（已批准→实施中）"""
    service = EhsChangeService(db)
    item = await service.start_implementation(change_id)
    if not item:
        return ApiResponse(code=400, message="无法开始实施，当前状态不允许")
    await db.commit()
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


@ehs_changes_router.post("/ehs-changes/{change_id}/commission", response_model=ApiResponse, summary="投用EHS变更")
async def commission_ehs_change(
    change_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """投用变更（实施中→已投用）"""
    service = EhsChangeService(db)
    item = await service.commission_change(change_id)
    if not item:
        return ApiResponse(code=400, message="无法投用，当前状态不允许")
    await db.commit()
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


@ehs_changes_router.post("/ehs-changes/{change_id}/close", response_model=ApiResponse, summary="关闭EHS变更")
async def close_ehs_change(
    change_id: uuid.UUID,
    data: CloseEhsChangeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """关闭变更（已投用→已关闭）"""
    service = EhsChangeService(db)
    item = await service.close_change(
        change_id, data.closed_by, data.temp_expiry_date, data.restored_date
    )
    if not item:
        return ApiResponse(code=400, message="无法关闭，当前状态不允许")
    await db.commit()
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


@ehs_changes_router.post("/ehs-changes/{change_id}/cancel", response_model=ApiResponse, summary="取消EHS变更")
async def cancel_ehs_change(
    change_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """取消变更（草稿→已关闭）"""
    service = EhsChangeService(db)
    item = await service.cancel_change(change_id)
    if not item:
        return ApiResponse(code=400, message="无法取消，当前状态不允许")
    await db.commit()
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


# ── EHS变更 JSON子记录操作 Routes ──


@ehs_changes_router.post("/ehs-changes/{change_id}/risk-assessments", response_model=ApiResponse, summary="添加风险评估记录")
async def add_risk_assessment_ehs_change(
    change_id: uuid.UUID,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """追加风险评估记录到变更"""
    service = EhsChangeService(db)
    item = await service.add_risk_assessment(change_id, data)
    if not item:
        return ApiResponse(code=404, message="变更不存在")
    await db.commit()
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


@ehs_changes_router.put("/ehs-changes/{change_id}/action-items/{index}", response_model=ApiResponse, summary="更新行动项状态")
async def update_action_item_ehs_change(
    change_id: uuid.UUID,
    index: int,
    status: str = Query(..., description="状态: pending/in_progress/completed"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新行动项状态"""
    service = EhsChangeService(db)
    item = await service.update_action_item(change_id, index, status)
    if not item:
        return ApiResponse(code=400, message="无法更新，变更不存在或索引无效")
    await db.commit()
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


@ehs_changes_router.put("/ehs-changes/{change_id}/pssr-checklist", response_model=ApiResponse, summary="更新PSSR检查清单")
async def update_pssr_checklist_ehs_change(
    change_id: uuid.UUID,
    data: list[dict],
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新PSSR检查清单"""
    service = EhsChangeService(db)
    item = await service.update_pssr_checklist(change_id, data)
    if not item:
        return ApiResponse(code=404, message="变更不存在")
    await db.commit()
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


@ehs_changes_router.put("/ehs-changes/{change_id}/verification", response_model=ApiResponse, summary="提交变更验证数据")
async def submit_verification_ehs_change(
    change_id: uuid.UUID,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """提交变更验证数据"""
    service = EhsChangeService(db)
    item = await service.submit_verification(change_id, data)
    if not item:
        return ApiResponse(code=404, message="变更不存在")
    await db.commit()
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


