"""危化品库存趋势/异动只读查询（趋势看板后端）。

全部基于 daily 快照（19:30 日报落库口径）；急剧变化判定与日报同一阈值体系
（get_surge_thresholds：比例 + 绝对量双阈值，env/DB 可调）。与日报的两处口径差异：
- 物料粒度按 (部门, 物料) 聚合——比日报的纯物料粒度多部门维度，便于定位异动部门；
- D8 断源（前后两份快照 source 不一致）不跳过计算而是显式标记 compare_skipped，
  明细置空、趋势图该日记 0，前端给「环比断点」提示。

纯查询 + 纯计算，无 IO 副作用；api 层直接消费。
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.chemical_inventory.daily_report import get_surge_thresholds
from app.modules.safety.chemical_inventory.snapshots import (
    KIND_DAILY,
    ChemicalInventorySnapshot,
    prev_snapshot_date,
    snapshot_rows_for_date,
    snapshot_rows_source,
)

# 异动明细条数（按 |变化量| 降序截取）
DEFAULT_CHANGES_LIMIT = 100
MAX_CHANGES_LIMIT = 500


def _f(value: Any, places: str = "0.0001") -> float | None:
    """Decimal/数值 → float（默认 4 位小数）；None 原样。"""
    if value is None:
        return None
    return float(Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP))


async def _recent_daily_dates(db: AsyncSession, days: int) -> list[date]:
    """最近 N 个有 daily 快照的日期（新→旧）。按「快照日」而非自然日取窗口，容忍断档。"""
    rows = await db.execute(
        select(ChemicalInventorySnapshot.snapshot_date)
        .where(
            ChemicalInventorySnapshot.snapshot_kind == KIND_DAILY,
            ChemicalInventorySnapshot.is_deleted == False,  # noqa: E712
        )
        .distinct()
        .order_by(ChemicalInventorySnapshot.snapshot_date.desc())
        .limit(days)
    )
    return [r[0] for r in rows.all()]


async def daily_trend_points(db: AsyncSession, days: int = 30) -> list[dict[str, Any]]:
    """逐日聚合（老→新）：现场物料总量合计、条目数、预警条目数。"""
    dates = await _recent_daily_dates(db, days)
    if not dates:
        return []
    rows = await db.execute(
        select(
            ChemicalInventorySnapshot.snapshot_date,
            func.sum(ChemicalInventorySnapshot.total_quantity_t),
            func.count(),
            func.sum(case((ChemicalInventorySnapshot.risk_flag == "warn", 1), else_=0)),
        ).where(
            ChemicalInventorySnapshot.snapshot_kind == KIND_DAILY,
            ChemicalInventorySnapshot.is_deleted == False,  # noqa: E712
            ChemicalInventorySnapshot.snapshot_date.in_(dates),
        ).group_by(ChemicalInventorySnapshot.snapshot_date)
    )
    by_date = {
        r[0]: {"date": r[0].isoformat(), "total_t": _f(r[1]), "item_count": int(r[2]), "warn_count": int(r[3] or 0)}
        for r in rows.all()
    }
    return [by_date[d] for d in sorted(dates)]


def _aggregate_t(rows: list[Any]) -> dict[tuple[str, str], Decimal]:
    """快照行按 (部门, 物料) 聚合现场总量（无吨值的行计 0）。"""
    totals: dict[tuple[str, str], Decimal] = {}
    for r in rows:
        key = (getattr(r, "department", "") or "", getattr(r, "material_name", "") or "?")
        total = Decimal(str(getattr(r, "total_quantity_t", None) or 0))
        totals[key] = totals.get(key, Decimal("0")) + total
    return totals


def _flag(pairs: dict[tuple[str, str], tuple[Decimal, Decimal]],
          ratio_th: Decimal, abs_th: Decimal) -> list[dict[str, Any]]:
    """{(部门,物料): (昨日T, 今日T)} → 变化条目列表（|Δ| 降序，含标记）。

    标记与日报同规则：双阈值达标 → surge/decline；未达标的新出现/消失 → new/removed；
    其余非零变化 → normal（小波动）。Δ=0 不出条目。
    """
    items: list[dict[str, Any]] = []
    for (department, name), (prev, cur) in pairs.items():
        delta = cur - prev
        if delta == 0:
            continue
        ratio = (delta / prev) if prev > 0 else None
        if delta > 0 and delta >= abs_th and (prev <= 0 or ratio >= ratio_th):
            flag = "surge"
        elif delta < 0 and -delta >= abs_th and (prev <= 0 or (ratio is not None and -ratio >= ratio_th)):
            flag = "decline"
        elif prev <= 0:
            flag = "new"
        elif cur <= 0:
            flag = "removed"
        else:
            flag = "normal"
        items.append({
            "department": department,
            "material_name": name,
            "prev_t": _f(prev),
            "cur_t": _f(cur),
            "delta_t": _f(delta),
            "ratio": _f(ratio, "0.0001") if ratio is not None else None,
            "flag": flag,
        })
    items.sort(key=lambda x: -abs(x["delta_t"] or 0))
    return items


async def material_changes(
    db: AsyncSession, target_date: date | None = None, limit: int = DEFAULT_CHANGES_LIMIT
) -> dict[str, Any]:
    """目标日（默认最新 daily 快照日）vs 前一 daily 快照日的部门×物料异动明细。"""
    if target_date is None:
        latest = await _recent_daily_dates(db, 1)
        if not latest:
            return {
                "target_date": None, "base_date": None, "compare_skipped": False,
                "thresholds": None, "summary": {"surge_count": 0, "decline_count": 0,
                                                "new_count": 0, "removed_count": 0,
                                                "total_materials": 0},
                "items": [],
            }
        target_date = latest[0]
    base_date = await prev_snapshot_date(db, target_date, kind=KIND_DAILY)
    cur_rows = await snapshot_rows_for_date(db, target_date, KIND_DAILY)
    prev_rows = (await snapshot_rows_for_date(db, base_date, KIND_DAILY)) if base_date else []
    cur_map, prev_map = _aggregate_t(cur_rows), _aggregate_t(prev_rows)

    # D8 环比断点：两日快照数据源口径不一致（切换/回滚日），环比不可比
    compare_skipped = bool(prev_rows) and snapshot_rows_source(cur_rows) != snapshot_rows_source(prev_rows)

    ratio_th, abs_th = get_surge_thresholds()
    if compare_skipped:
        items: list[dict[str, Any]] = []
    else:
        pairs = {}
        for key in set(cur_map) | set(prev_map):
            pairs[key] = (prev_map.get(key, Decimal("0")), cur_map.get(key, Decimal("0")))
        items = _flag(pairs, ratio_th, abs_th)

    flagged = [i for i in items if i["flag"] in ("surge", "decline")]
    summary = {
        "surge_count": sum(1 for i in items if i["flag"] == "surge"),
        "decline_count": sum(1 for i in items if i["flag"] == "decline"),
        "new_count": sum(1 for i in items if i["flag"] == "new"),
        "removed_count": sum(1 for i in items if i["flag"] == "removed"),
        "total_materials": sum(1 for v in cur_map.values() if v > 0),
    }
    return {
        "target_date": target_date.isoformat(),
        "base_date": base_date.isoformat() if base_date else None,
        "compare_skipped": compare_skipped,
        "thresholds": {"ratio": _f(ratio_th), "abs_t": _f(abs_th)},
        "summary": summary,
        "items": items[: max(1, min(limit, MAX_CHANGES_LIMIT))],
    }


async def change_trend(db: AsyncSession, days: int = 30) -> list[dict[str, Any]]:
    """窗口内逐日急剧上升/下降条数（老→新），供异动趋势柱状/面积图。

    每日与其前一快照日对比；断源日记 0 并标 compare_skipped。
    """
    dates = await _recent_daily_dates(db, days + 1)  # 最老一点作对比基线
    if len(dates) < 2:
        return []
    rows = await db.execute(
        select(
            ChemicalInventorySnapshot.snapshot_date,
            ChemicalInventorySnapshot.department,
            ChemicalInventorySnapshot.material_name,
            func.sum(ChemicalInventorySnapshot.total_quantity_t),
            func.max(ChemicalInventorySnapshot.source),
        ).where(
            ChemicalInventorySnapshot.snapshot_kind == KIND_DAILY,
            ChemicalInventorySnapshot.is_deleted == False,  # noqa: E712
            ChemicalInventorySnapshot.snapshot_date.in_(dates),
        ).group_by(
            ChemicalInventorySnapshot.snapshot_date,
            ChemicalInventorySnapshot.department,
            ChemicalInventorySnapshot.material_name,
        )
    )
    by_date: dict[date, dict[tuple[str, str], Decimal]] = {}
    source_by_date: dict[date, str | None] = {}
    for snap_date, department, name, total, source in rows.all():
        by_date.setdefault(snap_date, {})[(department or "", name or "?")] = Decimal(str(total or 0))
        source_by_date[snap_date] = source

    ratio_th, abs_th = get_surge_thresholds()
    # _recent_daily_dates 取 days+1 个新→旧日期，窗口内每日的环比基线即相邻后一天
    ordered = sorted(dates)  # 老→新
    start = max(1, len(ordered) - days)  # 最老一条仅作基线
    points: list[dict[str, Any]] = []
    for idx in range(start, len(ordered)):
        snap_date = ordered[idx]
        base = ordered[idx - 1]
        cur_map = by_date.get(snap_date, {})
        prev_map = by_date.get(base, {})
        skipped = base is not None and source_by_date.get(snap_date) != source_by_date.get(base)
        if skipped or not prev_map:
            points.append({"date": snap_date.isoformat(), "surge_count": 0,
                           "decline_count": 0, "compare_skipped": skipped})
            continue
        pairs = {key: (prev_map.get(key, Decimal("0")), cur_map.get(key, Decimal("0")))
                 for key in set(cur_map) | set(prev_map)}
        items = _flag(pairs, ratio_th, abs_th)
        points.append({
            "date": snap_date.isoformat(),
            "surge_count": sum(1 for i in items if i["flag"] == "surge"),
            "decline_count": sum(1 for i in items if i["flag"] == "decline"),
            "compare_skipped": False,
        })
    return points
