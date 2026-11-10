"""PQR 段级 Word 年度回顾报告：matplotlib 趋势图 + docxtpl 模板渲染。

口径对齐独立年度回顾工具 qa_year_review（stats.py/charts.py/gen_template.py）：
- 统计值复用 analysis.compute_column_stats（查询时计算，不入库）；
- 文字项/恒值数值项走 t1 常数结论，变值数值项走 t2（均值+极值+趋势图+
  CPK 结论）；模板结论文案保持原样（列内出现 OOS/OOT 也照写，与既有
  手工流程一致，最终由 QA 人工签核把关）；
- 趋势图版式（15×8.5cm/300dpi/线色线宽/右侧图例按限值排序/0.25磅边框/
  批号自适应字号/%列精度+1）复刻其「趋势图格式要求」；中文回退到仓库
  自带 Noto Serif SC（服务器无宋体，assets/fonts 随代码打包）。
"""

from __future__ import annotations

import asyncio
import io
import tempfile
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.qa.models import AprValueType
from app.modules.qa.repository import apr as repo
from app.modules.qa.service.apr.analysis import build_trend_points, compute_column_stats
from app.modules.qa.service.apr.common import (
    _display_name,
    _get_product_or_404,
    _get_section_or_404,
    _item_precision,
)

_TEMPLATE_RELPATH = "qa/apr/templates/pqr_report_template.docx"

# 仓库 assets 根候选：report.py 在 backend/app/modules/qa/service/apr/ 下，
# parents[5] 即 backend 根；再兜底 cwd 与上级（从任意目录启动都能找到）
_ASSET_ROOTS = [
    Path(__file__).resolve().parents[5] / "assets",
    Path("assets"),
    Path("../assets"),
]


def _template_path() -> Path:
    """报告模板定位：backend/assets/qa/apr/templates/（随代码打包，不进 app 包）。"""
    for root in _ASSET_ROOTS:
        candidate = root / _TEMPLATE_RELPATH
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"未找到 PQR 报告模板 assets/{_TEMPLATE_RELPATH}")

# 趋势图版式常量（对齐 qa_year_review「趋势图格式要求」）
_FIG_SIZE = (15 / 2.54, 8.5 / 2.54)
_DATA_COLOR = "#1F4E79"
_SPEC_COLOR = "red"
_OOT_COLOR = "brown"
_AVG_COLOR = "black"
_LEGEND_FONTSIZE = 9

_MATPLOTLIB_READY = False


def _setup_matplotlib() -> None:
    """Agg 后端 + 字体回退链（西文衬线 → 中文逐字回退宋体族）。

    直接赋 font.family 才能触发逐字回退；服务器无宋体/Times New Roman，
    注册仓库自带 Noto Serif SC 兜底，本机有真宋体时优先系统字体。
    """
    global _MATPLOTLIB_READY
    import logging

    import matplotlib

    matplotlib.use("Agg")
    if _MATPLOTLIB_READY:
        return
    # 回退链按逐字尝试各字体，缺失字体名每次渲染都会打 findfont 警告，压掉
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
    from matplotlib import font_manager

    bundled: list[str] = []
    for fonts_dir in (root / "fonts" for root in _ASSET_ROOTS):
        if not fonts_dir.is_dir():
            continue
        for font_file in sorted(fonts_dir.iterdir()):
            if font_file.suffix.lower() not in {".ttf", ".otf"}:
                continue
            try:
                font_manager.fontManager.addfont(str(font_file))
            except Exception:
                continue  # 损坏字体不阻断报告，回退链里少一个名字而已
            bundled.append(
                font_manager.FontProperties(fname=str(font_file)).get_name()
            )
        break
    chain = [
        "Times New Roman",
        "DejaVu Serif",
        "Songti SC",
        "SimSun",
        "NSimSun",
        "STSong",
        *bundled,
        "Microsoft YaHei",
        "PingFang SC",
        "DejaVu Sans",
    ]
    deduped: list[str] = []
    for name in chain:
        if name not in deduped:
            deduped.append(name)
    matplotlib.rcParams["font.family"] = deduped
    matplotlib.rcParams["axes.unicode_minus"] = False
    _MATPLOTLIB_READY = True


def _fmt(value: float, prec: int, unit: str) -> str:
    return f"{value:.{prec}f}{unit}"


def _range_text(item: dict[str, Any], prec: int, unit: str) -> str:
    """由标准限推导范围文案：≤ / ≥ / 区间；无限回退标准原文。"""
    spec_min, spec_max = item.get("spec_min"), item.get("spec_max")
    if spec_min is not None and spec_max is not None:
        return (
            f"{spec_min:.{prec}f}{unit}~{spec_max:.{prec}f}{unit}"
        )
    if spec_max is not None:
        return f"≤{spec_max:.{prec}f}{unit}"
    if spec_min is not None:
        return f"≥{spec_min:.{prec}f}{unit}"
    return str(item.get("spec_text") or "—")


def build_report_rows(
    items: list[dict[str, Any]], *, product: str
) -> list[dict[str, Any]]:
    """把段内各列的年度数据点分类成模板渲染行（纯函数，图与 docx 无关）。

    items 每项：{id, code, name_cn, value_type, unit, spec_text, spec_min,
    spec_max, stat_precision, points: [(批号标签, 数值或文字结果)]}；
    数值列的文字点（未检出等）按 0 进统计（exclude 口径的行由加载侧过滤）。
    输出行：t1=常数结论（文字项/恒值数值项）、t2=均值+极值+CPK（photo 由
    渲染层补）。无数据点的列跳过。
    """
    rows: list[dict[str, Any]] = []
    for item in items:
        points: list[tuple[str, float | str]] = item.get("points") or []
        if not points:
            continue
        name = _display_name(str(item["name_cn"]), str(item.get("code") or ""))
        prec = _item_precision(item)
        unit = str(item.get("unit") or "")

        if item.get("value_type") != "number":
            # 文字项：结论句写最常出现的文字结果
            const = Counter(v for _, v in points).most_common(1)[0][0]
            rows.append(
                {
                    "id": item["id"],
                    "tpl": "t1",
                    "product": product,
                    "test_name": name,
                    "const": str(const),
                    "range": str(item.get("spec_text") or "—"),
                }
            )
            continue

        values = [float(v) if not isinstance(v, str) else 0.0 for _, v in points]
        nd_texts = [v for _, v in points if isinstance(v, str)]
        stats = compute_column_stats(
            values, spec_min=item.get("spec_min"), spec_max=item.get("spec_max")
        )
        range_ = _range_text(item, prec, unit)
        if stats["max"] == stats["min"]:
            # 恒值数值项：免图，结论句直接写结果值；全列未检出（按 0 计）时
            # 写原文（如 未检出），与下面 t2 最小值的处理同口径。
            const = (
                str(nd_texts[0])
                if nd_texts and stats["max"] == 0.0
                else _fmt(stats["max"], prec, unit)
            )
            rows.append(
                {
                    "id": item["id"],
                    "tpl": "t1",
                    "product": product,
                    "test_name": name,
                    "const": const,
                    "range": range_,
                }
            )
            continue
        # 最小值为 0 且列有未检出文字：按原始文字展示（如 未检出/<1）
        if nd_texts and stats["min"] == 0.0:
            min_text: str = str(nd_texts[0])
        else:
            min_text = _fmt(stats["min"], prec, unit)
        cpk = stats.get("cpk")
        rows.append(
            {
                "id": item["id"],
                "tpl": "t2",
                "product": product,
                "test_name": name,
                "range": range_,
                "avg": _fmt(stats["mean"], prec, unit),
                "max": _fmt(stats["max"], prec, unit),
                "min": min_text,
                "cpk": round(cpk, 2) if cpk is not None else "N/A",
                "cpk_level": stats.get("cpk_level", "N/A"),
            }
        )
    return rows


def _render_trend_chart(png_path: Path, *, item: dict[str, Any]) -> None:
    """单列趋势图（版式复刻 qa_year_review charts.py）。"""
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    from matplotlib.ticker import FuncFormatter

    name = _display_name(str(item["name_cn"]), str(item.get("code") or ""))
    prec = _item_precision(item)
    unit = str(item.get("unit") or "")
    labels = [label for label, _ in item["points"]]
    values = [0.0 if isinstance(v, str) else float(v) for _, v in item["points"]]
    nd_texts = [v for _, v in item["points"] if isinstance(v, str)]
    x_axis = list(range(len(labels)))
    avg = sum(values) / len(values)
    spec_min, spec_max = item.get("spec_min"), item.get("spec_max")
    oot_min, oot_max = item.get("oot_min"), item.get("oot_max")

    fig, ax = plt.subplots(figsize=_FIG_SIZE, constrained_layout=True)
    # 数据线：深蓝 1 磅（图例只列标准/平均值/OOT，不含数据线）
    ax.plot(x_axis, values, marker="o", markersize=3, linewidth=1, color=_DATA_COLOR)

    legend_entries: list[tuple[float, Any, str]] = []
    # 平均值线：黑 0.25 磅；均值恰为 0 且列有未检出文字时按文字展示
    avg_s = _fmt(avg, prec, unit) if avg != 0 or not nd_texts else str(nd_texts[0])
    avg_line = ax.axhline(y=avg, color=_AVG_COLOR, linewidth=0.25)
    legend_entries.append((avg, avg_line, f"平均值={avg_s}"))
    # 标准上/下限：红 2 磅；只有上限时 y 轴从 0 起（杂质类列惯例）
    if spec_max is not None:
        line = ax.axhline(y=float(spec_max), color=_SPEC_COLOR, linewidth=2)
        legend_entries.append(
            (float(spec_max), line, f"标准上限={spec_max:.{prec}f}{unit}")
        )
    if spec_min is not None:
        line = ax.axhline(y=float(spec_min), color=_SPEC_COLOR, linewidth=2)
        legend_entries.append(
            (float(spec_min), line, f"标准下限={spec_min:.{prec}f}{unit}")
        )
    else:
        ax.set_ylim(bottom=0)
    # OOT/警戒线：棕 1.5 磅
    if oot_max is not None:
        line = ax.axhline(y=float(oot_max), color=_OOT_COLOR, linewidth=1.5)
        legend_entries.append(
            (float(oot_max), line, f"OOT上限={oot_max:.{prec}f}{unit}")
        )
    if oot_min is not None:
        line = ax.axhline(y=float(oot_min), color=_OOT_COLOR, linewidth=1.5)
        legend_entries.append(
            (float(oot_min), line, f"OOT下限={oot_min:.{prec}f}{unit}")
        )

    ax.set_title(f"{name}趋势图", fontsize=18, fontweight="bold")
    ax.set_xlabel("批号", fontsize=11, fontweight="bold")
    ax.set_ylabel(name, fontsize=11, fontweight="bold")
    ax.tick_params(axis="y", labelsize=10)
    ax.tick_params(axis="x", labelsize=9)
    # y 轴刻度统一拼单位；% 列加一位精度是既有约定
    decimals = prec + 1 if unit == "%" else prec
    ax.yaxis.set_major_formatter(
        FuncFormatter(lambda x, _p: f"{x:.{decimals}f}{unit}")
    )
    ax.set_xticks(x_axis)
    # ha=center 让竖排批号中线正对刻度（ha=right 会整体左偏约一个字高）
    ax.set_xticklabels(labels, rotation=90, ha="center")

    # 图例：右侧外置、按限值自上而下、文字颜色与线一致
    legend_entries.sort(key=lambda e: e[0], reverse=True)
    legend = fig.legend(
        [e[1] for e in legend_entries],
        [e[2] for e in legend_entries],
        loc="outside right center",
        fontsize=_LEGEND_FONTSIZE,
        frameon=False,
        handlelength=1.2,
        handletextpad=0.4,
        labelspacing=0.3,
    )
    from matplotlib.lines import Line2D

    for handle, text in zip(legend.legend_handles, legend.get_texts()):
        # 图例句柄静态类型是 Artist：这里全是水平线，收窄后取颜色
        if isinstance(handle, Line2D):
            text.set_color(handle.get_color())

    # 边框黑 0.25 磅：向内缩半个线宽，笔画中心压画布边界会被裁半条线
    border_lw = 0.25
    fig_w_in, fig_h_in = fig.get_size_inches()
    dx = (border_lw / 72 / 2) / fig_w_in
    dy = (border_lw / 72 / 2) / fig_h_in
    fig.add_artist(
        Rectangle(
            (dx, dy),
            1 - 2 * dx,
            1 - 2 * dy,
            transform=fig.transFigure,
            fill=False,
            edgecolor="black",
            linewidth=border_lw,
            zorder=10,
        )
    )
    # 批号宋体 9 号；批次数多到重叠时按绘图区宽度自适应缩小
    fig.canvas.draw()
    per_label_pt = ax.get_window_extent().width / fig.dpi * 72 / len(labels)
    xt_size = min(9, max(4.5, round(0.85 * per_label_pt, 1)))
    ax.tick_params(axis="x", labelsize=xt_size)

    fig.savefig(png_path, dpi=300)
    plt.close(fig)


def _render_report_sync(
    payload_items: list[dict[str, Any]], product_name: str
) -> bytes:
    """同步渲染（在线程池执行）：趋势图 → docxtpl 模板 → docx 字节。"""
    rows = build_report_rows(payload_items, product=product_name)
    if not rows:
        raise AppException(
            status_code=422, message="该年度没有可生成报告的检测数据。"
        )
    _setup_matplotlib()
    from docx.shared import Mm
    from docxtpl import DocxTemplate, InlineImage  # type: ignore[import-untyped]

    tpl = DocxTemplate(str(_template_path()))
    items_by_id = {str(i["id"]): i for i in payload_items}
    with tempfile.TemporaryDirectory() as tmpdir:
        for row in rows:
            if row["tpl"] != "t2":
                continue
            png_path = Path(tmpdir) / f"{row['id']}.png"
            _render_trend_chart(png_path, item=items_by_id[row["id"]])
            # InlineImage 需要 tpl 实例：图画完立即挂到行上
            row["photo"] = InlineImage(tpl, str(png_path), width=Mm(150))
        # autoescape：产品名/项目名/标准原文/结果都可能含 <、&；docxtpl 默认
        # 不转义，recover 解析会静默丢字。InlineImage 有 __html__，图片不受影响。
        tpl.render({"data": rows}, autoescape=True)
        buf = io.BytesIO()
        tpl.save(buf)
        return buf.getvalue()


async def build_section_report(
    db: AsyncSession, section_id: uuid.UUID, *, year: int
) -> tuple[bytes, str]:
    """段级年度回顾 Word 报告：返回 (docx 字节, 下载文件名)。

    图表与 docx 渲染是同步 CPU 工作（单段十几列毫秒~秒级），放线程池
    避免阻塞事件循环；统计仍查询时计算。
    """
    section = await _get_section_or_404(db, section_id)
    product = await _get_product_or_404(db, section.product_id)
    items = await repo.list_items(db, section_id, active_only=True)
    batches = await repo.list_batches_of_section(db, section_id, year=year)
    if not batches:
        raise AppException(
            status_code=422,
            message=(
                f"模板段「{section.name}」在 {year} 年度还没有登记批次，"
                "无法生成报告。"
            ),
        )
    # 数值列点集与页面趋势同一条管线（load_numeric_series + build_trend_points）：
    # 同查询同排序同 ND 口径，图内数据与页面趋势图恒一致。
    # 文字列只收结论文字，走段级取值查询。
    text_items = [i for i in items if i.value_type != AprValueType.NUMBER.value]
    raw_values = (
        await repo.load_section_values(
            db, section_id, year=year, item_ids=[i.id for i in text_items]
        )
        if text_items
        else []
    )
    batch_no_by_id = {b.id: b.batch_no for b in batches}
    # item_id -> {(批次号, 行号): 文字/数值}
    text_cells: dict[uuid.UUID, dict[tuple[str, int], float | str]] = {}
    for batch_id, item_id, row_seq, value_num, value_text, _row_label in raw_values:
        batch_no = batch_no_by_id.get(batch_id)
        if batch_no is None:
            continue
        value: float | str | None = (
            value_text if value_text is not None else value_num
        )
        if value is not None:
            text_cells.setdefault(item_id, {})[(batch_no, row_seq)] = value

    payload_items: list[dict[str, Any]] = []
    for item in items:
        if item.value_type == AprValueType.NUMBER.value:
            series = await repo.load_numeric_series(db, item.id, year=year)
            trend_points, _values, _nd = build_trend_points(
                series,
                nd_policy=item.nd_policy,
                spec_min=item.spec_min,
                spec_max=item.spec_max,
                oot_min=item.oot_min,
                oot_max=item.oot_max,
            )
            # 标签规则与前端 AprTrendChart 一致：row_seq>1 拼「批号·行号」；
            # ND 点带原文（build_report_rows 按口径映 0 并用于最小值展示）
            points: list[tuple[str, float | str]] = [
                (
                    (
                        f"{p['batch_no']}·{p['row_seq']}"
                        if p["row_seq"] > 1
                        else p["batch_no"]
                    ),
                    p["text"] if p["nd"] else p["value"],
                )
                for p in trend_points
            ]
        else:
            cells = text_cells.get(item.id, {})
            points = [(label, v) for (label, _rs), v in sorted(cells.items())]
        payload_items.append(
            {
                "id": str(item.id),
                "code": item.code,
                "name_cn": item.name_cn,
                "value_type": item.value_type,
                "unit": item.unit,
                "spec_text": item.spec_text,
                "spec_min": item.spec_min,
                "spec_max": item.spec_max,
                "oot_min": item.oot_min,
                "oot_max": item.oot_max,
                "stat_precision": item.stat_precision,
                "points": points,
            }
        )
    content = await asyncio.to_thread(_render_report_sync, payload_items, product.name)
    filename = f"{product.name}{section.name}{year}年度回顾报告.docx"
    return content, filename
