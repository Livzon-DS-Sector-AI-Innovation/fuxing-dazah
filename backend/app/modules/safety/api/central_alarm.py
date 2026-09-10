"""Safety API — central_alarm endpoints.

中控报警多表同步（ticket 02）；记录查询/统计（ticket 03）；日报生成（ticket 06）。
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import ApiResponse
from app.modules.safety.models import CentralAlarmRecord
from app.modules.safety.schemas.central_alarm import (
    CentralAlarmDailyReportRequest,
    CentralAlarmStatsOut,
    CentralAlarmSyncResponse,
)
from app.modules.safety.service.central_alarm import CentralAlarmService

logger = logging.getLogger(__name__)

central_alarm_router = APIRouter()


@central_alarm_router.post(
    "/central-alarms/sync",
    response_model=ApiResponse,
    summary="手动触发中控报警 Bitable 多表全量同步",
)
async def sync_from_bitable(db: AsyncSession = Depends(get_db)):
    """从飞书中控报警 Base 全量同步 15 张表（each 表 upsert + 软删对齐）。

    Bitable/网络异常降级：返回 HTTP 200 + body code=500 + 错误 message，不抛 500。
    """
    service = CentralAlarmService(db)
    try:
        synced, soft_deleted = await service.sync_from_bitable()
        return ApiResponse(
            data=CentralAlarmSyncResponse(
                synced_count=synced, soft_deleted_count=soft_deleted,
            ).model_dump(),
            message=f"同步完成，处理 {synced} 条，软删除 {soft_deleted} 条",
        )
    except Exception as exc:
        await db.rollback()
        logger.exception("中控报警 Bitable 同步失败")
        return ApiResponse(code=500, message=f"同步失败: {exc}", data=None)


# ── 记录查询 ──


@central_alarm_router.get(
    "/central-alarms/records",
    response_model=ApiResponse,
    summary="分页查询中控报警记录（含 AI 分析列）",
)
async def get_records(
    date_from: date | None = Query(None, description="起始日期（报警时间，含当天）"),
    date_to: date | None = Query(None, description="截止日期（报警时间，含当天）"),
    workshop: str | None = Query(None, description="车间（精确匹配）"),
    line: str | None = Query(None, description="产线（精确匹配）"),
    post: str | None = Query(None, description="岗位（精确匹配）"),
    ai_alarm_type: str | None = Query(None, description="结构化报警类型（精确匹配）"),
    ai_dimension: str | None = Query(
        None, description="AI 维度（process/operation/equipment/other）"
    ),
    ai_pattern: str | None = Query(
        None, description="异常模式（normal_transient/repeated/false_alarm/anomalous）"
    ),
    keyword: str | None = Query(None, description="关键词（报警情况说明/特殊说明模糊匹配）"),
    page: int = Query(1, ge=1, description="页码（从 1 开始）"),
    page_size: int = Query(20, ge=1, le=200, description="每页条数"),
    db: AsyncSession = Depends(get_db),
):
    """分页查询中控报警记录（默认过滤软删；按报警日期倒序）。"""
    service = CentralAlarmService(db)
    items, total = await service.get_records(
        date_from=date_from, date_to=date_to, workshop=workshop, line=line,
        post=post, ai_alarm_type=ai_alarm_type, ai_dimension=ai_dimension,
        ai_pattern=ai_pattern, keyword=keyword, page=page, page_size=page_size,
    )
    return ApiResponse(
        data=[_serialize(r) for r in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


# ── 统计 ──


@central_alarm_router.get(
    "/central-alarms/stats",
    response_model=ApiResponse,
    summary="获取中控报警 KPI（今日/本周报警数 + 分布）",
)
async def get_stats(
    target_date: date | None = Query(None, description="目标日期，默认今天（北京时间）"),
    db: AsyncSession = Depends(get_db),
):
    """KPI：今日/本周报警数 + 车间/岗位/报警类型/异常模式/维度分布（dict[str,int]）。"""
    service = CentralAlarmService(db)
    stats = await service.get_stats(target_date)
    return ApiResponse(data=CentralAlarmStatsOut(**stats).model_dump())


# ── 日报生成 ──


@central_alarm_router.post(
    "/central-alarms/daily-report/generate",
    response_model=ApiResponse,
    summary="生成并推送中控报警日报",
)
async def generate_daily_report(
    data: CentralAlarmDailyReportRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    """生成当日中控报警分析报告（聚合 → AI 分析回写 → 渲染 → 推送）。

    body {target_date?} 可空，默认今天（北京时间）；channel="web"。
    AI/推送失败由 service 降级（不抛 500，返回纯数据汇总 markdown）。
    """
    service = CentralAlarmService(db)
    result = await service.generate_daily_report(
        target_date=data.target_date if data else None,
        push=True, channel="web",
    )
    return ApiResponse(data=result.model_dump(mode="json"))


def _serialize(r: CentralAlarmRecord) -> dict:
    """轻量序列化（含 AI 分析列）。"""
    return {
        "id": str(r.id),
        "feishu_record_id": r.feishu_record_id,
        "source": r.source,
        "alarm_date": r.alarm_date.isoformat() if r.alarm_date else None,
        "post": r.post,
        "alarm_description": r.alarm_description,
        "special_note": r.special_note,
        "workshop": r.workshop,
        "line": r.line,
        "ai_alarm_type": r.ai_alarm_type,
        "ai_equipment": r.ai_equipment,
        "ai_pattern": r.ai_pattern,
        "ai_dimension": r.ai_dimension,
        "ai_reason_analysis": r.ai_reason_analysis,
        "ai_rectification_direction": r.ai_rectification_direction,
        "ai_analyzed_at": r.ai_analyzed_at.isoformat() if r.ai_analyzed_at else None,
        "synced_at": r.synced_at.isoformat() if r.synced_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
