"""版式规划：把中文 span 归类到 图区竖排标注 / 表格单元格 / 信息区行聚簇，
生成遮盖目标与回填文本。策略全部来自真实报告调参（详见 profiles 注释）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pymupdf

from .profiles import Profile
from .render import Ops
from .spans import (
    cell_of,
    has_cjk,
    join_tokens,
    lines_by_y,
    normalize,
    run_text,
    runs_by_gap,
    tr_run,
)


@dataclass
class PageData:
    """单页解析结果：文本 span + 几何分区"""

    spans: list[dict[str, Any]]
    charts: list[tuple[float, float, float, float]] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    page_w: float = 595.3
    vsegs: list[tuple[float, float, float]] = field(default_factory=list)


def _baseline(y0: float, size: float, prof: Profile) -> float:
    return y0 + prof.baseline_ratio * size


# ────────────────────── 1) 色谱图竖排标注 ──────────────────────
ChartZone = tuple[float, float, float, float]
TableZone = dict[str, Any]
Terms = dict[str, str]
Measure = Any  # 字体测量函数 (text, fs=1.0) -> float（pymupdf 未暴露可注解类型）


def do_chart(
    ops: Ops,
    spans: list[dict[str, Any]],
    charts: list[ChartZone],
    terms: Terms,
    prof: Profile,
    tw: Measure,
) -> None:
    for cy0, cy1, cx0, cx1 in charts:
        cols = [
            s
            for s in spans
            if cy0 - 1 <= s["rect"].y0 <= cy1
            and cx0 + 2 <= (s["rect"].x0 + s["rect"].x1) / 2 <= cx1 - 2
            and s["rect"].width <= prof.chart_label_width
        ]
        groups: list[list[dict[str, Any]]] = []
        for s in sorted(cols, key=lambda r: r["rect"].x0):
            for g in groups:
                if abs(g[0]["rect"].x0 - s["rect"].x0) < prof.chart_col_tol:
                    g.append(s)
                    break
            else:
                groups.append([s])
        centers = [
            sum(s["rect"].x0 + s["rect"].x1 for s in g) / (2 * len(g)) for g in groups
        ]
        for gi, g in enumerate(groups):
            if not any(has_cjk(s["text"]) for s in g):
                continue  # 纯数字列原样保留
            # Empower 竖排标注自下而上读：名字在下、RT 在上、β 前缀最底
            pieces = [
                tr_run(terms, s["text"]) if has_cjk(s["text"]) else s["text"]
                for s in sorted(g, key=lambda r: -r["rect"].y0)
            ]
            text = join_tokens(pieces)
            sc_top = min(s["rect"].y0 for s in g)
            sc_bot = max(s["rect"].y1 for s in g)
            center = (sc_top + sc_bot) / 2  # 以源列中心为轴上下对称扩展
            xcol = (min(s["rect"].x0 for s in g) + max(s["rect"].x1 for s in g)) / 2
            u = max(tw(text), 0.1)
            fs = min(
                prof.chart_fs_cap,
                2 * (cy1 - 2.5 - center) / u,
                2 * (center - cy0 - 2.5) / u,
            )
            for ci, c in enumerate(centers):  # 邻列水平净距限字号
                if ci != gi and abs(c - xcol) < prof.chart_neighbor_cap:
                    fs = min(fs, 2 * (abs(c - xcol) - 1.0))
            fs = max(prof.chart_fs_floor, fs)
            if fs < 6.5:
                ops.warn(f"图区竖排标注字号收缩至 {fs:.1f}pt：{text[:24]}")
            length = tw(text, fs)
            page_no = g[0]["p"]
            for s in g:
                ops.target_chars(s)
            # rotate=90 自下而上；字形带以列中心对齐
            ops.text(page_no, xcol + 0.34 * fs, center + length / 2, text, fs, 90)


# ────────────────────── 2) 表格 ──────────────────────
def pass1_name_fs(
    pd_list: list[PageData], terms: Terms, prof: Profile, tw: Measure
) -> float:
    """名称列全文档统一字号（最长英文如 Anhydrodaptomycin 决定下限）"""
    worst = prof.name_fs_cap
    for pd in pd_list:
        for z in pd.tables:
            name_cell = _name_cell(pd.spans, z)
            if not name_cell:
                continue
            winw = name_cell[1] - 2.0 - (name_cell[0] + 3.0)
            for s in pd.spans:
                if not (z["y0"] - 1 <= s["rect"].y0 <= z["y1"] + 1):
                    continue
                if not has_cjk(s["text"]):
                    continue
                if cell_of(z["edges"], (s["rect"].x0 + s["rect"].x1) / 2) != name_cell:
                    continue
                worst = min(worst, winw / max(tw(tr_run(terms, s["text"])), 0.1))
    return max(prof.name_fs_floor, min(prof.name_fs_cap, worst))


def _name_cell(spans: list[dict[str, Any]], z: TableZone) -> tuple[float, float] | None:
    for s in spans:
        if z["y0"] - 1 <= s["rect"].y0 <= z["y1"] + 1 and s["text"].strip() == "名称":
            return cell_of(z["edges"], (s["rect"].x0 + s["rect"].x1) / 2)
    return None


def do_table(
    ops: Ops,
    spans: list[dict[str, Any]],
    z: TableZone,
    terms: Terms,
    prof: Profile,
    name_fs: float,
    tw: Measure,
) -> None:
    inzone = [
        s
        for s in spans
        if z["y0"] - 1 <= s["rect"].y0 <= z["y1"] + 1 and z["x0"] - 2 <= s["rect"].x0
    ]
    name_cell = _name_cell(inzone, z)
    for by0, by1 in zip(z["rows"], z["rows"][1:]):
        band = [s for s in inzone if by0 <= s["rect"].y0 < by1]
        if not band:
            continue
        chars = [(c, r, s) for s in band for c, r in s["chars"]]
        is_header = (
            len(
                {
                    run_text(r_)
                    for ln in lines_by_y([(c, r) for c, r, _ in chars])
                    for r_ in runs_by_gap(ln)
                    if run_text(r_).strip() in prof.header_keys
                }
            )
            >= 2
        )
        # 行内 run →（按 run 中心）落列；members 保留 (char, rect, span)
        bycell: dict[tuple[float, float], list[Any]] = {}
        for ln in lines_by_y(chars):
            for run in runs_by_gap([(c, r) for c, r, _ in ln], z["edges"]):
                cell = cell_of(
                    z["edges"], sum(r.x0 + r.x1 for _, r in run) / (2 * len(run))
                )
                if not cell:
                    continue
                keys = {(c, r.x0, r.y0) for c, r in run}
                members = [(c, r, s) for c, r, s in ln if (c, r.x0, r.y0) in keys]
                bycell.setdefault(cell, []).append((run, members))
        for cell, items in bycell.items():
            win0, win1 = cell[0] + 3.0, cell[1] - 2.0
            cell_clip = _clip_of(cell)
            if is_header:
                _header_cell(ops, items, cell, win0, win1, terms, prof, tw)
            elif name_cell and cell == name_cell:
                # 名称列：整格合成（吸收行内数字/β/连字符），全文档统一字号
                pieces = [tr_run(terms, run_text(r_)) for r_, _ in items]
                text = join_tokens(pieces)
                y0 = min(r.y0 for _, mem in items for _, r, _s in mem)
                x = min(r.x0 for _, mem in items for _, r, _s in mem)
                for s in {id(s): s for _, mem in items for _, _, s in mem}.values():
                    ops.target_chars(s, cell_clip)
                ops.text(
                    items[0][1][0][2]["p"],
                    x,
                    _baseline(y0, items[0][1][0][2]["size"], prof),
                    text,
                    name_fs,
                    0,
                )
            else:
                for run, mem in items:
                    t = run_text(run)
                    if not has_cjk(t):
                        continue
                    text = tr_run(terms, t)
                    fs = max(
                        prof.fs_floor,
                        min(mem[0][2]["size"], (win1 - win0) / max(tw(text), 0.1)),
                    )
                    for c, r, s in mem:
                        ops.target_chars(s, cell_clip)
                    y0 = min(r.y0 for _, r, _s in mem)
                    ops.text(
                        mem[0][2]["p"],
                        win0,
                        _baseline(y0, mem[0][2]["size"], prof),
                        text,
                        fs,
                        0,
                    )


def _header_cell(
    ops: Ops,
    items: list[Any],
    cell: tuple[float, float],
    win0: float,
    win1: float,
    terms: Terms,
    prof: Profile,
    tw: Measure,
) -> None:
    """表头单元格：两行表头自动拆分（Retention / Time (min)）+ 缩写梯。"""
    lines: list[tuple[float, list[Any]]] = []
    for run, mem in items:
        y0 = min(r.y0 for _, r, _s in mem)
        if lines and abs(y0 - lines[-1][0]) < 5.0:
            lines[-1][1].append((run, mem))
        else:
            lines.append((y0, [(run, mem)]))

    def tr(t: str) -> str:
        return tr_run(terms, t)

    winw = win1 - win0
    # 忽略纯空格行（窄表术语行与单位行之间的空格 span 行）
    lines = [(y, its) for y, its in lines if any(run_text(r_).strip() for r_, _ in its)]
    if len(lines) == 1:
        text = join_tokens([tr(run_text(r_)) for r_, _ in lines[0][1]])
        fs = min(10.0, winw / max(tw(text), 0.1))
        if fs < prof.header_split_min and text in prof.abbrev:
            text = prof.abbrev[text]  # 单行表头也要缩写梯
            ops.warn(f"表头使用缩写 {text}（列宽 {winw:.0f}pt 不足以完整呈现）")
        texts_ys = [(text, lines[0][0])]
    else:
        t1 = join_tokens([tr(run_text(r_)) for r_, _ in lines[0][1]])
        unit2 = join_tokens([tr(run_text(r_)) for r_, _ in lines[-1][1]])
        inner = unit2[1:-1] if unit2.startswith("(") and unit2.endswith(")") else unit2
        fs1 = min(10.0, winw / max(tw(t1), 0.1))
        if fs1 >= prof.header_split_min:
            texts_ys = [(t1, lines[0][0]), (unit2, lines[-1][0])]
        else:
            words = t1.split()
            a = " ".join(words[: len(words) // 2]) if len(words) >= 2 else t1
            b = " ".join(words[len(words) // 2 :]) if len(words) >= 2 else ""
            line2 = f"{b} ({inner})" if (b and inner) else (b or unit2)
            if words and max(tw(a), tw(line2)) * prof.header_split_min <= winw * 1.02:
                ops.warn(f"表头两行拆分：{t1} → {a} / {line2}")
                texts_ys = [(a, lines[0][0]), (line2, lines[-1][0])]
            else:
                if t1 in prof.abbrev:
                    ops.warn(f"表头使用缩写 {prof.abbrev[t1]}（列宽 {winw:.0f}pt）")
                    t1 = prof.abbrev[t1]
                texts_ys = (
                    [(t1, lines[0][0]), (unit2, lines[-1][0])]
                    if tw(t1) * 10 <= winw
                    else [(t1, lines[0][0])]
                )
    for run, mem in items:
        for c, r, s in mem:
            ops.target_chars(s, _clip_of(cell))
    for text, y0 in texts_ys:
        if not text:
            continue
        fs = max(prof.fs_floor, min(10.0, winw / max(tw(text), 0.1)))
        x = cell[0] + 3.0 + (winw - tw(text, fs)) / 2  # 居中
        ops.text(
            items[0][1][0][2]["p"],
            x,
            _baseline(y0, items[0][1][0][2]["size"], prof),
            text,
            fs,
            0,
        )


def _clip_of(cell: tuple[float, float]) -> pymupdf.Rect:
    return pymupdf.Rect(cell[0] + 0.4, 0, cell[1] - 0.4, 10000)


# ────────────────────── 3) 信息区/页脚/标题：按行聚簇 ──────────────────────
def do_clusters(
    ops: Ops,
    spans: list[dict[str, Any]],
    terms: Terms,
    prof: Profile,
    tw: Measure,
    page_w: float,
    vsegs: list[tuple[float, float, float]] | None = None,
) -> None:
    rows: list[list[dict[str, Any]]] = []
    for s in sorted(spans, key=lambda r: r["rect"].y0):
        for row in rows:
            prev = row[-1]
            if (
                min(prev["rect"].y1, s["rect"].y1) - max(prev["rect"].y0, s["rect"].y0)
            ) > 0.5 * min(prev["rect"].height, s["rect"].height):
                row.append(s)
                break
        else:
            rows.append([s])
    for row in rows:
        row.sort(key=lambda r: r["rect"].x0)
        # 标签 span：后邻紧贴冒号，或自身以冒号结尾（跨字段遇新标签必须断开，
        # 否则长值字段会吞并右侧字段——System Name 吞 Sample Set Name 教训）
        label_ids: set[int] = set()
        for i, s in enumerate(row[:-1]):
            nxt = row[i + 1]
            if (
                has_cjk(s["text"])
                and nxt["text"].lstrip().startswith(":")
                and nxt["rect"].x0 - s["rect"].x1 < 6
            ):
                label_ids.add(id(s))
        for s in row:
            if has_cjk(s["text"]) and s["text"].rstrip().endswith((":", "：")):
                label_ids.add(id(s))
        ry0 = min(s["rect"].y0 for s in row)
        ry1 = max(s["rect"].y1 for s in row)
        clusters, cur = [], [row[0]]
        for s in row[1:]:
            gap = s["rect"].x0 - cur[-1]["rect"].x1
            # cluster_gap = 标签列→值列间隙(42-66)与字段→字段间隙(94+)的分界
            if gap > prof.cluster_gap or (id(s) in label_ids and gap > prof.label_gap):
                clusters.append(cur)
                cur = [s]
            else:
                cur.append(s)
        clusters.append(cur)
        for ci, cl in enumerate(clusters):
            if not any(has_cjk(s["text"]) for s in cl):
                continue
            right = (
                clusters[ci + 1][0]["rect"].x0 - 4
                if ci + 1 < len(clusters)
                else page_w - prof.right_margin
            )
            right = min(right, page_w - prof.right_margin)
            x_end = max(s["rect"].x1 for s in cl)
            for x, ya, yb in vsegs or []:  # 行右侧竖线：真实边界
                if x > x_end + 1 and ya < ry1 and yb > ry0:
                    right = min(right, x - prof.vline_right_gap)
            content = [s for s in cl if s["text"].strip()]
            if not content:
                continue
            x0 = min(s["rect"].x0 for s in content)
            size = min(s["size"] for s in content)
            y0 = min(s["rect"].y0 for s in content)
            text = normalize(join_tokens([tr_run(terms, s["text"]) for s in cl]))
            if len(content) == 1:  # 单 span 聚簇
                r0 = content[0]["rect"]
                if ":" in text:
                    # 页脚 label:value 整串（"页码: 1 (共计 1)"）：左对齐+收缩
                    fs = max(
                        prof.info_fs_floor, min(size, (right - x0) / max(tw(text), 0.1))
                    )
                    x = x0
                else:  # 独立标题：原位居中并钳制右界
                    fs = min(
                        size, prof.alone_width_factor * r0.width / max(tw(text), 0.1)
                    )
                    x = r0.x0 + (r0.width - tw(text, fs)) / 2
                    if x + tw(text, fs) > right:
                        fs = max(
                            prof.info_fs_floor,
                            min(fs, (right - r0.x0) / max(tw(text), 0.1)),
                        )
                        x = max(r0.x0, right - tw(text, fs))
            else:
                fs = min(size, (right - x0) / max(tw(text), 0.1))
                if fs < prof.info_abbr_below:  # 信息区缩写梯
                    for full, short in prof.info_abbrev:
                        if full in text:
                            text = text.replace(full, short, 1)
                            fs = min(size, (right - x0) / max(tw(text), 0.1))
                            break
                fs = max(prof.info_fs_floor, fs)
                x = x0
            if fs < prof.info_fs_floor + 0.01 and tw(text, fs) > right - x0:
                ops.warn(f"信息区行接近右边界：{text[:30]}")
            for s in cl:
                ops.target_chars(s)
            ops.text(cl[0]["p"], x, _baseline(y0, size, prof), text, fs, 0)


# ────────────────────── 编排 ──────────────────────
def build_ops(
    pd_list: list[PageData], terms: Terms, prof: Profile, name_fs: float, tw: Measure
) -> Ops:
    """全部页的渲染操作集；目标字符收集与插入文本全在返回的 Ops 里。"""
    ops = Ops()
    for pd in pd_list:
        chart_ids, table_ids = set(), set()
        for cy0, cy1, cx0, cx1 in pd.charts:
            for i, s in enumerate(pd.spans):
                if (
                    cy0 - 1 <= s["rect"].y0 <= cy1
                    and cx0 + 2 <= (s["rect"].x0 + s["rect"].x1) / 2 <= cx1 - 2
                ):
                    chart_ids.add(i)
        for z in pd.tables:
            for i, s in enumerate(pd.spans):
                if (
                    z["y0"] - 1 <= s["rect"].y0 <= z["y1"] + 1
                    and z["x0"] - 2 <= s["rect"].x0
                ):
                    table_ids.add(i)
        table_ids -= chart_ids
        do_chart(
            ops,
            [s for i, s in enumerate(pd.spans) if i in chart_ids],
            pd.charts,
            terms,
            prof,
            tw,
        )
        for z in pd.tables:
            do_table(
                ops,
                [s for i, s in enumerate(pd.spans) if i in table_ids],
                z,
                terms,
                prof,
                name_fs,
                tw,
            )
        rest = [
            s
            for i, s in enumerate(pd.spans)
            if i not in chart_ids and i not in table_ids
        ]
        do_clusters(ops, rest, terms, prof, tw, pd.page_w, vsegs=pd.vsegs)
    return ops
