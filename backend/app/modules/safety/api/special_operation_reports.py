"""Safety API — special_operation_reports endpoints."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.schemas import (
    LedgerExportRequest,
    SetCriticalRequest,
    SpecialOperationLedgerStats,
    SpecialOperationReportCreate,
    SpecialOperationReportResponse,
    SpecialOperationReportUpdate,
)
from app.modules.safety.service import (
    SpecialOperationReportService,
)

special_operation_reports_router = APIRouter()


@special_operation_reports_router.get("/special-operation-reports", response_model=ApiResponse, summary="获取特殊作业报备列表")
async def get_special_operation_reports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    operation_type: str | None = None,
    operation_level: str | None = None,
    risk_level: str | None = None,
    department: str | None = None,
    date_from: str | None = Query(None, description="计划开始日期起 (YYYY-MM-DD)"),
    date_to: str | None = Query(None, description="计划结束日期止 (YYYY-MM-DD)"),
    keyword: str | None = None,
    is_critical: bool | None = Query(None, description="是否关键作业"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取特殊作业报备列表"""
    service = SpecialOperationReportService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_reports(
        skip, page_size, status, operation_type, operation_level,
        risk_level, department, date_from, date_to, keyword, is_critical,
    )
    return ApiResponse(
        data=[SpecialOperationReportResponse.model_validate(i) for i in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@special_operation_reports_router.post("/special-operation-reports", response_model=ApiResponse, summary="创建特殊作业报备")
async def create_special_operation_report(
    data: SpecialOperationReportCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建特殊作业报备"""
    service = SpecialOperationReportService(db)
    item = await service.create_report(data)
    await db.commit()
    return ApiResponse(data=SpecialOperationReportResponse.model_validate(item))


@special_operation_reports_router.get("/special-operation-reports/{report_id}", response_model=ApiResponse, summary="获取特殊作业报备详情")
async def get_special_operation_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取特殊作业报备详情"""
    service = SpecialOperationReportService(db)
    item = await service.get_report(report_id)
    if not item:
        return ApiResponse(code=404, message="报备不存在")
    return ApiResponse(data=SpecialOperationReportResponse.model_validate(item))


@special_operation_reports_router.put("/special-operation-reports/{report_id}", response_model=ApiResponse, summary="更新特殊作业报备")
async def update_special_operation_report(
    report_id: uuid.UUID,
    data: SpecialOperationReportUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新特殊作业报备"""
    service = SpecialOperationReportService(db)
    item = await service.update_report(report_id, data)
    if not item:
        return ApiResponse(code=404, message="报备不存在")
    await db.commit()
    return ApiResponse(data=SpecialOperationReportResponse.model_validate(item))


@special_operation_reports_router.delete("/special-operation-reports/{report_id}", response_model=ApiResponse, summary="删除特殊作业报备")
async def delete_special_operation_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除特殊作业报备（软删除）"""
    service = SpecialOperationReportService(db)
    ok = await service.delete_report(report_id)
    if not ok:
        return ApiResponse(code=404, message="报备不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


@special_operation_reports_router.post("/special-operation-reports/{report_id}/submit", response_model=ApiResponse, summary="提交特殊作业报备")
async def submit_special_operation_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """提交报备（草稿→已提交）"""
    service = SpecialOperationReportService(db)
    item = await service.submit_report(report_id)
    if not item:
        return ApiResponse(code=400, message="无法提交，当前状态不允许")
    await db.commit()
    return ApiResponse(data=SpecialOperationReportResponse.model_validate(item))


@special_operation_reports_router.post("/special-operation-reports/{report_id}/approve", response_model=ApiResponse, summary="审批特殊作业报备")
async def approve_special_operation_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """审批通过报备（已提交→已审批）"""
    service = SpecialOperationReportService(db)
    item = await service.approve_report(report_id)
    if not item:
        return ApiResponse(code=400, message="无法审批，当前状态不允许")
    await db.commit()
    return ApiResponse(data=SpecialOperationReportResponse.model_validate(item))


@special_operation_reports_router.post("/special-operation-reports/{report_id}/reject", response_model=ApiResponse, summary="驳回特殊作业报备")
async def reject_special_operation_report(
    report_id: uuid.UUID,
    reason: str = Query(..., description="驳回原因"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """驳回报备（已提交→已驳回）"""
    service = SpecialOperationReportService(db)
    item = await service.reject_report(report_id, reason)
    if not item:
        return ApiResponse(code=400, message="无法驳回，当前状态不允许")
    await db.commit()
    return ApiResponse(data=SpecialOperationReportResponse.model_validate(item))


@special_operation_reports_router.put(
    "/special-operation-reports/{report_id}/critical",
    response_model=ApiResponse,
    summary="手动设置关键作业标记",
)
async def set_special_operation_report_critical(
    report_id: uuid.UUID,
    data: SetCriticalRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """手动修改特殊作业报备的关键作业标记"""
    service = SpecialOperationReportService(db)
    updated_by = current_user.name if current_user else None
    item = await service.set_critical_manual(
        report_id, data.is_critical, data.reason, updated_by
    )
    if not item:
        return ApiResponse(code=404, message="报备不存在")
    await db.commit()
    return ApiResponse(data=SpecialOperationReportResponse.model_validate(item))


# ==================== 特殊作业台账 Routes ====================


@special_operation_reports_router.get(
    "/special-operation-ledger",
    response_model=ApiResponse,
    summary="获取特殊作业台账列表",
)
async def get_special_operation_ledger(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    operation_type: str | None = None,
    operation_level: str | None = None,
    risk_level: str | None = None,
    department: str | None = None,
    date_from: str | None = Query(None, description="计划开始日期起 (YYYY-MM-DD)"),
    date_to: str | None = Query(None, description="计划结束日期止 (YYYY-MM-DD)"),
    keyword: str | None = None,
    is_critical: bool | None = Query(None, description="是否关键作业"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取特殊作业台账列表（审批中 + 已审批的报备记录）"""
    service = SpecialOperationReportService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_ledger(
        skip=skip,
        limit=page_size,
        operation_type=operation_type,
        operation_level=operation_level,
        risk_level=risk_level,
        department=department,
        date_from=date_from,
        date_to=date_to,
        keyword=keyword,
        is_critical=is_critical,
    )
    return ApiResponse(
        data=[SpecialOperationReportResponse.model_validate(i) for i in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@special_operation_reports_router.get(
    "/special-operation-ledger/stats",
    response_model=ApiResponse,
    summary="获取特殊作业台账统计",
)
async def get_special_operation_ledger_stats(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """按作业类型统计台账数量和关键作业数量"""
    service = SpecialOperationReportService(db)
    stats = await service.get_ledger_stats()
    return ApiResponse(
        data=[SpecialOperationLedgerStats(**s) for s in stats]
    )


@special_operation_reports_router.post(
    "/special-operation-ledger/parse-query",
    response_model=ApiResponse,
    summary="AI 解析自然语言筛选条件",
)
async def parse_ledger_query(
    data: LedgerExportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """使用 AI 将自然语言查询解析为结构化的台账筛选条件"""
    service = SpecialOperationReportService(db)
    if not data.natural_query:
        return ApiResponse(code=400, message="请提供自然语言查询")
    result = await service.parse_natural_query(data.natural_query)
    return ApiResponse(data=result)


@special_operation_reports_router.post(
    "/special-operation-ledger/export",
    summary="导出特殊作业台账 Excel",
)
async def export_special_operation_ledger(
    data: LedgerExportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """导出特殊作业台账为 Excel 文件，支持 AI 自然语言筛选"""
    from fastapi.responses import Response

    service = SpecialOperationReportService(db)

    # 如果有自然语言查询，先用 AI 解析
    filters: dict = {}
    if data.natural_query:
        parsed = await service.parse_natural_query(data.natural_query)
        filters = {k: v for k, v in parsed.items() if k != "explanation"}
    else:
        filters = {
            k: v for k, v in {
                "operation_type": data.operation_type,
                "operation_level": data.operation_level,
                "risk_level": data.risk_level,
                "department": data.department,
                "date_from": data.date_from,
                "date_to": data.date_to,
                "keyword": data.keyword,
                "is_critical": data.is_critical,
            }.items() if v is not None
        }

    excel_bytes = await service.export_ledger_excel(**filters)

    filename = f"特殊作业台账_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


