"""Safety API — daily_risk_reports endpoints."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.schemas import (
    DailyRiskReportCreate,
    DailyRiskReportResponse,
    DailyRiskReportUpdate,
)
from app.modules.safety.service import (
    DailyRiskReportService,
)

daily_risk_reports_router = APIRouter()


@daily_risk_reports_router.get("/daily-risk-reports", response_model=ApiResponse, summary="获取每日风险作业报备列表")
async def get_daily_risk_reports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    department: str | None = None,
    report_date: str | None = Query(None, description="报备日期 (YYYY-MM-DD)"),
    keyword: str | None = None,
    report_type: str | None = Query(None, description="报备类型: regular/non_regular"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取每日风险作业报备列表"""
    service = DailyRiskReportService(db)
    skip = (page - 1) * page_size
    parsed_date = None
    if report_date:
        from datetime import datetime as dt
        parsed_date = dt.fromisoformat(report_date)
    items, total = await service.get_reports(skip, page_size, status, department, parsed_date, keyword, report_type)
    return ApiResponse(
        data=[DailyRiskReportResponse.model_validate(i) for i in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@daily_risk_reports_router.post("/daily-risk-reports", response_model=ApiResponse, summary="创建每日风险作业报备")
async def create_daily_risk_report(
    data: DailyRiskReportCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建每日风险作业报备"""
    service = DailyRiskReportService(db)
    item = await service.create_report(data)
    await db.commit()
    return ApiResponse(data=DailyRiskReportResponse.model_validate(item))


@daily_risk_reports_router.get("/daily-risk-reports/{report_id}", response_model=ApiResponse, summary="获取每日风险作业报备详情")
async def get_daily_risk_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取每日风险作业报备详情"""
    service = DailyRiskReportService(db)
    item = await service.get_report(report_id)
    if not item:
        return ApiResponse(code=404, message="报备不存在")
    return ApiResponse(data=DailyRiskReportResponse.model_validate(item))


@daily_risk_reports_router.put("/daily-risk-reports/{report_id}", response_model=ApiResponse, summary="更新每日风险作业报备")
async def update_daily_risk_report(
    report_id: uuid.UUID,
    data: DailyRiskReportUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新每日风险作业报备"""
    service = DailyRiskReportService(db)
    item = await service.update_report(report_id, data)
    if not item:
        return ApiResponse(code=404, message="报备不存在")
    await db.commit()
    return ApiResponse(data=DailyRiskReportResponse.model_validate(item))


@daily_risk_reports_router.delete("/daily-risk-reports/{report_id}", response_model=ApiResponse, summary="删除每日风险作业报备")
async def delete_daily_risk_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除每日风险作业报备（软删除）"""
    service = DailyRiskReportService(db)
    ok = await service.delete_report(report_id)
    if not ok:
        return ApiResponse(code=404, message="报备不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


@daily_risk_reports_router.post("/daily-risk-reports/{report_id}/submit", response_model=ApiResponse, summary="提交每日风险作业报备")
async def submit_daily_risk_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """提交报备（草稿→已提交）"""
    service = DailyRiskReportService(db)
    item = await service.submit_report(report_id)
    if not item:
        return ApiResponse(code=400, message="无法提交，当前状态不允许")
    await db.commit()
    return ApiResponse(data=DailyRiskReportResponse.model_validate(item))


@daily_risk_reports_router.post("/daily-risk-reports/{report_id}/approve", response_model=ApiResponse, summary="审批每日风险作业报备")
async def approve_daily_risk_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """审批通过报备（已提交→已审批）"""
    service = DailyRiskReportService(db)
    item = await service.approve_report(report_id)
    if not item:
        return ApiResponse(code=400, message="无法审批，当前状态不允许")
    await db.commit()
    return ApiResponse(data=DailyRiskReportResponse.model_validate(item))


@daily_risk_reports_router.post("/daily-risk-reports/{report_id}/reject", response_model=ApiResponse, summary="驳回每日风险作业报备")
async def reject_daily_risk_report(
    report_id: uuid.UUID,
    reason: str = Query(..., description="驳回原因"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """驳回报备（已提交→已驳回）"""
    service = DailyRiskReportService(db)
    item = await service.reject_report(report_id, reason)
    if not item:
        return ApiResponse(code=400, message="无法驳回，当前状态不允许")
    await db.commit()
    return ApiResponse(data=DailyRiskReportResponse.model_validate(item))


