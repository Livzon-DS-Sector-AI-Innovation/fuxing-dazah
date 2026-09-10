"""Safety API — key_risk_operation_reports endpoints（只读，Bitable 同步）."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.schemas import (
    KeyRiskOperationExportRequest,
    KeyRiskOperationLedgerStats,
    KeyRiskOperationReportResponse,
)
from app.modules.safety.service import KeyRiskOperationReportService

key_risk_operation_reports_router = APIRouter()


@key_risk_operation_reports_router.get(
    "/key-risk-operation-reports",
    response_model=ApiResponse,
    summary="获取关键风险作业报备列表",
)
async def get_key_risk_operation_reports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    department: str | None = None,
    area: str | None = None,
    operation_content: str | None = None,
    apply_status: str | None = Query(None, description="申请状态: 已通过/审批中/已拒绝/…"),
    date_from: str | None = Query(None, description="作业开始日期起 (YYYY-MM-DD)"),
    date_to: str | None = Query(None, description="作业开始日期止 (YYYY-MM-DD)"),
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取关键风险作业报备列表（只读）"""
    service = KeyRiskOperationReportService(db)
    skip = (page - 1) * page_size
    parsed_from = date.fromisoformat(date_from) if date_from else None
    parsed_to = date.fromisoformat(date_to) if date_to else None
    items, total = await service.get_reports(
        skip, page_size, department, area, operation_content,
        apply_status, parsed_from, parsed_to, keyword,
    )
    return ApiResponse(
        data=[KeyRiskOperationReportResponse.model_validate(i) for i in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@key_risk_operation_reports_router.get(
    "/key-risk-operation-reports/stats",
    response_model=ApiResponse,
    summary="获取关键风险作业统计",
)
async def get_key_risk_operation_stats(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取关键风险作业 KPI 统计（今日/审批中/本月/累计）"""
    service = KeyRiskOperationReportService(db)
    stats = await service.get_stats()
    return ApiResponse(data=KeyRiskOperationLedgerStats(**stats))


@key_risk_operation_reports_router.post(
    "/key-risk-operation-reports/sync",
    response_model=ApiResponse,
    summary="手动同步关键风险作业 Bitable",
)
async def sync_key_risk_operation_reports(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """从飞书 Bitable 全量同步关键风险作业报备"""
    service = KeyRiskOperationReportService(db)
    stats = await service.sync_from_bitable()
    return ApiResponse(data=stats)


@key_risk_operation_reports_router.post(
    "/key-risk-operation-reports/export",
    summary="导出关键风险作业台账 Excel",
)
async def export_key_risk_operation_reports(
    data: KeyRiskOperationExportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """导出关键风险作业台账为 Excel 文件"""
    from datetime import datetime

    from fastapi.responses import Response

    service = KeyRiskOperationReportService(db)
    parsed_from = date.fromisoformat(data.date_from) if data.date_from else None
    parsed_to = date.fromisoformat(data.date_to) if data.date_to else None
    excel_bytes = await service.export_excel(
        department=data.department,
        area=data.area,
        operation_content=data.operation_content,
        apply_status=data.apply_status,
        date_from=parsed_from,
        date_to=parsed_to,
        keyword=data.keyword,
    )
    filename = f"关键风险作业台账_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@key_risk_operation_reports_router.get(
    "/key-risk-operation-reports/{report_id}",
    response_model=ApiResponse,
    summary="获取关键风险作业报备详情",
)
async def get_key_risk_operation_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取关键风险作业报备详情"""
    service = KeyRiskOperationReportService(db)
    item = await service.get_report(report_id)
    if not item:
        return ApiResponse(code=404, message="报备不存在")
    return ApiResponse(data=KeyRiskOperationReportResponse.model_validate(item))
