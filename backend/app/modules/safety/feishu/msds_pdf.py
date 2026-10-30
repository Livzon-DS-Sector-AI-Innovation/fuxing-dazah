"""MSDS 标准 PDF 生成器 — 复刻《无水硫酸镁；泻盐MSDS.pdf》企业格式。

输出 A4 纵向 PDF：顶部居中「MSDS 表」标题；单表四列（窄列竖排标签 + 内容两栏）；
理化特性(左)×职业接触限值(右)交错 6 行；健康危害/急救措施/接触控制(左)×
稳定性/泄漏/消防/废弃(右)两大块；● 项目符号；操作处置与储存注意事项收尾。

共享 msds_docx 的标签映射与组合字段拆分逻辑（_DIRECT_LABEL_TO_FIELD /
_SUB_LABEL_SPECS / _SECTION_FIELD / _resolve_value / _split_into_parts）。

字体用 reportlab 内置 CID 字体 STSong-Light（无需字体文件，Docker 无中文字体
也能渲染）。中文换行用 wordWrap="CJK"。
"""

from __future__ import annotations

import html
import logging

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

from app.modules.safety.feishu.msds_docx import (
    _SECTION_FIELD,
    _SUB_LABEL_SPECS,
    _resolve_value,
    _split_into_parts,
)

logger = logging.getLogger(__name__)

pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
_FONT = "STSong-Light"

# ── 样式 ──────────────────────────────────────────────────────────────

# 字号对齐《无水硫酸镁；泻盐MSDS.pdf》（客观测量）：
#   - 标题 36pt、顶部两行（名称/分子式/UNNo/CAS No 及值）12pt 横排
#   - 其余全部 9pt（竖排标签、节标题、正文）
# 单页自适应（2026-10-30，打印需求）：以上为 1.0 倍基准，放不进一页时按
# _SCALE_STEPS 逐档整体缩小字号重排（列宽/版式不变），直到整表收进一页。
_TITLE = ParagraphStyle("msds_title", fontName=_FONT, fontSize=36, leading=42, alignment=1, spaceAfter=8)
_LABEL_TOP = ParagraphStyle("msds_label_top", fontName=_FONT, fontSize=12, leading=16, alignment=1)
_VALUE_TOP = ParagraphStyle("msds_value_top", fontName=_FONT, fontSize=12, leading=16)
_LABEL = ParagraphStyle("msds_label", fontName=_FONT, fontSize=9, leading=12, wordWrap="CJK")
_BODY = ParagraphStyle("msds_body", fontName=_FONT, fontSize=9, leading=13, wordWrap="CJK")

# 缩放档位：内容多时先挤上下边距与行距，再缩字号；下限 6.5pt 仍放不下才分页
_SCALE_STEPS: tuple[float, ...] = (1.0, 0.94, 0.89, 0.83, 0.78, 0.72, 0.67)

# 列宽（pt）：左竖排标签(20) + 顶部横排标签位(40) + 内容(186.65) ×2；边距 51pt → 表格宽 493.3
_COL_LABEL_NARROW = 20
_COL_LABEL_WIDE = 40
_COL_CONTENT = 186.65
_COLS = [_COL_LABEL_NARROW, _COL_LABEL_WIDE, _COL_CONTENT, _COL_LABEL_NARROW, _COL_LABEL_WIDE, _COL_CONTENT]

# 理化特性 6 行的左栏子项（模板标签，直接字段；每行最多两个并排）
# 「外观与性状」为 GB/T 16483 标准术语（2026-10-30 修正历史错别字「外观与现状」）
_PHYS_ROW_LABELS: list[tuple[str, str | None]] = [
    ("外观与性状", None),
    ("溶解性", None),
    ("熔点", "闪点"),
    ("沸点", "相对密度（水）"),
    ("爆炸上限(%)", "爆炸下限(%)"),
    ("自燃温度", "分解温度"),
]

# OEL 值出现的行（其余行留空，匹配参考网格）
_OEL_ROW_LABELS: dict[int, str] = {
    0: "时间加权平均容许浓度（PC-TWA）",
    2: "短时间接触容许浓度（PC-STEL）",
    4: "最高容许浓度（MAC）",
}

# ── 工具 ──────────────────────────────────────────────────────────────


def _esc(value: str) -> str:
    """转义 XML 实体，安全嵌入 reportlab Paragraph 标记。"""
    return html.escape(value or "")


def _resolve(label: str, entry: dict, section_parts: dict) -> str:
    """取模板标签对应的值（复用 docx 的字段解析）。"""
    return _resolve_value(label, label, entry, section_parts)


def _bullet_lines(section: str, entry: dict, section_parts: dict) -> list[str]:
    """组合节的 ● 行列表：{子标签}：{值}。整块节（泄漏应急处理）单行。"""
    field_key = _SECTION_FIELD[section]
    raw = (entry.get(field_key) or "").strip()
    if not raw:
        return []
    if section == "泄漏应急处理":
        return [f"● {raw}"]
    parts = section_parts.get(section, {})
    lines: list[str] = []
    for lbl, (sec, aliases) in _SUB_LABEL_SPECS.items():
        if sec != section:
            continue
        for a in aliases:
            if a in parts:
                lines.append(f"● {a}：{parts[a]}")
                break
    return lines


def _block_cell(header: str, body_lines: list[str], style: ParagraphStyle | None = None) -> Paragraph:
    """大块单元格：节标题（字号略大）+ ● 内容行（style 注入供自适应档位）。"""
    pieces = [_section_header(header)]
    for line in body_lines:
        pieces.append(_esc(line))
    return Paragraph("<br/>".join(pieces), style or _BODY)


def _section_header(text: str) -> str:
    """节标题标记：参考为 9pt 宋体（SimSun），同正文字号。"""
    return _esc(text)


def _label(text: str) -> Paragraph:
    """竖排标签（9pt）：CJK 逐字竖排，供窄列使用。"""
    return Paragraph(_esc(text), _LABEL)


def _label_top(text: str) -> Paragraph:
    """顶部两行标签（12pt 横排）：名 称/分子式/UNNo/CAS No。"""
    return Paragraph(_esc(text), _LABEL_TOP)


def _value_top(text: str) -> Paragraph:
    """顶部两行值（12pt 横排）。"""
    return Paragraph(_esc(text), _VALUE_TOP)


def _body(text: str) -> Paragraph:
    return Paragraph(_esc(text), _BODY)


# ── 主入口 ────────────────────────────────────────────────────────────


def _scaled_styles(scale: float) -> dict[str, ParagraphStyle]:
    """按缩放系数派生一套字号/行距（标题档位差压平，正文线性缩）。"""
    title = ParagraphStyle(
        "msds_title", fontName=_FONT,
        fontSize=round(36 * scale), leading=42 * scale, alignment=1,
        spaceAfter=8 * scale,
    )
    top = round(12 * scale, 1)
    body = round(9 * scale, 2)
    return {
        "title": title,
        "label_top": ParagraphStyle("msds_label_top", fontName=_FONT, fontSize=top, leading=16 * scale, alignment=1),
        "value_top": ParagraphStyle("msds_value_top", fontName=_FONT, fontSize=top, leading=16 * scale),
        "label": ParagraphStyle("msds_label", fontName=_FONT, fontSize=body, leading=12 * scale, wordWrap="CJK"),
        "body": ParagraphStyle("msds_body", fontName=_FONT, fontSize=body, leading=13 * scale, wordWrap="CJK"),
    }


def _clip_entry(entry: dict, limit: int) -> dict:
    """极端长文安全阀：每个文本字段截到 limit 字（保号 + …截断 标记）。"""
    clipped: dict = {}
    for k, v in entry.items():
        if isinstance(v, str) and len(v) > limit:
            clipped[k] = v[:limit].rstrip() + "…截断"
        else:
            clipped[k] = v
    return clipped


def _fits_one_page(
    title: Paragraph,
    table: Table,
    scale: float,
) -> bool:
    """试排：该档位下「标题 + 表格」能否收进一页（落临时文件数页数）。"""
    top_margin = max(18.0, 31 * scale)
    bottom_margin = max(16.0, 30 * scale)

    doc = SimpleDocTemplate(
        "/tmp/_msds_fits_probe.pdf", pagesize=A4,
        leftMargin=51.3, rightMargin=51.3,
        topMargin=top_margin, bottomMargin=bottom_margin,
    )
    try:
        doc.build([title, table])
    except Exception:
        # 单个 Flowable 本身高过一页（极端长文）→ 该档位判不放
        return False
    import os

    try:
        from pypdf import PdfReader

        pages = len(PdfReader("/tmp/_msds_fits_probe.pdf").pages)
    except ImportError:
        # pypdf 缺失时退回文件大小启发式（不精确兜底）
        pages = 1 if os.path.getsize("/tmp/_msds_fits_probe.pdf") < 65536 else 2
    finally:
        try:
            os.unlink("/tmp/_msds_fits_probe.pdf")
        except OSError:
            pass
    return pages <= 1


def build_standard_msds_pdf(entry: dict, output_path: str) -> str:
    """将单条 28 字段填充为企业标准 PDF，**强制收进单页**（打印需求）。

    从参考版式 1.0 倍起步逐档缩小字号重排（版式/列宽不变），直到整表
    收进一页；最小档仍放不下时逐级截断超长内容（保号留「…截断」标记，
    完整全文永远在飞书台账行里）。

    Args:
        entry: AI 提取的单化学品 28 字段 dict
        output_path: 输出 pdf 路径
    """
    parts: tuple[Paragraph, Table] | None = None
    scale = _SCALE_STEPS[-1]
    for step in _SCALE_STEPS:
        style = _scaled_styles(step)
        parts = _build_parts(entry, style)
        if _fits_one_page(parts[0], parts[1], step):
            scale = step
            break
        if step == _SCALE_STEPS[-1]:
            # 最小档放不下：内容截断逐级加倍直到收进一页（极端长文安全阀）
            for cut in (800, 400, 200, 100, 50):
                clipped = _clip_entry(entry, cut)
                parts = _build_parts(clipped, style)
                if _fits_one_page(parts[0], parts[1], step):
                    logger.warning(
                        "MSDS PDF 内容超长已截断(每字段≤%d字): %s", cut, entry.get("name")
                    )
                    break
    title, table = parts  # type: ignore[misc]
    top_margin = max(18.0, 31 * scale)
    bottom_margin = max(16.0, 30 * scale)
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=51.3, rightMargin=51.3,
        topMargin=top_margin, bottomMargin=bottom_margin,
        title="化学品安全技术说明书（MSDS）",
        author="DAZAH 安全模块",
    )
    doc.build([title, table])
    logger.info(
        "MSDS 标准 PDF 已生成(单页自适应 scale=%.2f): %s", scale, output_path
    )
    return output_path


def _build_parts(entry: dict, style: dict[str, ParagraphStyle]) -> tuple[Paragraph, Table]:
    """组装流内容：返回（标题, 主表格）。样式由单页自适应档位注入。"""
    def st_body(text: str) -> Paragraph:
        return Paragraph(_esc(text), style["body"])

    def st_label(text: str) -> Paragraph:
        return Paragraph(_esc(text), style["label"])

    def st_label_top(text: str) -> Paragraph:
        return Paragraph(_esc(text), style["label_top"])

    def st_value_top(text: str) -> Paragraph:
        return Paragraph(_esc(text), style["value_top"])

    # 预拆分组合字段
    section_parts: dict[str, dict[str, str]] = {}
    for section, field_key in _SECTION_FIELD.items():
        aliases = {
            a
            for _t in _SUB_LABEL_SPECS
            if _SUB_LABEL_SPECS[_t][0] == section
            for a in _SUB_LABEL_SPECS[_t][1]
        }
        section_parts[section] = _split_into_parts(entry.get(field_key) or "", list(aliases))

    # ① 理化特性 / OEL 两块内容
    phys_rows: list[list[str]] = []
    for pair in _PHYS_ROW_LABELS:
        items = [f"{lbl}：{_resolve(lbl, entry, section_parts)}" for lbl in pair if lbl]
        phys_rows.append(["  ".join(items)])
    oel_rows: list[str] = []
    for i in range(6):
        if i in _OEL_ROW_LABELS:
            lbl = _OEL_ROW_LABELS[i]
            oel_rows.append(f"{lbl}：{_resolve(lbl, entry, section_parts)}")
        else:
            oel_rows.append("")

    # ② 大块内容（左：健康危害/急救/接触控制；右：稳定性/泄漏/消防/废弃）
    health = entry.get("health_hazard") or ""
    left_block = _block_cell("健康危害", [f"● {health}"] if health else [], style["body"])
    first_aid_lines = _bullet_lines("急救措施", entry, section_parts)
    if first_aid_lines:
        left_block = Paragraph(
            left_block.text + "<br/><br/>" + _section_header("急救措施") + "<br/>"
            + "<br/>".join(_esc(line) for line in first_aid_lines),
            style["body"],
        )
    exposure_lines = _bullet_lines("接触控制/个体防护", entry, section_parts)
    if exposure_lines:
        left_block = Paragraph(
            left_block.text + "<br/><br/>" + _section_header("接触控制/个体防护") + "<br/>"
            + "<br/>".join(_esc(line) for line in exposure_lines),
            style["body"],
        )

    right_block = _block_cell("稳定性和反应性", _bullet_lines("稳定性和反应性", entry, section_parts), style["body"])
    for section in ("泄漏应急处理", "消防措施", "废弃处置"):
        lines = _bullet_lines(section, entry, section_parts)
        if lines:
            right_block = Paragraph(
                right_block.text + "<br/><br/>" + _section_header(section) + "<br/>"
                + "<br/>".join(_esc(line) for line in lines),
                style["body"],
            )

    # ③ 操作处置与储存注意事项
    handling_lines = _bullet_lines("操作处置与储存注意事项", entry, section_parts)
    handling_text = "<br/>".join(_esc(line) for line in handling_lines) if handling_lines else ""

    # ④ 组装表格（6 列：左标签20 + 顶行标签延伸40 + 左内容186.65 + 右标签20 + 右标签延伸40 + 右内容186.65）
    name = entry.get("name") or ""
    formula = entry.get("molecular_formula") or ""
    un_no = entry.get("un_no") or ""
    cas_no = entry.get("cas_no") or ""
    hazard_statement = entry.get("hazard_statement") or ""
    label_elements = entry.get("label_elements") or ""

    # 顶部两行横排（对齐参考）
    table_data: list[list[object]] = [
        [st_label_top("名 称"), "", st_value_top(name), st_label_top("UN No"), "", st_value_top(un_no)],
        [st_label_top("分子式"), "", st_value_top(formula), st_label_top("CAS No"), "", st_value_top(cas_no)],
    ]
    # 危险性说明 / 标签要素（竖排标签 + 内容跨 2 列；内容放 SPAN 锚点列）
    table_data.append(
        [st_label("危险性说明"), st_body(hazard_statement), "", st_label("标签要素"), st_body(label_elements), ""]
    )
    # 理化特性(左) × 职业接触限值(右) 交错 6 行（标签竖排跨 6 行；内容放 SPAN 锚点列）
    for i in range(6):
        table_data.append(
            [
                "" if i else st_label("理化特性"),
                st_body(phys_rows[i][0]), "",
                "" if i else st_label("职业接触限值"),
                st_body(oel_rows[i]), "",
            ]
        )
    # 大块左右分栏 + 底部操作处置（内容放 SPAN 锚点列）
    table_data.append([left_block, "", "", right_block, "", ""])
    table_data.append([st_label("操作处置与储存注意事项"), Paragraph(handling_text, style["body"]), "", "", "", ""])

    title_para = Paragraph("MSDS 表", style["title"])
    return title_para, _build_table(table_data)


def _build_table(table_data: list[list[object]]) -> Table:
    """6 列 SPAN/GRID 版式（列宽/边距固定，缩字号即缩行数 → 高度自适应）。"""
    table = Table(table_data, colWidths=_COLS)
    spans = [
        # 顶部两行：标签横跨左/右标签+延伸列
        ("SPAN", (0, 0), (1, 0)), ("SPAN", (3, 0), (4, 0)),
        ("SPAN", (0, 1), (1, 1)), ("SPAN", (3, 1), (4, 1)),
        # 危险性说明行：内容横跨内容+延伸列
        ("SPAN", (1, 2), (2, 2)), ("SPAN", (4, 2), (5, 2)),
        # 理化特性/职业接触限值竖排标签跨 6 行
        ("SPAN", (0, 3), (0, 8)), ("SPAN", (3, 3), (3, 8)),
        # 左大块跨 3 列、右大块跨 3 列
        ("SPAN", (0, 9), (2, 9)), ("SPAN", (3, 9), (5, 9)),
        # 操作处置内容跨 5 列
        ("SPAN", (1, 10), (5, 10)),
    ]
    # 理化/OEL 内容行：每行内容跨 内容+延伸列
    for i in range(6):
        spans.append(("SPAN", (1, 3 + i), (2, 3 + i)))
        spans.append(("SPAN", (4, 3 + i), (5, 3 + i)))
    table.setStyle(
        TableStyle(
            spans
            + [
                ("GRID", (0, 0), (-1, -1), 0.48, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                # 竖排标签垂直居中
                ("VALIGN", (0, 2), (0, 2), "MIDDLE"),
                ("VALIGN", (3, 2), (3, 2), "MIDDLE"),
                ("VALIGN", (0, 3), (0, 8), "MIDDLE"),
                ("VALIGN", (3, 3), (3, 8), "MIDDLE"),
                ("VALIGN", (0, 10), (0, 10), "MIDDLE"),
                # 收紧单元格 padding，窄标签列留足可写宽度
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return table


def standard_pdf_filename(entry: dict, collection_id: str, idx: int) -> str:
    """标准 pdf 文件名（sanitized）。"""
    name = (entry.get("name") or "unknown").replace("/", "_").replace("\\", "_")
    cas = (entry.get("cas_no") or "no_cas").replace("/", "_").replace("\\", "_")
    return f"{name}_{cas}_{collection_id[:8]}_{idx}.pdf"
