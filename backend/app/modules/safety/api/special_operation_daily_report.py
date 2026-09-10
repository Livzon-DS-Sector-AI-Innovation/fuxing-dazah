"""Safety API — special_operation_daily_report endpoints.

日报生成、同步、统计。数据基于 SpecialOperationReport（source=bitable）。
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import ApiResponse
from app.modules.safety.models import SpecialOperationReport
from app.modules.safety.schemas import (
    DailyReportRequest,
    DailyReportStats,
)
from app.modules.safety.service.special_operation_daily_report import (
    SpecialOperationDailyReportService,
)

special_operation_daily_report_router = APIRouter()


# ── 同步 ──

@special_operation_daily_report_router.post(
    "/special-operation-daily-report/sync",
    response_model=ApiResponse,
    summary="手动触发 Bitable 数据同步",
)
async def sync_from_bitable(db: AsyncSession = Depends(get_db)):
    """从飞书 Bitable 同步特殊作业数据到 SpecialOperationReport。"""
    service = SpecialOperationDailyReportService(db)
    try:
        synced = await service.sync_from_bitable()
        await db.commit()
        return ApiResponse(data={"synced_count": synced}, message=f"同步完成，共处理 {synced} 条记录")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"同步失败: {exc}")


# ── 日报生成与推送 ──

@special_operation_daily_report_router.post(
    "/special-operation-daily-report/generate",
    response_model=ApiResponse,
    summary="生成并推送特殊作业日报",
)
async def generate_daily_report(
    data: DailyReportRequest = None,
    db: AsyncSession = Depends(get_db),
):
    """手动触发：同步 → 风险分析 → 生成日报 → 推送飞书群。"""
    service = SpecialOperationDailyReportService(db)
    try:
        # 先同步最新数据
        await service.sync_from_bitable()
        # 再生成日报
        result = await service.generate_and_push(
            target_date=data.target_date if data else None,
            mode=data.mode if data else "today",
        )
        await db.commit()
        return ApiResponse(data=result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"日报生成失败: {exc}")


# ── 统计 ──

@special_operation_daily_report_router.get(
    "/special-operation-daily-report/stats",
    response_model=ApiResponse,
    summary="获取指定日期的日报风险统计",
)
async def get_daily_stats(
    target_date: date | None = Query(None, description="目标日期，默认今天"),
    db: AsyncSession = Depends(get_db),
):
    service = SpecialOperationDailyReportService(db)
    stats = await service.get_stats(target_date)
    return ApiResponse(data=DailyReportStats(**stats))


# ── 记录查询 ──

@special_operation_daily_report_router.get(
    "/special-operation-daily-report/records",
    response_model=ApiResponse,
    summary="获取特殊作业日报记录列表",
)
async def get_daily_records(
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """分页查询 Bitable 同步的特殊作业记录（含风险判定结果）。"""
    from datetime import datetime, timedelta

    from sqlalchemy import func

    stmt = select(SpecialOperationReport).where(
        SpecialOperationReport.source == "bitable",
        SpecialOperationReport.is_deleted == False,  # noqa: E712
    )
    cnt_stmt = select(func.count(SpecialOperationReport.id)).where(
        SpecialOperationReport.source == "bitable",
        SpecialOperationReport.is_deleted == False,  # noqa: E712
    )
    if date_from:
        dt_from = datetime.combine(date_from, datetime.min.time())
        stmt = stmt.where(SpecialOperationReport.planned_start_time >= dt_from)
        cnt_stmt = cnt_stmt.where(SpecialOperationReport.planned_start_time >= dt_from)
    if date_to:
        dt_to = datetime.combine(date_to + timedelta(days=1), datetime.min.time())
        stmt = stmt.where(SpecialOperationReport.planned_start_time < dt_to)
        cnt_stmt = cnt_stmt.where(SpecialOperationReport.planned_start_time < dt_to)

    total = (await db.execute(cnt_stmt)).scalar() or 0
    offset = (page - 1) * page_size
    items = (await db.execute(
        stmt.order_by(SpecialOperationReport.planned_start_time.desc()).offset(offset).limit(page_size)
    )).scalars().all()

    return ApiResponse(
        data=[_serialize(r) for r in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


def _serialize(r: SpecialOperationReport) -> dict:
    """轻量序列化，避免 Pydantic model_validate 的字段缺失问题。"""
    return {
        "id": str(r.id),
        "source": r.source,
        "feishu_record_id": r.feishu_record_id,
        "department": r.department,
        "location": r.location,
        "operation_type": r.operation_type,
        "operation_level": r.operation_level,
        "work_description": r.work_description,
        "work_duration_hours": r.work_duration_hours,
        "personnel_type": r.personnel_type,
        "planned_start_time": r.planned_start_time.isoformat() if r.planned_start_time else None,
        "planned_end_time": r.planned_end_time.isoformat() if r.planned_end_time else None,
        "daily_risk_level": r.daily_risk_level,
        "daily_risk_reason": r.daily_risk_reason,
        "inferred_operation_types": r.inferred_operation_types,
        "is_excluded": r.is_excluded,
        "exclusion_reason": r.exclusion_reason,
        "daily_report_date": r.daily_report_date.isoformat() if r.daily_report_date else None,
        "approval_no": r.approval_no,
        "report_type": r.report_type,
        "is_weekend_holiday": r.is_weekend_holiday,
        "status": r.status,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
