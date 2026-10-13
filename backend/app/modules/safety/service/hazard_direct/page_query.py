"""隐患直读 — 台账页面内存查询（口径对齐镜像 ``repository/core.py``）。

输入为 ``reader.fetch_all()`` 的全量 HazardView，过滤/排序/分页/统计全部内存完成
（key_risk_op_direct.query 同款模式）。与镜像路径的已知差异：

- 排序按 ``discovered_at``（检查日期）倒序——镜像按 ``created_at`` 倒序，
  Bitable 无平台创建时间，检查日期是最接近的业务时间；
- ``replied``/``verifying``/``rejected`` 恒 0——这三态来自平台工作流
  （整改回复/三级复核），多维表格整改状态只有 已关闭/未关闭/整改中 三选项；
- ``pending_review`` 恒 0——AI 识别完成待审核是平台 AI 流程状态，直读模式由
  轮询直接回写多维表格，不经过平台待审态。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.modules.safety.feishu.bitable_handler import (
    HAZARD_LEVEL_MAP,
)

# 隐患等级匹配的双语集合（镜像列历史存量中英文混存，前端筛选值同理）
_LEVEL_ALIASES: dict[str, set[str]] = {}
for _cn, _en in HAZARD_LEVEL_MAP.items():
    _LEVEL_ALIASES.setdefault(_en, set()).update({_en, _cn})
    _LEVEL_ALIASES.setdefault(_cn, set()).update({_en, _cn})


def _match_level(view_level: str | None, wanted: str) -> bool:
    """等级匹配（EN 枚举码与中文值互通：general≡一般隐患）。"""
    if not view_level:
        return False
    return view_level in _LEVEL_ALIASES.get(wanted, {wanted})


def list_ledger(
    views: list[Any],
    *,
    skip: int = 0,
    limit: int = 20,
    status: str | None = None,
    rectification_status: str | None = None,
    hazard_type: str | None = None,
    hazard_level: str | None = None,
    hazard_category: str | None = None,
    inspection_category: str | None = None,
    department: str | None = None,
    keyword: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> tuple[list[Any], int]:
    """台账列表（过滤口径与 ``SafetyRepository.get_hazards`` 一致）。"""
    filtered = [
        v for v in views
        if _matches(
            v,
            status=status,
            rectification_status=rectification_status,
            hazard_type=hazard_type,
            hazard_level=hazard_level,
            hazard_category=hazard_category,
            inspection_category=inspection_category,
            department=department,
            keyword=keyword,
            date_from=date_from,
            date_to=date_to,
        )
    ]
    total = len(filtered)
    filtered.sort(key=lambda v: v.discovered_at or datetime.min.replace(tzinfo=UTC), reverse=True)
    return filtered[skip : skip + limit], total


def ledger_stats(views: list[Any]) -> dict[str, int]:
    """全局统计（键与 ``SafetyRepository.get_hazard_stats`` 一致）。"""
    now = datetime.now(UTC)
    stats = {
        "total": 0, "pending_review": 0, "pending": 0, "in_progress": 0,
        "replied": 0, "verifying": 0, "rejected": 0, "closed": 0, "overdue": 0,
    }
    for v in views:
        stats["total"] += 1
        if v.rectification_status == "closed":
            stats["closed"] += 1
        elif v.rectification_status == "in_progress":
            stats["in_progress"] += 1
        else:
            stats["pending"] += 1
        if (
            v.deadline is not None
            and v.deadline < now
            and v.rectification_status != "closed"
            and v.status != "closed"
        ):
            stats["overdue"] += 1
    return stats


def trend_buckets(views: list[Any]) -> tuple[list[datetime], list[datetime]]:
    """趋势序列原料：(新增 discovered_at 列表, 闭环 actual_completion_date 列表)。

    与镜像 ``get_hazard_created_times`` / ``get_hazard_closed_times`` 同口径：
    闭环 = 整改状态已关闭且有整改完成时间。
    """
    created = [v.discovered_at for v in views if v.discovered_at is not None]
    closed = [
        v.actual_completion_date
        for v in views
        if v.rectification_status == "closed" and v.actual_completion_date is not None
    ]
    return created, closed


def count_unclosed_asof(views: list[Any], asof: datetime) -> int:
    """历史时点 t 的未闭环数（对齐 ``count_hazards_unclosed_asof``）。

    口径：发现于 t 之前 且 未在 t 前闭环。闭环时间取整改完成时间；
    已关闭但无完成时间的老数据视为早已闭环（镜像回退 updated_at 的近似）。
    """
    count = 0
    for v in views:
        if v.discovered_at is None or v.discovered_at >= asof:
            continue
        if v.rectification_status == "closed" and (
            v.actual_completion_date is None or v.actual_completion_date < asof
        ):
            continue
        count += 1
    return count


def _matches(
    v: Any,
    *,
    status: str | None,
    rectification_status: str | None,
    hazard_type: str | None,
    hazard_level: str | None,
    hazard_category: str | None,
    inspection_category: str | None,
    department: str | None,
    keyword: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> bool:
    if status and v.status != status:
        return False
    if rectification_status and v.rectification_status != rectification_status:
        return False
    if hazard_type and (v.hazard_type or "") != hazard_type:
        return False
    if hazard_level and not _match_level(v.hazard_level, hazard_level):
        return False
    if hazard_category and (v.hazard_category or "") != hazard_category:
        return False
    if inspection_category and inspection_category not in (v.inspection_category or ""):
        return False
    if department and v.department != department:
        return False
    if keyword:
        kw = keyword.lower()
        if kw not in (v.description or "").lower() and kw not in (v.hazard_no or "").lower():
            return False
    if date_from and (v.discovered_at is None or v.discovered_at < date_from):
        return False
    if date_to and (v.discovered_at is None or v.discovered_at > date_to):
        return False
    return True
