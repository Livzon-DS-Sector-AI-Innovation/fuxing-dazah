"""直读侧内存查询/统计/详情（key_risk_op-direct Ticket 03）。

两套过滤语义分别复刻（源码本就不同，直读不合并）：
- ``list_reports`` ↔ repo.get_key_risk_operation_reports（API 列表/导出口径）：
  department/area/operation_content/apply_status 精确等值；date_from/to → 北京日界
  UTC 边界（from 端 ``>=``、to 端 ``<=`` 次日零点——逐字对齐 repo 的闭端比较）；
  keyword 对 report_no/作业内容/区域/部门四字段大小写不敏感子串。
    已知边界：keyword/过滤值含 % 或 _ 时按字面匹配（legacy ilike 按通配符解释），
    极端输入下两路径结果不同（cert/chemical 同类复刻的同款限制）。
- ``query_ops_for_agent`` ↔ read_tools.query_key_risk_ops（Agent 口径）：
  department 模糊子串；keyword 仅 作业内容/区域 两字段；无 source 过滤；
  date 边界为裸 date 语义（会话时区午夜，复刻 read_tools._date_bounds 直传 date
  的行为）；排序 start_time DESC（PG 默认 NULLS FIRST）。

统计四 KPI 与 repo.get_key_risk_operation_stats 口径一致（北京日/月界由调用方传入）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.modules.safety.service.key_risk_op_direct.views import KeyRiskOpView

__all__ = [
    "list_reports",
    "query_ops_for_agent",
    "compute_stats",
    "find_by_record_id",
    "sort_start_time_desc_pg",
]


def _ci_contains(haystack: str | None, needle: str) -> bool:
    return needle.lower() in (haystack or "").lower()


async def list_reports(
    views: list[KeyRiskOpView],
    skip: int,
    limit: int,
    department: str | None = None,
    area: str | None = None,
    operation_content: str | None = None,
    apply_status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    keyword: str | None = None,
) -> tuple[list[KeyRiskOpView], int]:
    """API 列表口径（repo.get_key_risk_operation_reports 等价内存实现）。"""
    from app.modules.safety.service.key_risk_operation_report import (
        _day_bounds_utc,
    )

    from_dt = _day_bounds_utc(date_from)[0] if date_from else None
    to_dt = _day_bounds_utc(date_to)[1] if date_to else None

    filtered = views
    if department:
        filtered = [v for v in filtered if v.department == department]
    if area:
        filtered = [v for v in filtered if v.area == area]
    if operation_content:
        filtered = [v for v in filtered if v.operation_content == operation_content]
    if apply_status:
        filtered = [v for v in filtered if v.apply_status == apply_status]
    if from_dt is not None:
        filtered = [v for v in filtered
                    if v.start_time is not None and v.start_time >= from_dt]
    if to_dt is not None:
        # repo 为闭端比较（<= 次日零点），逐字复刻
        filtered = [v for v in filtered
                    if v.start_time is not None and v.start_time <= to_dt]
    if keyword:
        filtered = [v for v in filtered
                    if _ci_contains(v.report_no, keyword)
                    or _ci_contains(v.operation_content, keyword)
                    or _ci_contains(v.area, keyword)
                    or _ci_contains(v.department, keyword)]
    total = len(filtered)
    return filtered[skip : skip + limit], total


def sort_start_time_desc_pg(views: list[KeyRiskOpView]) -> list[KeyRiskOpView]:
    """Agent 口径排序：start_time DESC（PG 默认 NULLS FIRST，稳定排序）。"""
    rows = list(views)
    rows.sort(key=lambda v: (
        v.start_time is not None,
        -(v.start_time.timestamp()) if v.start_time is not None else 0.0,
    ))
    return rows


async def query_ops_for_agent(
    views: list[KeyRiskOpView],
    *,
    department: str | None = None,
    start: date | None = None,
    end_exclusive: date | None = None,
    apply_status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[KeyRiskOpView], int]:
    """Agent 查询口径（read_tools.query_key_risk_ops 等价内存实现）。

    date 边界：复刻 read_tools._date_bounds 直传裸 date 的行为（DB 会话时区午夜，
    平台库会话为 UTC）——date → UTC 午夜 datetime。
    """
    start_dt = (datetime(start.year, start.month, start.day, tzinfo=UTC)
                if start else None)
    end_dt = (datetime(end_exclusive.year, end_exclusive.month, end_exclusive.day,
                       tzinfo=UTC) if end_exclusive else None)

    filtered = views
    if department:
        filtered = [v for v in filtered if _ci_contains(v.department, department)]
    if start_dt is not None:
        filtered = [v for v in filtered
                    if v.start_time is not None and v.start_time >= start_dt]
    if end_dt is not None:
        filtered = [v for v in filtered
                    if v.start_time is not None and v.start_time < end_dt]
    if apply_status:
        filtered = [v for v in filtered if v.apply_status == apply_status.strip()]
    if keyword:
        filtered = [v for v in filtered
                    if _ci_contains(v.operation_content, keyword)
                    or _ci_contains(v.area, keyword)]
    ordered = sort_start_time_desc_pg(filtered)
    # offset 用未封顶 page_size（与 legacy read_tools 逐字一致——审查 MAJOR-1 口径），
    # 仅 limit 封顶 100
    offset = (max(page, 1) - 1) * page_size
    return ordered[offset : offset + min(page_size, 100)], len(filtered)


async def compute_stats(
    views: list[KeyRiskOpView],
    today_start: datetime,
    today_end: datetime,
    month_start: datetime,
    month_end: datetime,
) -> dict[str, int]:
    """四 KPI（repo.get_key_risk_operation_stats 口径；bounds 为 UTC 时刻）。"""
    today_approved = sum(
        1 for v in views
        if v.apply_status == "已通过"
        and v.start_time is not None
        and today_start <= v.start_time < today_end
    )
    in_progress = sum(1 for v in views if v.apply_status == "审批中")
    month_approved = sum(
        1 for v in views
        if v.apply_status == "已通过"
        and v.start_time is not None
        and month_start <= v.start_time < month_end
    )
    return {
        "today_approved": today_approved,
        "in_progress": in_progress,
        "month_approved": month_approved,
        "total": len(views),
    }


def find_by_record_id(
    views: list[KeyRiskOpView], record_id: str
) -> KeyRiskOpView | None:
    for view in views:
        if view.id == record_id:
            return view
    return None
