"""Safety API — ehs_changes endpoints（3.0 只读台账口径）.

仅保留台账查询类端点：列表 / 统计 / 详情。
平台状态机操作端点（创建/更新/删除/提交/审批/驳回/实施/投用/关闭/取消/
风险评估/行动项/PSSR/验证/手动 AI 审核）已随 Web 退役——业务在飞书多维
表格，AI 审核由 bitable handler 以 channel="system" 自动触发（service 层不动）。
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.schemas import (
    EhsChangeResponse,
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
    source: str | None = Query(None, description="数据来源: manual/bitable"),
    feishu_table_id: str | None = Query(None, description="飞书表类型: approval/acceptance"),
    sort_by: str | None = Query(None, description="排序字段: expected_start/acceptance_date/created_at"),
    sort_order: str = Query("desc", description="排序方向: desc/asc"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取EHS变更列表，支持多条件筛选"""
    service = EhsChangeService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_ehs_changes(
        skip, page_size, status, change_type, change_grade, change_duration,
        department, keyword, source, feishu_table_id, sort_by, sort_order,
    )
    return ApiResponse(
        data=[EhsChangeResponse.model_validate(i) for i in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@ehs_changes_router.get("/ehs-changes/stats", response_model=ApiResponse, summary="获取EHS变更统计")
async def get_ehs_changes_stats(
    feishu_table_id: str | None = Query(None, description="飞书表类型: approval/acceptance"),
    source: str | None = Query(None, description="数据来源: manual/bitable"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """EHS 变更统计（KPI 卡）：total + status 分组 + AI 总体结论计数"""
    service = EhsChangeService(db)
    data = await service.get_ehs_change_stats(feishu_table_id, source)
    return ApiResponse(data=data)


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
