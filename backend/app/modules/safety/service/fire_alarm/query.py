"""消防报警 Agent 查询：直读 Bitable + 应用侧过滤 + 应用侧分页。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.modules.safety.service.bitable_direct import filters as bd_filters
from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.fire_alarm import contract, reader

F_ALARM_TIME = "报警时间"
F_ALARM_TYPE = "报警类型"
F_ALARM_NATURE = "报警性质"

# 部门字段说明（2026-09-17 票据 08 实测）：
# 1. 该表没有「报警部门」独立列（bitable_config registry 里的映射已过时）；
# 2. 部门实际来自「报警部门负责人.部门」，它是多选(type=4)，Bitable 的多选
#    不支持 contains 过滤（实测 code=1254018 InvalidFilter）；
# 3. 用 is 精确匹配会漏掉「五部」这类部分部门名。
# 因此部门不下推服务端，统一在应用侧做子串匹配：窗口内记录量级为数百条，
# 全量拉回再过滤的成本可忽略，且语义与镜像链路的模糊匹配一致。

MAX_QUERY_DAYS = 31
DEFAULT_QUERY_DAYS = 30
FETCH_PAGE_SIZE = 500
MAX_PAGE_SIZE = 100


def _bj_today() -> date:
    return (datetime.now(UTC) + timedelta(hours=8)).date()


def _resolve_window(
    date_from: date | None, date_to: date | None
) -> tuple[date, date]:
    """解析查询日期窗口；两者都为空时默认最近 30 天。"""
    today = _bj_today()
    if date_from is None and date_to is None:
        return today - timedelta(days=DEFAULT_QUERY_DAYS - 1), today
    if date_from is not None and date_to is not None:
        return date_from, date_to
    if date_from is not None:
        return date_from, date_from
    assert date_to is not None
    return date_to, date_to


def _view_to_dict(view: reader.FireAlarmView) -> dict[str, Any]:
    """视图对象 -> Agent 返回条目；id 为飞书记录 ID，并保留 feishu_record_id。"""
    return {
        "id": view.id,
        "feishu_record_id": view.feishu_record_id,
        "source": view.source,
        "alarm_time": view.alarm_time.isoformat() if view.alarm_time else None,
        "alarm_type": view.alarm_type,
        "department": view.department,
        "department_leader_name": view.department_leader_name,
        "building": view.building,
        "location": view.location,
        "alarm_nature": view.alarm_nature,
        "cause_category": view.cause_category,
        "cause_description": view.cause_description,
        "ai_dimension": view.ai_dimension,
        "ai_reason_analysis": view.ai_reason_analysis,
        "ai_rectification_direction": view.ai_rectification_direction,
        "ai_analyzed_at": (
            view.ai_analyzed_at.isoformat() if view.ai_analyzed_at else None
        ),
        "synced_at": view.synced_at.isoformat() if view.synced_at else None,
    }


def _matches(
    view: reader.FireAlarmView,
    *,
    department: str | None,
    alarm_type: str | None,
    alarm_nature: str | None,
    ai_dimension: str | None,
    keyword: str | None,
) -> bool:
    if department and department not in (view.department or ""):
        return False
    if alarm_type and view.alarm_type != alarm_type:
        return False
    if alarm_nature and view.alarm_nature != alarm_nature:
        return False
    if ai_dimension and view.ai_dimension != ai_dimension:
        return False
    if keyword:
        kw = keyword.lower()
        haystacks = (
            (view.location or "").lower(),
            (view.cause_description or "").lower(),
        )
        if not any(kw in hay for hay in haystacks):
            return False
    return True


async def query_fire_alarms_direct(
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    department: str | None = None,
    alarm_type: str | None = None,
    alarm_nature: str | None = None,
    ai_dimension: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
    client: bd_reader.BitableRecordsReader | None = None,
) -> dict[str, Any]:
    """直读消防 Bitable 并返回 Agent 工具结构。

    - 日期范围、类型、性质、AI 维度下推服务端；部门在应用侧做子串匹配；
    - 关键词在应用侧匹配报警部位 / 具体报警原因；
    - 分页在应用侧完成；
    - 未给日期范围时默认最近 30 天；范围超过 31 天返回明确错误。
    """
    start_date, end_date = _resolve_window(date_from, date_to)
    if start_date > end_date:
        return {"success": False, "error": "起始日期不能晚于结束日期"}
    span_days = (end_date - start_date).days + 1
    if span_days > MAX_QUERY_DAYS:
        return {
            "success": False,
            "error": f"查询范围 {span_days} 天超过上限 {MAX_QUERY_DAYS} 天，请缩小范围",
        }

    start_dt = bd_filters.bjt_day_start(start_date)
    end_dt = bd_filters.bjt_day_start(end_date) + timedelta(days=1)

    push_conditions: list[dict[str, Any]] = []
    # 部门不下推（原因见模块头部说明），统一在应用侧做子串匹配。
    if alarm_type:
        push_conditions.append(bd_filters.condition(F_ALARM_TYPE, "is", [alarm_type]))
    if alarm_nature:
        push_conditions.append(
            bd_filters.condition(F_ALARM_NATURE, "is", [alarm_nature])
        )
    dimension_option = contract.dimension_to_option(ai_dimension)
    if dimension_option:
        push_conditions.append(
            bd_filters.condition(contract.AI_DIMENSION_FIELD, "is", [dimension_option])
        )

    page_reader = client or bd_reader.open_reader("fire_alarm", "alarm")
    fetched_groups: list[list[dict[str, Any]]] = []
    for _day, day_filter in bd_filters.day_queries(
        F_ALARM_TIME, start_dt, end_dt
    ):
        conditions = list(day_filter["conditions"]) + push_conditions
        filter_info = bd_filters.flat_group(conditions)
        fetched = await page_reader.list_all_records(
            filter_info=filter_info,
            field_names=list(reader.REQUEST_FIELD_NAMES),
            page_size=FETCH_PAGE_SIZE,
            strict=True,
        )
        fetched_groups.append(fetched)

    records = bd_filters.union_by_record_id(fetched_groups)
    views = [reader.to_view(record) for record in records]
    views = bd_filters.trim_records(
        views,
        lambda view: view.alarm_time,
        start=start_dt,
        end=end_dt,
    )
    matched = [
        view
        for view in views
        if _matches(
            view,
            department=department,
            alarm_type=alarm_type,
            alarm_nature=alarm_nature,
            ai_dimension=ai_dimension,
            keyword=keyword,
        )
    ]
    matched.sort(
        key=lambda view: (
            view.alarm_time or datetime.min.replace(tzinfo=UTC),
            view.feishu_record_id or "",
        ),
        reverse=True,
    )

    effective_page = max(page, 1)
    effective_size = max(1, min(page_size, MAX_PAGE_SIZE))
    offset = (effective_page - 1) * effective_size
    return {
        "success": True,
        "items": [
            _view_to_dict(view)
            for view in matched[offset:offset + effective_size]
        ],
        "page": effective_page,
        "page_size": effective_size,
        "total": len(matched),
        "window": {
            "date_from": start_date.isoformat(),
            "date_to": end_date.isoformat(),
        },
    }


__all__ = ["query_fire_alarms_direct", "MAX_QUERY_DAYS", "DEFAULT_QUERY_DAYS"]
