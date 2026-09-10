"""Safety API — fire_alarm endpoints.

消防报警同步（ticket 02）；记录查询/统计（ticket 03）；日报/周报生成（ticket 07）。
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import ApiResponse
from app.modules.safety.models import FireAlarmRecord
from app.modules.safety.schemas.fire_alarm import (
    FireAlarmDailyReportRequest,
    FireAlarmStatsOut,
    FireAlarmSyncResponse,
    FireAlarmWeeklyReportRequest,
)
from app.modules.safety.service.fire_alarm import FireAlarmService

logger = logging.getLogger(__name__)

fire_alarm_router = APIRouter()


@fire_alarm_router.post(
    "/fire-alarms/sync",
    response_model=ApiResponse,
    summary="手动触发消防报警 Bitable 全量同步",
)
async def sync_from_bitable(db: AsyncSession = Depends(get_db)):
    """从飞书消防数据多维表格全量同步报警记录（upsert + 软删对齐）。

    Bitable/网络异常降级：返回 HTTP 200 + body code=500 + 错误 message，不抛 500。
    """
    service = FireAlarmService(db)
    try:
        synced, soft_deleted = await service.sync_from_bitable()
        return ApiResponse(
            data=FireAlarmSyncResponse(
                synced_count=synced, soft_deleted_count=soft_deleted,
            ).model_dump(),
            message=f"同步完成，处理 {synced} 条，软删除 {soft_deleted} 条",
        )
    except Exception as exc:
        await db.rollback()
        logger.exception("消防报警 Bitable 同步失败")
        return ApiResponse(code=500, message=f"同步失败: {exc}", data=None)


# ── 记录查询 ──


@fire_alarm_router.get(
    "/fire-alarms/records",
    response_model=ApiResponse,
    summary="分页查询消防报警记录（含 AI 分析列）",
)
async def get_records(
    date_from: date | None = Query(None, description="起始日期（报警时间，含当天）"),
    date_to: date | None = Query(None, description="截止日期（报警时间，含当天）"),
    department: str | None = Query(None, description="报警部门（精确匹配）"),
    alarm_type: str | None = Query(None, description="报警类型（精确匹配）"),
    alarm_nature: str | None = Query(None, description="报警性质（精确匹配）"),
    ai_dimension: str | None = Query(
        None, description="AI 维度（process/operation/equipment/other）"
    ),
    keyword: str | None = Query(None, description="关键词（报警部位/原因模糊匹配）"),
    page: int = Query(1, ge=1, description="页码（从 1 开始）"),
    page_size: int = Query(20, ge=1, le=200, description="每页条数"),
    db: AsyncSession = Depends(get_db),
):
    """分页查询报警记录（默认过滤软删；按报警时间倒序）。"""
    service = FireAlarmService(db)
    items, total = await service.get_records(
        date_from=date_from, date_to=date_to, department=department,
        alarm_type=alarm_type, alarm_nature=alarm_nature,
        ai_dimension=ai_dimension, keyword=keyword,
        page=page, page_size=page_size,
    )
    return ApiResponse(
        data=[_serialize(r) for r in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


# ── 统计 ──


@fire_alarm_router.get(
    "/fire-alarms/stats",
    response_model=ApiResponse,
    summary="获取消防报警 KPI（今日/本周报警数 + 分布）",
)
async def get_stats(
    target_date: date | None = Query(None, description="目标日期，默认今天（北京时间）"),
    db: AsyncSession = Depends(get_db),
):
    """KPI：今日/本周报警数 + 性质/类型/维度/部门分布（dict[str,int]）。"""
    service = FireAlarmService(db)
    stats = await service.get_stats(target_date)
    return ApiResponse(data=FireAlarmStatsOut(**stats).model_dump())


# ── 日报生成 ──


@fire_alarm_router.post(
    "/fire-alarms/daily-report/generate",
    response_model=ApiResponse,
    summary="生成并推送消防报警日报",
)
async def generate_daily_report(
    data: FireAlarmDailyReportRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    """生成当日消防报警分析报告（聚合 → AI 分析回写 → 渲染 → 推送）。

    body {target_date?} 可空，默认今天（北京时间）；channel="web"。
    AI/推送失败由 service 降级（不抛 500，返回纯数据汇总 markdown）。
    """
    service = FireAlarmService(db)
    result = await service.generate_daily_report(
        target_date=data.target_date if data else None,
        push=True, channel="web",
    )
    return ApiResponse(data=result.model_dump(mode="json"))


# ── 周报生成 ──


@fire_alarm_router.post(
    "/fire-alarms/weekly-report/generate",
    response_model=ApiResponse,
    summary="生成并推送消防报警周报",
)
async def generate_weekly_report(
    data: FireAlarmWeeklyReportRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    """生成自然周（周一~周日）消防报警分析报告（复用记录上的日分析结果）。

    body {week_end?} 可空，默认今天（北京时间）所在自然周；channel="web"。
    AI/推送失败由 service 降级（不抛 500）。
    """
    service = FireAlarmService(db)
    result = await service.generate_weekly_report(
        week_end=data.week_end if data else None,
        push=True, channel="web",
    )
    return ApiResponse(data=result.model_dump(mode="json"))


def _serialize(r: FireAlarmRecord) -> dict:
    """轻量序列化（参照 special_op _serialize，避免 Pydantic model_validate 字段缺失）。"""
    return {
        "id": str(r.id),
        "feishu_record_id": r.feishu_record_id,
        "source": r.source,
        "alarm_time": r.alarm_time.isoformat() if r.alarm_time else None,
        "alarm_type": r.alarm_type,
        "department": r.department,
        "department_leader_name": r.department_leader_name,
        "building": r.building,
        "location": r.location,
        "alarm_nature": r.alarm_nature,
        "cause_category": r.cause_category,
        "cause_description": r.cause_description,
        "ai_dimension": r.ai_dimension,
        "ai_reason_analysis": r.ai_reason_analysis,
        "ai_rectification_direction": r.ai_rectification_direction,
        "ai_analyzed_at": r.ai_analyzed_at.isoformat() if r.ai_analyzed_at else None,
        "synced_at": r.synced_at.isoformat() if r.synced_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
