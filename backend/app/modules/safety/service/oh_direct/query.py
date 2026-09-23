"""oh 直读侧查询（Ticket 02）——两语义，Agent 工具专用。

忠实复刻 legacy 镜像语义（spec D3/D5）：

``oh_positions``（等价 repository.get_oh_positions + 工具体投影）：
- 过滤：department 等值 + hazard_factors_status 等值（视图已按 handler 规则
  派生 filled/empty，等值比较即等价 SQL 列比较）；
- 排序：department asc NULLS LAST → position asc NULLS LAST（内存比较器；
  PG collation 与 Python str 比较的差异属受控偏差，全中文场景无实测差异，落档）；
- 分页：skip/limit 应用侧内存分页（等价 OFFSET/LIMIT）；total=过滤后全量
  计数（等价 SQL count，非页大小）。

``oh_hazard_factors``（等价 repository.get_oh_hazard_factors + 工具体 keyword
后过滤，**quirk 忠实复刻**）：legacy 先 ``ORDER BY factor_name LIMIT :limit``
截断、再 Python keyword 过滤、最后 ``total = len(items)`` 被工具体覆盖
（read_tools.py:855-869 现行为）——即无 keyword 时 total=min(limit, 全表数)、
有 keyword 时 total=窗口内过滤后计数，两者都不是全表计数。直读同序复刻：
先全量排序取前 limit，再窗口内过滤，total=len(最终 items)。
"""

from __future__ import annotations

from typing import Any

from app.modules.safety.service.oh_direct.views import (
    OhHazardFactorView,
    OhPositionView,
)

__all__ = ["oh_hazard_factors", "oh_positions"]

# 与 legacy 工具体逐字同款的输出键集（factors 全字段直取；positions 的
# hazard_factors 需 ``or []`` 投影，键集以 _sort/输出构造为准）
_FACTOR_KEYS = ("id", "factor_name", "ppe_respiratory")


def _sort_key_positions(v: OhPositionView) -> tuple[Any, ...]:
    """排序键：department asc NULLS LAST → position asc NULLS LAST（等价 PG 排序）。"""
    return (
        v.department is None,
        v.department or "",
        v.position is None,
        v.position or "",
    )


def oh_positions(
    views: list[OhPositionView],
    *,
    department: str | None = None,
    hazard_factors_status: str | None = None,
    limit: int = 20,
    skip: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """岗位危害台账列表（legacy get_positions 等价内存实现）。"""
    filtered = [
        v for v in views
        if (not department or v.department == department)
        and (not hazard_factors_status or v.hazard_factors_status == hazard_factors_status)
    ]
    filtered.sort(key=_sort_key_positions)
    window = filtered[max(0, skip): max(0, skip) + max(0, limit)]
    items: list[dict[str, Any]] = [
        {
            "id": v.id,
            "department": v.department,
            "position": v.position,
            "job_title": v.job_title,
            "hazard_factors": v.hazard_factors or [],
            "hazard_factors_status": v.hazard_factors_status,
        }
        for v in window
    ]
    return items, len(filtered)


def oh_hazard_factors(
    views: list[OhHazardFactorView],
    *,
    keyword: str | None = None,
    limit: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    """危害因素 PPE 字典列表（legacy 先 LIMIT 后过滤 quirk 等价内存实现）。"""
    ordered = sorted(views, key=lambda v: v.factor_name or "")
    window = ordered[: max(0, limit)]
    if keyword:
        kw = keyword.strip()
        window = [f for f in window if kw in (f.factor_name or "")]
    items: list[dict[str, Any]] = [
        {key: getattr(v, key) for key in _FACTOR_KEYS} for v in window
    ]
    return items, len(items)
