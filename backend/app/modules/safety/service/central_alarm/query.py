"""中控报警直读查询（Agent + API 共用，central-alarm-direct Ticket 05）。

已拍板口径：
- 窗口默认近 7 天（date_from/date_to 可显式放宽，放宽时接受更长响应）；
- workshop/line/post/keyword/date 内存过滤 + alarm_date 倒序 + 内存分页；
- **ai_alarm_type / ai_dimension / ai_pattern 过滤参数静默忽略**，序列化 ai_* 恒 null
  （AI 分析不落盘、每日重跑——历史 AI 字段只在日报生成时内存存在）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from typing import Any

from app.modules.safety.service.central_alarm.reader import (
    CentralAlarmRecordsReader,
    CentralAlarmView,
    day_window,
    week_window,
)

DEFAULT_WINDOW_DAYS = 7


@dataclass
class DirectQueryResult:
    """直读查询结果（内存分页后）。"""

    items: list[CentralAlarmView] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    elapsed_ms: int = 0


def _bj_today() -> date:
    return (datetime.now(UTC) + timedelta(hours=8)).date()


def _window_from_dates(
    date_from: date | None, date_to: date | None,
) -> tuple[datetime, datetime]:
    """显式日期窗口；缺省 = 近 DEFAULT_WINDOW_DAYS 天（北京时间，含今天）。"""
    today = _bj_today()
    start_day = date_from or (today - timedelta(days=DEFAULT_WINDOW_DAYS - 1))
    end_day = date_to or today
    if end_day < start_day:  # 参数倒挂时按单日处理
        start_day = end_day
    start = datetime.combine(start_day, dtime.min, tzinfo=UTC) - timedelta(hours=8)
    end = datetime.combine(end_day + timedelta(days=1), dtime.min, tzinfo=UTC) - timedelta(hours=8)
    return start, end


def _match(
    v: CentralAlarmView,
    *,
    workshop: str | None,
    line: str | None,
    post: str | None,
    keyword: str | None,
) -> bool:
    if workshop and v.workshop != workshop:
        return False
    if line and v.line != line:
        return False
    if post and v.post != post:
        return False
    if keyword:
        kw = keyword.lower()
        hay = f"{v.alarm_description or ''}\n{v.special_note or ''}".lower()
        if kw not in hay:
            return False
    return True


def serialize_view(v: CentralAlarmView) -> dict[str, Any]:
    """视图对象 → API/Agent 序列化 dict（ai_* 恒 null）。"""
    return {
        "id": str(v.id),
        "feishu_record_id": v.feishu_record_id,
        "source": v.source,
        "alarm_date": v.alarm_date.isoformat() if v.alarm_date else None,
        "post": v.post,
        "alarm_description": v.alarm_description,
        "special_note": v.special_note,
        "workshop": v.workshop,
        "line": v.line,
        "ai_alarm_type": v.ai_alarm_type,
        "ai_equipment": v.ai_equipment,
        "ai_pattern": v.ai_pattern,
        "ai_dimension": v.ai_dimension,
        "ai_reason_analysis": v.ai_reason_analysis,
        "ai_rectification_direction": v.ai_rectification_direction,
        "ai_analyzed_at": None,
        "synced_at": None,
        "created_at": None,
    }


async def query_central_alarms_direct(
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    workshop: str | None = None,
    line: str | None = None,
    post: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
    reader: CentralAlarmRecordsReader | None = None,
    # 兼容旧签名：直读模式下静默忽略（AI 不落盘，无过滤数据源）
    ai_alarm_type: str | None = None,
    ai_dimension: str | None = None,
    ai_pattern: str | None = None,
) -> DirectQueryResult:
    """直读查询中控报警记录（默认近 7 天，内存过滤/倒序/分页）。"""
    r = reader
    if r is None:
        from app.modules.safety.service.central_alarm.reader import open_reader

        r = open_reader()
    t0 = time.perf_counter()
    start, end = _window_from_dates(date_from, date_to)
    views = await r.fetch_window_records(start_utc=start, end_utc=end)
    matched = [
        v for v in views
        if _match(v, workshop=workshop, line=line, post=post, keyword=keyword)
    ]
    matched.sort(
        key=lambda v: v.alarm_date or datetime.min.replace(tzinfo=UTC), reverse=True,
    )
    total = len(matched)
    offset = (page - 1) * page_size
    items = matched[offset:offset + page_size]
    elapsed = int((time.perf_counter() - t0) * 1000)
    return DirectQueryResult(
        items=items, total=total, page=page, page_size=page_size,
        elapsed_ms=elapsed,
    )


def _count_by(records: list[CentralAlarmView], attr: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in records:
        v = getattr(r, attr)
        if v is None:
            continue
        out[v] = out.get(v, 0) + 1
    return out


async def get_stats_direct(
    target_date: date | None = None,
    *,
    reader: CentralAlarmRecordsReader | None = None,
) -> dict[str, Any]:
    """直读 KPI：今日/本周报警数 + 分布；total_count 走 search total 免翻页。

    week_ai_analyzed_count 直读恒 0（AI 不落盘；字段保留供前端兼容）。
    """
    from app.modules.safety.service.central_alarm.aggregator import (
        get_natural_week_range,
    )

    r = reader
    if r is None:
        from app.modules.safety.service.central_alarm.reader import open_reader

        r = open_reader()
    target = target_date or _bj_today()
    week_start, week_end = get_natural_week_range(target)

    today_start, today_end = day_window(target)
    week_start_dt, week_end_dt = week_window(week_start, week_end)

    # 性能：只拉一次自然周窗口，今日分布由应用侧裁剪（少一半拉取）
    week_records, total_count = await _gather_week_and_count(
        r, week_start_dt, week_end_dt,
    )
    today_records = [
        v for v in week_records
        if v.alarm_date and today_start <= v.alarm_date < today_end
    ]
    return {
        "date": target.isoformat(),
        "today_total": len(today_records),
        "week_total": len(week_records),
        "total_count": total_count,
        "week_ai_analyzed_count": 0,
        "workshop_distribution": _count_by(week_records, "workshop"),
        "post_distribution": _count_by(week_records, "post"),
        "alarm_type_distribution": _count_by(week_records, "ai_alarm_type"),
        "pattern_distribution": _count_by(week_records, "ai_pattern"),
        "dimension_distribution": _count_by(week_records, "ai_dimension"),
    }


async def _gather_week_and_count(
    r: CentralAlarmRecordsReader,
    week_start: datetime,
    week_end: datetime,
) -> tuple[list[CentralAlarmView], int]:
    import asyncio

    week_records, total_count = await asyncio.gather(
        r.fetch_window_records(start_utc=week_start, end_utc=week_end),
        r.count_total(),
    )
    return week_records, int(total_count)
