"""特殊作业直读 — Web 台账页面查询（直读看板批次 1，2026-10-13）。

全量拉取报备表 → ``to_query_view``（风险列存量优先，缺失现场判定）→
TTL 缓存 → 内存过滤/分页/统计，口径对齐镜像 ``get_special_operation_ledger``。

与镜像路径的已知差异：
- 状态口径：镜像 status in (submitted, approved)（审批流事件写入）；
  直读以「申请状态 ≠ 已撤回」等价表达（审批中+已通过），已撤回票不入台账；
- ``date_to`` 按当日结束时刻（含当天）比较——镜像历史行为是与当日零点比较
  （当天结束的作业被排除），此处取语义正确版并在此声明；
- ``is_critical`` 直读无平台标记，以日报风险等级=high 近似（关键作业≈高风险）。
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

from app.modules.safety.service.special_op_direct import bitable_repo, config, query

_cached: dict[str, Any] = {"ts": 0.0, "views": []}


class CachedLedgerReader:
    """报备表全量视图的 TTL 缓存读取器（页面/看板共用）。"""

    async def fetch_all(self, *, strict: bool = False) -> list[Any]:
        ttl = config.cache_ttl_seconds()
        now = time.monotonic()
        if not strict and ttl > 0 and _cached["views"] and now - _cached["ts"] < ttl:
            return cast("list[Any]", _cached["views"])

        reader = bitable_repo.resolve_client()
        records = await reader.list_all_records(
            automatic_fields=True, page_size=500, strict=True,
        )
        views = [query.to_query_view(rec) for rec in records]
        # 已撤回票不入台账（镜像 status_list 语义的直读等价）
        views = [
            v for v in views
            if (v.application_status or "") != bitable_repo.WITHDRAWN_APPLICATION_STATUS
        ]
        if ttl > 0:
            _cached["ts"] = now
            _cached["views"] = views
        return views


def open_reader() -> CachedLedgerReader:
    return _READER


_READER = CachedLedgerReader()


def _bj_day_end(d: date) -> datetime:
    """北京时间 d 日 23:59:59.999 的 UTC 瞬时（date_to 含当天语义）。"""
    start_utc = datetime(d.year, d.month, d.day, tzinfo=UTC) - timedelta(hours=8)
    return start_utc + timedelta(days=1) - timedelta(microseconds=1)


def _bj_day_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC) - timedelta(hours=8)


def list_ledger(
    views: list[Any],
    *,
    skip: int = 0,
    limit: int = 20,
    operation_type: str | None = None,
    operation_level: str | None = None,
    risk_level: str | None = None,
    department: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    keyword: str | None = None,
    is_critical: bool | None = None,
) -> tuple[list[Any], int]:
    """台账列表（过滤口径与镜像 ``get_special_operation_ledger`` 一致）。"""
    start = _bj_day_start(date_from) if date_from else None
    end = _bj_day_end(date_to) if date_to else None
    filtered = [
        v for v in views
        if _matches(
            v,
            operation_type=operation_type,
            operation_level=operation_level,
            risk_level=risk_level,
            department=department,
            start=start,
            end=end,
            keyword=keyword,
            is_critical=is_critical,
        )
    ]
    total = len(filtered)
    filtered.sort(
        key=lambda v: v.planned_start_time or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    return filtered[skip : skip + limit], total


def ledger_stats(views: list[Any]) -> list[dict[str, Any]]:
    """按作业类型统计（键与镜像 ``get_special_operation_ledger_stats`` 一致）。

    critical_count 为直读近似口径：日报风险等级=high。
    """
    by_type: dict[str, dict[str, int]] = {}
    for v in views:
        bucket = by_type.setdefault(v.operation_type or "未知", {"count": 0, "critical_count": 0})
        bucket["count"] += 1
        if v.daily_risk_level == "high":
            bucket["critical_count"] += 1
    rows: list[dict[str, Any]] = [
        {"operation_type": op_type, "count": b["count"], "critical_count": b["critical_count"]}
        for op_type, b in by_type.items()
    ]
    rows.sort(key=lambda r: -int(r["count"]))
    return rows


def _matches(
    v: Any,
    *,
    operation_type: str | None,
    operation_level: str | None,
    risk_level: str | None,
    department: str | None,
    start: datetime | None,
    end: datetime | None,
    keyword: str | None,
    is_critical: bool | None,
) -> bool:
    if operation_type and v.operation_type != operation_type:
        return False
    if operation_level and v.operation_level != operation_level:
        return False
    if risk_level and v.risk_level != risk_level:
        return False
    if department and v.department != department:
        return False
    if start and (v.planned_start_time is None or v.planned_start_time < start):
        return False
    if end and (v.planned_end_time is None or v.planned_end_time > end):
        return False
    if is_critical is not None and (v.daily_risk_level == "high") != is_critical:
        return False
    if keyword:
        kw = keyword.lower()
        if not any(
            kw in (getattr(v, f) or "").lower()
            for f in ("report_no", "work_description", "location")
        ):
            return False
    return True
