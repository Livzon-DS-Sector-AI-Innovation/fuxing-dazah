"""Safety API — cert_warnings endpoints（持证到期预警）。

对齐 backend-design.md §6：
- GET 列表（page/page_size/status/department/category/days 筛选 + 分页，引擎派生展示）；
- GET summary 汇总（6 档人数 + by_category + by_event）；
- POST renew 回填闭环（特种作业证→next_review_date；监护人证→renewed_date）；
- 业务失败返回 ApiResponse(code=400/404)（HTTP 200），与 oh_followups 一致。

api.py 只做 HTTP 层（接参、注入、调 service、返回），不写业务逻辑（CLAUDE.md）。
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.schemas import (
    CertCategory,
    CertWarningDetail,
    RenewRequest,
    WarningLevel,
)
from app.modules.safety.service import CertWarningService

cert_warnings_router = APIRouter()


@cert_warnings_router.get(
    "/cert-warnings", response_model=ApiResponse, summary="持证到期预警明细列表（筛选 + 分页）"
)
async def get_cert_warnings(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status_level: WarningLevel | None = Query(None, description="预警状态（6 档）"),
    department: str | None = Query(None, description="部门"),
    cert_category: CertCategory | None = Query(None, description="证件类别"),
    days_within: int | None = Query(None, ge=0, description="剩余天数 ≤ N"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """到期明细列表：状态/部门/类别筛选 + 分页（预警等级由引擎派生）"""
    service = CertWarningService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_warnings(
        skip=skip,
        limit=page_size,
        status_level=status_level.value if status_level else None,
        department=department,
        cert_category=cert_category.value if cert_category else None,
        days_within=days_within,
    )
    return ApiResponse(
        data=items,
        meta={"page": page, "page_size": page_size, "total": total},
    )


@cert_warnings_router.get(
    "/cert-warnings/summary", response_model=ApiResponse, summary="持证到期预警汇总"
)
async def get_cert_warnings_summary(
    department: str | None = Query(None, description="部门"),
    cert_category: CertCategory | None = Query(None, description="证件类别"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """汇总：6 档人数 + by_category + by_event"""
    service = CertWarningService(db)
    summary = await service.get_summary(
        department=department,
        cert_category=cert_category.value if cert_category else None,
    )
    return ApiResponse(data=summary)


@cert_warnings_router.post(
    "/cert-warnings/{cert_id}/renew",
    response_model=ApiResponse,
    summary="回填复审/换证结果（闭环，进入下一证件周期）",
)
async def renew_cert_warning(
    cert_id: uuid.UUID,
    data: RenewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """回填闭环：特种作业证→next_review_date；监护人证→renewed_date"""
    service = CertWarningService(db)
    try:
        item = await service.renew(
            cert_id,
            data,
            user_id=current_user.id if current_user else None,
        )
    except ValueError as e:
        return ApiResponse(code=400, message=str(e))
    if not item:
        return ApiResponse(code=404, message="持证记录不存在")
    await db.commit()
    return ApiResponse(data=CertWarningDetail.model_validate(item))
