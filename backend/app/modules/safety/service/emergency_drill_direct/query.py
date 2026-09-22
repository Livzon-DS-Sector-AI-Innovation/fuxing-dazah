"""emergency_drill 直读侧内存查询/统计（Ticket 02）——单语义，API 与 Agent 共用。

``filter_views`` / ``sort_views`` / ``paginate`` / ``stats_of`` ↔
service/emergency_drill.py list_records / get_stats（legacy 镜像口径）：

- department / drill_type / status 精确等值（PG == 口径）；
- keyword 大小写不敏感子串，仅 drill_content 单字段（复刻 ilike %kw%）；
  已知边界：keyword 含 % 或 _ 时按字面匹配（legacy ilike 按通配符解释），
  极端输入下两路径结果不同（key_risk_op/cert/contractor 同款已落档限制）；
- stage 三态照 PG 口径：plan=execution_time 为空、execution=execution_time
  非空、review=status 非空；
- 排序：本域 API 不暴露排序参数，legacy 恒 created_at desc；直读取
  plan_time_ref desc NULLS LAST（spec §4.1 D3：探针实证无创建日期公式列，
  111/112 行有值；顺序差异为受控偏差，前端不展示 created_at 列）；
- stats：total / executed（实施时间非空）/ completed（状态=已完成）/
  pending=total-completed / by_type / by_department，None→「未分类」
  （照 legacy get_stats 的 ``row[0] or "未分类"``）。
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from app.modules.safety.service.emergency_drill_direct.views import (
    EmergencyDrillRecordView,
)

__all__ = [
    "filter_views",
    "find_view",
    "paginate",
    "sort_views",
    "stats_of",
]


def _ci_contains(haystack: str | None, needle: str) -> bool:
    return needle.lower() in (haystack or "").lower()


def filter_views(
    views: list[EmergencyDrillRecordView],
    *,
    department: str | None = None,
    drill_type: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    stage: str | None = None,
) -> list[EmergencyDrillRecordView]:
    """API/Agent 列表过滤口径（list_records 等价内存实现）。"""
    filtered = views
    if department:
        filtered = [v for v in filtered if v.department == department]
    if drill_type:
        filtered = [v for v in filtered if v.drill_type == drill_type]
    if status:
        filtered = [v for v in filtered if v.status == status]
    if keyword:
        filtered = [v for v in filtered if _ci_contains(v.drill_content, keyword)]
    if stage == "plan":
        filtered = [v for v in filtered if v.execution_time is None]
    elif stage == "execution":
        filtered = [v for v in filtered if v.execution_time is not None]
    elif stage == "review":
        filtered = [v for v in filtered if v.status is not None]
    return filtered


def _nulls_last_cmp(a: Any, b: Any) -> int:
    """plan_time_ref desc + NULLS LAST（D3 拍板：空值排末尾，业务可读）。"""
    if a is None and b is None:
        return 0
    if a is None:
        return 1
    if b is None:
        return -1
    if a == b:
        return 0
    return -1 if a > b else 1


def sort_views(
    views: list[EmergencyDrillRecordView],
) -> list[EmergencyDrillRecordView]:
    """默认排序：plan_time_ref desc NULLS LAST（spec §4.1 D3）。"""
    return sorted(
        views,
        key=functools.cmp_to_key(
            lambda u, v: _nulls_last_cmp(u.plan_time_ref, v.plan_time_ref)
        ),
    )


def paginate(
    views: list[EmergencyDrillRecordView], skip: int, limit: int
) -> tuple[list[EmergencyDrillRecordView], int]:
    """内存分页，返回 (page_items, total)。"""
    total = len(views)
    return views[skip : skip + limit], total


def stats_of(views: list[EmergencyDrillRecordView]) -> dict[str, Any]:
    """KPI 统计（get_stats 口径：None 分组 → 未分类）。"""
    def group_counts(
        getter: Callable[[EmergencyDrillRecordView], Any],
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        for v in views:
            value = getter(v)
            key = str(value) if value is not None else "未分类"
            counts[key] = counts.get(key, 0) + 1
        return counts

    total = len(views)
    executed = sum(1 for v in views if v.execution_time is not None)
    completed = sum(1 for v in views if v.status == "已完成")
    return {
        "total": total,
        "executed": executed,
        "completed": completed,
        "pending": total - completed,
        "by_type": group_counts(lambda v: v.drill_type),
        "by_department": group_counts(lambda v: v.department),
    }


def find_view(
    views: list[EmergencyDrillRecordView], record_id: str
) -> EmergencyDrillRecordView | None:
    for view in views:
        if view.id == record_id:
            return view
    return None
