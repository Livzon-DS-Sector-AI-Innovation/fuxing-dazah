"""历史定格聚合（S1 二期，DESIGN §4.6 / §5「历史定格」Tab）。

迎检/标准化自评/绩效评定直接取 snapshot 定格结果，不再现场重算。
纯读：按年份分组 period_key → 汇总六态 + 行明细；无快照年份=empty 引导态。
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models.standard_check import (
    SNAP_STATUSES,
    StandardCheckSnapshot,
)
from app.modules.safety.service.standard_check.engine import format_target

# 展示排序（迎检视角：年 → 半年 → 季 → 月；同类倒序）
_Q = re.compile(r"^(\d{4})-Q([1-4])$")
_M = re.compile(r"^(\d{4})-(\d{2})$")
_H = re.compile(r"^(\d{4})H([12])$")


def period_sort_key(period_key: str) -> tuple[int, int]:
    """period_key → (组序, 组内倒序锚)：年 0 < 半年 1 < 季 2 < 月 3。"""
    if m := _H.fullmatch(period_key):
        return 1, -int(m.group(2))
    if m := _Q.fullmatch(period_key):
        return 2, -int(m.group(2))
    if m := _M.fullmatch(period_key):
        return 3, -int(m.group(2))
    return 0, 0


def period_label(period_key: str) -> str:
    """period_key → 中文标签（前端分组标题）。"""
    if m := _H.fullmatch(period_key):
        half = "上半年" if m.group(2) == "1" else "下半年"
        return f"{m.group(1)} {half}"
    if m := _Q.fullmatch(period_key):
        return f"{m.group(1)} 第{'一二三四'[int(m.group(2)) - 1]}季度"
    if m := _M.fullmatch(period_key):
        return f"{m.group(1)} 年 {int(m.group(2))} 月"
    return f"{period_key} 年度"


def _row_payload(s: StandardCheckSnapshot) -> dict[str, Any]:
    target = format_target(s.operator, s.target_value, s.unit)
    return {
        "standard_no": s.standard_no,
        "clause": s.clause,
        "basis": s.basis,
        "element": s.element,
        "metric_key": s.metric_key,
        "period": s.period,
        "target_display": target,
        "actual_display": s.actual_display,
        "status": s.status,
        "department": s.department or [],
        "owner": s.owner,
        "note": s.note,
        "auto": bool(s.metric_key),
    }


def _summary(rows: list[StandardCheckSnapshot]) -> dict[str, Any]:
    counts = dict.fromkeys(SNAP_STATUSES, 0)
    for s in rows:
        counts[s.status] = counts.get(s.status, 0) + 1
    judged = counts["achieved"] + counts["manual_done"] + counts["missed"] + counts["manual_missed"]
    ok = counts["achieved"] + counts["manual_done"]
    return {
        **counts,
        "total": len(rows),
        # 与页面 compliance_rate 同口径：达标/(达标+未达标)，无数据/进行中不计入
        "compliance_rate": round(ok * 100 / judged) if judged else None,
    }


async def build_standard_history(
    year: int | None = None,
    *,
    db: AsyncSession,
    today: date | None = None,
) -> dict[str, Any]:
    """年份 → 定格结果（live/empty 两态）+ 可选年份清单。

    available_years 恒全量返回（前端年份切换引导）；periods 按
    年 → 半年 → 季 → 月 组序排列（同类倒序，迎检先看年度终版）。
    """
    from app.modules.safety.service.standard_check import page as sc_page

    today = today or sc_page._bj_today()
    year = year or today.year

    available = [
        int(y) for y in (
            await db.execute(
                select(StandardCheckSnapshot.year)
                .where(StandardCheckSnapshot.is_deleted.is_(False))
                .distinct()
                .order_by(StandardCheckSnapshot.year.desc())
            )
        ).scalars()
    ]

    rows = list(
        (
            await db.execute(
                select(StandardCheckSnapshot)
                .where(
                    StandardCheckSnapshot.is_deleted.is_(False),
                    StandardCheckSnapshot.year == year,
                )
                .order_by(StandardCheckSnapshot.standard_no)
            )
        )
        .scalars()
        .all()
    )

    by_period: dict[str, list[StandardCheckSnapshot]] = {}
    for s in rows:
        by_period.setdefault(s.period_key, []).append(s)

    periods = [
        {
            "period_key": pk,
            "label": period_label(pk),
            "frozen_at": max(s.frozen_at for s in ss).isoformat(),
            "summary": _summary(ss),
            "rows": [_row_payload(s) for s in ss],
        }
        for pk, ss in sorted(
            by_period.items(), key=lambda kv: (period_sort_key(kv[0]), kv[0])
        )
    ]
    return {
        "status": "live" if periods else "empty",
        "year": year,
        "available_years": available,
        "periods": periods,
    }
