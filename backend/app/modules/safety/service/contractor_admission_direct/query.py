"""直读侧内存查询/统计/详情（Ticket 03）——单语义，API 与 Agent 共用（复刻 repo 口径）。

``filter_views`` / ``sort_views`` / ``paginate`` / ``stats_of`` ↔
repository.get_contractor_admission_list / get_contractor_admission_stats：

- related_party_type / submit_status / ai_review_status 精确等值；
  ai_review_status=processing/failed 在直读下恒空（派生态只含 none/completed，
  spec §4.2 用户已接受）；ai_conclusion 精确匹配派生 overall_conclusion；
- keyword 大小写不敏感子串，company_name / contact_person 两字段（复刻 ilike %kw%）；
  已知边界：keyword 含 % 或 _ 时按字面匹配（legacy ilike 按通配符解释），
  极端输入下两路径结果不同（key_risk_op/cert 同款已落档限制）；
- 排序白名单 entry_date/actual_complete_date/created_at/company_name，默认 created_at
  desc；NULLS 口径照 Postgres 默认：ASC NULLS LAST / DESC NULLS FIRST；
  created_at 直读取「创建日期」公式列；company_name 为文本排序，Python 码点序与
  Postgres collation 在极端字符下可能不同序（tie 组本就无稳定次序，verify 归一）；
- stats 三分组 None → "未知"；by_ai_review_status 直读只会出现 none/completed
  （镜像侧还有 processing/failed/未知，比对按口径归因）。
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from app.modules.safety.service.contractor_admission_direct.views import (
    ContractorAdmissionView,
)

__all__ = [
    "filter_views",
    "sort_views",
    "paginate",
    "stats_of",
    "find_view",
]


def _ci_contains(haystack: str | None, needle: str) -> bool:
    return needle.lower() in (haystack or "").lower()


def _derived_conclusion(view: ContractorAdmissionView) -> str | None:
    if not view.ai_review_result:
        return None
    value = view.ai_review_result.get("overall_conclusion")
    return str(value) if value is not None else None


def filter_views(
    views: list[ContractorAdmissionView],
    *,
    related_party_type: str | None = None,
    submit_status: str | None = None,
    ai_review_status: str | None = None,
    ai_conclusion: str | None = None,
    keyword: str | None = None,
) -> list[ContractorAdmissionView]:
    """API/Agent 列表过滤口径（repo.get_contractor_admission_list 等价内存实现）。"""
    filtered = views
    if related_party_type:
        filtered = [v for v in filtered if v.related_party_type == related_party_type]
    if submit_status:
        filtered = [v for v in filtered if v.submit_status == submit_status]
    if ai_review_status:
        filtered = [v for v in filtered if v.ai_review_status == ai_review_status]
    if ai_conclusion:
        filtered = [v for v in filtered if _derived_conclusion(v) == ai_conclusion]
    if keyword:
        filtered = [
            v for v in filtered
            if _ci_contains(v.company_name, keyword)
            or _ci_contains(v.contact_person, keyword)
        ]
    return filtered


_SORT_COLS: dict[str, Callable[[ContractorAdmissionView], Any]] = {
    "entry_date": lambda v: v.entry_date,
    "actual_complete_date": lambda v: v.actual_complete_date,
    "created_at": lambda v: v.created_at,
    "company_name": lambda v: v.company_name,
}


def _pg_cmp(a: Any, b: Any, *, desc: bool) -> int:
    """Postgres 默认 NULLS 口径比较：ASC NULLS LAST / DESC NULLS FIRST。"""
    if a is None and b is None:
        return 0
    if a is None:
        return 1 if not desc else -1
    if b is None:
        return -1 if not desc else 1
    if a == b:
        return 0
    less = a < b
    if desc:
        return 1 if less else -1
    return -1 if less else 1


def sort_views(
    views: list[ContractorAdmissionView],
    sort_by: str | None = None,
    sort_order: str = "desc",
) -> list[ContractorAdmissionView]:
    """排序（白名单外回退 created_at，desc/asc 口径照 repo）。"""
    getter = _SORT_COLS.get(sort_by or "", _SORT_COLS["created_at"])
    desc = sort_order != "asc"

    def compare(u: ContractorAdmissionView, v: ContractorAdmissionView) -> int:
        return _pg_cmp(getter(u), getter(v), desc=desc)

    return sorted(views, key=functools.cmp_to_key(compare))


def paginate(
    views: list[ContractorAdmissionView], skip: int, limit: int
) -> tuple[list[ContractorAdmissionView], int]:
    """内存分页，返回 (page_items, total)。"""
    total = len(views)
    return views[skip : skip + limit], total


def stats_of(views: list[ContractorAdmissionView]) -> dict[str, Any]:
    """KPI 统计（repo.get_contractor_admission_stats 口径：三分组，None → 未知）。"""
    def group_counts(getter: Callable[[ContractorAdmissionView], Any]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for v in views:
            value = getter(v)
            key = str(value) if value is not None else "未知"
            counts[key] = counts.get(key, 0) + 1
        return counts

    return {
        "total": len(views),
        "by_ai_review_status": group_counts(lambda v: v.ai_review_status),
        "by_related_party_type": group_counts(lambda v: v.related_party_type),
        "by_submit_status": group_counts(lambda v: v.submit_status),
    }


def find_view(
    views: list[ContractorAdmissionView], record_id: str
) -> ContractorAdmissionView | None:
    for view in views:
        if view.id == record_id:
            return view
    return None
