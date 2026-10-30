"""页面几何：绘图层横线对→图区，横线组→表区，竖线段→表列边界。

关键经验：表区行线阈值必须低于图区宽线（305pt 窄表），否则表区漏检、
表头落入聚簇逻辑连成一行；但图区配对只认宽线，且表区行线只剔除被图区
消费的 y（404pt 宽表行线不能误剔）。"""

from __future__ import annotations

from typing import Any

import pymupdf

from .profiles import Profile


def page_geometry(
    page: pymupdf.Page, prof: Profile
) -> tuple[list[tuple[float, float, float, float]], list[dict[str, Any]]]:
    """返回 (charts, tables)：
    charts: [(y0, y1, x0, x1), ...]
    tables: [{y0, y1, rows, edges, x0, x1}, ...]"""
    hl: list[tuple[float, float, float]] = []
    vsegs: list[tuple[float, float, float]] = []
    for d in page.get_drawings():
        for it in d["items"]:
            if it[0] == "l":
                a, b = it[1], it[2]
                if abs(a.y - b.y) < 0.6 and abs(a.x - b.x) > prof.table_line_min_w:
                    hl.append((round(a.y, 1), min(a.x, b.x), max(a.x, b.x)))
                elif abs(a.x - b.x) < 0.6 and abs(a.y - b.y) > 8:
                    vsegs.append((round(a.x, 1), min(a.y, b.y), max(a.y, b.y)))
            elif it[0] == "re":
                r = it[1]
                if r.width > prof.table_line_min_w and r.height < 1.5:
                    hl.append((round(r.y0, 1), r.x0, r.x1))
                elif r.width < 1.5 and r.height > 8:
                    vsegs.append((round(r.x0, 1), r.y0, r.y1))
    hl = sorted(set(hl))
    wide = [h for h in hl if h[2] - h[1] > prof.wide_line_min_w]
    ys = sorted({y for y, _, _ in wide})

    charts: list[tuple[float, float, float, float]] = []
    rest, i = list(ys), 0
    chart_ys: set[float] = set()
    while i < len(rest) - 1:
        y0, y1 = rest[i], rest[i + 1]
        pair = [r for yy, a, b in wide if yy in (y0, y1) for r in (a, b)]
        if (
            prof.chart_pair_gap[0] < y1 - y0 < prof.chart_pair_gap[1]
            and len(pair) >= 2
            and min(pair) > prof.chart_x0_min
            and prof.chart_width[0] < max(pair) - min(pair) < prof.chart_width[1]
        ):
            xr = [r for yy, a, b in hl if yy in (y0, y1) for r in (a, b)]
            charts.append((y0, y1, min(xr), max(xr)))
            chart_ys.update((y0, y1))
            rest = rest[:i] + rest[i + 2 :]
            continue
        i += 1

    rest_all = [y for y in sorted({y for y, _, _ in hl}) if y not in chart_ys]
    groups: list[list[float]] = []
    for y in rest_all:
        if groups and y - groups[-1][-1] < prof.table_group_gap:
            groups[-1].append(y)
        else:
            groups.append([y])
    tables = []
    for grp in groups:
        if grp[-1] - grp[0] < prof.table_min_height:
            continue
        xs = sorted({x for x, ya, yb in vsegs if ya < grp[-1] and yb > grp[0] + 3})
        edges: list[float] = []
        for x in xs:
            if not edges or x - edges[-1] > prof.vline_dedup:
                edges.append(x)
        xr = [v for yy, a, b in hl if grp[0] - 1 <= yy <= grp[-1] + 1 for v in (a, b)]
        tables.append(
            {
                "y0": grp[0],
                "y1": grp[-1],
                "rows": grp,
                "edges": edges,
                "x0": min(xr),
                "x1": max(xr),
            }
        )
    return charts, tables


def page_vsegs(page: pymupdf.Page) -> list[tuple[float, float, float]]:
    """竖线段 (x, y0, y1)，聚簇右边界用"""
    out: list[tuple[float, float, float]] = []
    for d in page.get_drawings():
        for it in d["items"]:
            if (
                it[0] == "l"
                and abs(it[1].x - it[2].x) < 0.6
                and abs(it[1].y - it[2].y) > 8
            ):
                out.append(
                    (round(it[1].x, 1), min(it[1].y, it[2].y), max(it[1].y, it[2].y))
                )
            elif it[0] == "re" and it[1].width < 1.5 and it[1].height > 8:
                out.append((round(it[1].x0, 1), it[1].y0, it[1].y1))
    return out
