"""MSDS 标准 PDF 生成器 — 复刻《无水硫酸镁；泻盐MSDS.pdf》企业格式。

输出 A4 纵向 PDF，单页自适应：以 1.0 缩放（标题 36pt/顶行 12pt/正文 9pt）
试排，量出的总高超出可用页高时按比例整体缩小字号重排，直到收进一页
（打印要求；下限 0.67 防长文病态缩到不可读，再放不下走内容截断安全阀）。

格式基线对齐 docx 模板（msds_standard_template.docx，2026-11-02 实测格式）：
  - 顶部两行（名 称/分子式/UN No/CAS No 及值）：**黑体加粗居中**（NotoSansSC，
    复用 assets/fonts/NotoSansSC.ttf，缺字体环境回退 STSong-Light）
  - 大块节标题（健康危害/急救措施/…）：独立段落**黑体居中**
  - 健康危害内容：黑体左对齐（模板 bold+黑体）
  - 其余正文 9pt STSong-Light

文本规范化 `_rich_markup`（分子式修复，2026-11-02）：STSong-Light 无
U+208x/U+207x 字形，MgSO₄/MnO₂/m³ 等直接渲染丢字（「台账字段对、PDF 错」
根因）→ Unicode 下标/上标字符统一转 <sub>/<sup> 标记渲染，零宽字符删除。

共享 msds_docx 的标签映射与组合字段拆分逻辑（_DIRECT_LABEL_TO_FIELD /
_SUB_LABEL_SPECS / _SECTION_FIELD / _resolve_value / _split_into_parts）。
"""

from __future__ import annotations

import html
import logging
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Table, TableStyle

from app.modules.safety.feishu.msds_docx import (
    _SECTION_FIELD,
    _SUB_LABEL_SPECS,
    _resolve_value,
    _split_into_parts,
)

logger = logging.getLogger(__name__)

pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
_FONT = "STSong-Light"

# 黑体（Noto Sans SC Medium 静态实例）：顶部表头/节标题/健康危害内容用。
# **必须用静态实例**（assets/fonts/NotoSansSC-Medium.ttf，fontTools instancer
# wght=500 产出）：仓库原 NotoSansSC.ttf 是可变字体（fvar，默认实例 wght=100
# Thin）——reportlab 不支持 VF，按 100 极细渲染（业务反馈"淡黑色"）且子集
# 嵌入在部分阅读器字形错乱（"UN 号乱码"）。缺静态字体环境回退 STSong-Light。
_HEITI = "STSong-Light"


def _register_heiti() -> str:
    global _HEITI
    if _HEITI != "STSong-Light":
        return _HEITI
    candidates = (
        Path("assets/fonts/NotoSansSC-Medium.ttf"),
        Path(__file__).resolve().parents[4] / "assets" / "fonts" / "NotoSansSC-Medium.ttf",
    )
    for p in candidates:
        if p.exists():
            try:
                pdfmetrics.registerFont(TTFont("NotoSansSC", str(p)))
                _HEITI = "NotoSansSC"
                break
            except Exception:
                logger.warning("NotoSansSC-Medium 注册失败, 黑体回退 STSong-Light", exc_info=True)
    return _HEITI


_register_heiti()

# GHS 象形图（UN 官方图形，公有领域；assets/ghs/，2026-11-02 业务要求标签要素
# 以图片形式体现）。名称 = derive_label_elements 的图形名，缺图自动跳过。
_GHS_PICTOGRAMS: dict[str, str] = {
    "爆炸": "ghs01-explosion.png",
    "火焰": "ghs02-flame.png",
    "火焰加圆圈": "ghs03-flame-circle.png",
    "气瓶": "ghs04-gas-cylinder.png",
    "腐蚀": "ghs05-corrosion.png",
    "骷髅和交叉骨": "ghs06-skull.png",
    "感叹号": "ghs07-exclamation.png",
    "健康危害": "ghs08-health-hazard.png",
    "环境": "ghs09-environment.png",
}


def _ghs_asset(name: str) -> Path | None:
    for d in (Path("assets/ghs"), Path(__file__).resolve().parents[4] / "assets" / "ghs"):
        p = d / name
        if p.exists():
            return p
    return None

# 缩放档位：内容多时先缩字号行距；下限 0.67 仍放不下走截断安全阀
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

# ── 文本规范化（分子式/单位上下标修复）────────────────────────────────

# Unicode 下标数字（U+2080-2089）→ ASCII 数字
_SUBSCRIPT_MAP = {chr(0x2080 + i): str(i) for i in range(10)}
# 常见 Unicode 上标（数字/正负/n）→ ASCII
_SUPERSCRIPT_MAP = {
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
    "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
    "⁺": "+", "⁻": "−", "ⁿ": "n",
}
_INVISIBLE_RE = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")
# CJK 字符类：汉字 + CJK 标点（。，、；）+ 全角形式（（）：？！％）+ 中英文引号
_CJK_CLASS = r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\u201c-\u201d’‘]"
# CJK↔CJK 之间的空白（含换行）：供应商 PDF 断行残留（「刺 激」「建 议」类）
_CJK_GAP_RE = re.compile(rf"(?<={_CJK_CLASS})[\s\u3000]+(?={_CJK_CLASS})")
# CJK 之间的半角标点 → 全角：任一侧是 CJK 即转（中文句子中标点后接拉丁也该
# 全角，如「非常大,L」）；两侧都是数字/拉丁不动（3.5、13:00、1,2-丙二醇安全）
_HALF_TO_FULL = {
    ",": "，", ";": "；", ":": "：", "?": "？", "!": "！",
}
_HALF_FULL_RES = [
    (re.compile(rf"(?<={_CJK_CLASS}){re.escape(half)}"), full)
    for half, full in _HALF_TO_FULL.items()
] + [
    (re.compile(rf"{re.escape(half)}(?={_CJK_CLASS})"), full)
    for half, full in _HALF_TO_FULL.items()
]
# 半角双引号全角化（配对状态机：奇数个 " 交替 “/”）。中文排版规范 +
# 消除 STSong 对 U+0022 的字形/ToUnicode 歧义（提取器读出 `";` 的根源之一）。
def _normalize_quotes(s: str) -> str:
    out: list[str] = []
    open_q = False
    for ch in s:
        if ch == "“":
            out.append("“")
            open_q = True
        elif ch == "”":
            out.append("”")
            open_q = False
        elif ch == '"':
            out.append("”" if open_q else "“")
            open_q = not open_q
        else:
            out.append(ch)
    return "".join(out)


def _rich_markup(value: str) -> str:
    """XML 转义 + 中文排版规范化（所有单元格文本统一入口）。

    - 上下标：STSong-Light/NotoSansSC 均无下标字形（MgSO₄ 渲染丢字根因），
      连续下标字符 → <sub>12</sub>；上标字符 → <sup>3</sup>（mg/m³ 类）
    - 零宽字符（\u200b 等，AI 提取残留）删除
    - CJK 之间空白删除：供应商 PDF 断行残留（「刺\\n激」「建 议」类断词）
    - CJK 之间半角标点全角化（,;:?! → 全角；数字/拉丁间不动）
    标记由本函数生成，无注入面。
    """
    # ① 文本规范化（必须在 escape 前：escape 实体 &quot; 的 ";" 会被全角化破坏）
    s = _INVISIBLE_RE.sub("", value or "")
    s = _CJK_GAP_RE.sub("", s)
    for pattern, full in _HALF_FULL_RES:
        s = pattern.sub(full, s)
    s = _normalize_quotes(s)
    # ② XML 转义（只转 &<>；裸 " 已全角化，reportlab 属性外文本无需转义）
    s = html.escape(s, quote=False)
    out: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch in _SUBSCRIPT_MAP:
            digits: list[str] = []
            while i < len(s) and s[i] in _SUBSCRIPT_MAP:
                digits.append(_SUBSCRIPT_MAP[s[i]])
                i += 1
            out.append("<sub>" + "".join(digits) + "</sub>")
        elif ch in _SUPERSCRIPT_MAP:
            digits = []
            while i < len(s) and s[i] in _SUPERSCRIPT_MAP:
                digits.append(_SUPERSCRIPT_MAP[s[i]])
                i += 1
            out.append("<sup>" + "".join(digits) + "</sup>")
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _esc(value: str) -> str:
    """转义 XML 实体，安全嵌入 reportlab Paragraph 标记。"""
    return html.escape(value or "")


# 分子式普通数字下标：字母/右括号后的数字串（C2H6O → C₂H₆O 视觉形态）；
# 行首系数（2H2O 的 2）与中文/标点后的数字（“闪点 11℃”）不动
_FORMULA_DIGIT_RE = re.compile(r"(?<=[A-Za-z\)])\d+")


def _formula_markup(value: str) -> str:
    """分子式专用渲染：_rich_markup 基础上把字母后的普通数字转下标。

    台账分子式两种形态并存（MgSO₄ Unicode 下标 / C2H6O 普通数字），后者
    渲染成全大数字（业务反馈"识别成大数字"）——统一转 <sub> 下标形态。
    """
    s = _rich_markup(value)
    parts = re.split(r"(<sub>[^<]*</sub>|<sup>[^<]*</sup>)", s)
    out: list[str] = []
    for tok in parts:
        if tok.startswith(("<sub>", "<sup>")):
            out.append(tok)
        else:
            out.append(_FORMULA_DIGIT_RE.sub(r"<sub>\g<0></sub>", tok))
    return "".join(out)


def _parse_label_elements(text: str) -> tuple[list[str], str]:
    """解析标签要素文本 → (GHS 图形名列表, 信号词)。

    兼容人工填写：图形段按 、,， 切分后按标准图形名子串匹配；
    无图形段/全部无图时返回 ([], "")，调用方回退纯文本渲染。
    """
    if not text:
        return [], ""
    names: list[str] = []
    m = re.search(r"图形[：:](.+?)(?:[；;]|$)", text)
    if m:
        for part in re.split(r"[、,，]", m.group(1)):
            p = part.strip()
            for key in _GHS_PICTOGRAMS:
                if key in p:
                    if key not in names:
                        names.append(key)
                    break
    sig = ""
    m2 = re.search(r"信号词[：:]\s*(危险|警告)", text)
    if m2:
        sig = m2.group(1)
    return names, sig


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


# ── 主入口 ────────────────────────────────────────────────────────────


def _clip_entry(entry: dict, limit: int) -> dict:
    """极端长文安全阀：每个文本字段截到 limit 字（保号 + …截断 标记）。"""
    clipped: dict = {}
    for k, v in entry.items():
        if isinstance(v, str) and len(v) > limit:
            clipped[k] = v[:limit].rstrip() + "…截断"
        else:
            clipped[k] = v
    return clipped


def _scaled_styles(scale: float) -> dict[str, ParagraphStyle]:
    """按缩放系数派生整套样式（黑体档位差压平，正文线性缩）。

    label_top/value_top：顶部表头标签与值——黑体居中（模板 bold+黑体+居中）；
    value_top 带 CJK 折行（长 UN 值如"2672（含氨量10%-35%）；2073…"不溢出）。
    section_head：大块节标题——黑体居中独立段。heiti：健康危害内容——黑体左对齐。
    signal：标签要素信号词——黑体居中。ghs_pt：象形图边长（随档位缩放）。
    """
    heiti = _HEITI
    title = ParagraphStyle(
        "msds_title", fontName=_FONT,
        fontSize=round(36 * scale), leading=42 * scale, alignment=1,
        spaceAfter=8 * scale,
    )
    top = round(12 * scale, 1)
    body = round(9 * scale, 2)
    return {
        "title": title,
        "label_top": ParagraphStyle(
            "msds_label_top", fontName=heiti, fontSize=top, leading=16 * scale,
            alignment=TA_CENTER,
        ),
        "value_top": ParagraphStyle(
            "msds_value_top", fontName=heiti, fontSize=top, leading=16 * scale,
            alignment=TA_CENTER, wordWrap="CJK",
        ),
        "label": ParagraphStyle("msds_label", fontName=_FONT, fontSize=body, leading=12 * scale, wordWrap="CJK"),
        "body": ParagraphStyle("msds_body", fontName=_FONT, fontSize=body, leading=13 * scale, wordWrap="CJK"),
        "section_head": ParagraphStyle(
            "msds_section_head", fontName=heiti, fontSize=body, leading=13 * scale,
            alignment=TA_CENTER, spaceBefore=4 * scale,
        ),
        "heiti": ParagraphStyle("msds_heiti", fontName=heiti, fontSize=body, leading=13 * scale, wordWrap="CJK"),
        "signal": ParagraphStyle(
            "msds_signal", fontName=heiti, fontSize=body, leading=13 * scale,
            alignment=TA_CENTER, spaceBefore=2 * scale,
        ),
        "ghs_pt": 40 * scale,
    }


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
        return Paragraph(_rich_markup(text), style["body"])

    def st_label(text: str) -> Paragraph:
        """竖排标签：显式逐字一行（窄列自动断行会把 5-11 字标签折成两列，
        「危险性说明」折成『危险性说/明』两列的排版事故根因）。"""
        return Paragraph("<br/>".join(_esc(ch) for ch in text), style["label"])

    def st_label_top(text: str) -> Paragraph:
        return Paragraph(_esc(text), style["label_top"])

    def st_value_top(text: str) -> Paragraph:
        return Paragraph(_rich_markup(text), style["value_top"])

    def _ghs_cell(label_elements: str) -> list:
        """标签要素格：GHS 象形图网格（4/行）+ 信号词；无图回退纯文本。"""
        names, sig = _parse_label_elements(label_elements)
        pt = style["ghs_pt"]
        imgs = []
        for n in names:
            p = _ghs_asset(_GHS_PICTOGRAMS[n])
            if p:
                imgs.append(Image(str(p), width=pt, height=pt))
        if not imgs:
            return [st_body(label_elements)] if label_elements else []
        rows = [imgs[i:i + 4] for i in range(0, len(imgs), 4)]
        inner = Table(
            rows, colWidths=[(_COL_LABEL_WIDE + _COL_CONTENT) / 4] * min(4, len(imgs)),
            hAlign="CENTER",
        )
        inner.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        cells: list = [inner]
        if sig:
            cells.append(Paragraph(f"信号词：{_esc(sig)}", style["signal"]))
        return cells

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
    #    单元格为 Flowable 列表：每节标题独立段（黑体居中，对齐 docx 模板）
    def _section_cell(header: str, body_paras: list[Paragraph]) -> list:
        return [Paragraph(_esc(header), style["section_head"]), *body_paras]

    left_cells: list = []
    health = entry.get("health_hazard") or ""
    if health:
        # 健康危害内容黑体（模板 bold+黑体）
        left_cells.extend(_section_cell("健康危害", [Paragraph(_rich_markup(f"● {health}"), style["heiti"])]))
    # 环境危害（GB/T 16483 与健康危害相邻；参考模板无此格，字段有值即渲染，
    # 内容完整性 2026-11-02 审计补）
    environmental = entry.get("environmental_hazard") or ""
    if environmental:
        left_cells.extend(_section_cell(
            "环境危害", [Paragraph(_rich_markup(f"● {environmental}"), style["body"])],
        ))
    first_aid_lines = _bullet_lines("急救措施", entry, section_parts)
    if first_aid_lines:
        left_cells.extend(_section_cell(
            "急救措施", [Paragraph(_rich_markup(line), style["body"]) for line in first_aid_lines],
        ))
    exposure_lines = _bullet_lines("接触控制/个体防护", entry, section_parts)
    if exposure_lines:
        left_cells.extend(_section_cell(
            "接触控制/个体防护", [Paragraph(_rich_markup(line), style["body"]) for line in exposure_lines],
        ))

    right_cells: list = []
    stability_lines = _bullet_lines("稳定性和反应性", entry, section_parts)
    if stability_lines:
        right_cells.extend(_section_cell(
            "稳定性和反应性", [Paragraph(_rich_markup(line), style["body"]) for line in stability_lines],
        ))
    for section in ("泄漏应急处理", "消防措施", "废弃处置"):
        lines = _bullet_lines(section, entry, section_parts)
        if lines:
            right_cells.extend(_section_cell(
                section, [Paragraph(_rich_markup(line), style["body"]) for line in lines],
            ))

    # ③ 操作处置与储存注意事项
    handling_lines = _bullet_lines("操作处置与储存注意事项", entry, section_parts)
    handling_text = "<br/>".join(_rich_markup(line) for line in handling_lines) if handling_lines else ""

    # ④ 组装表格（6 列：左标签20 + 顶行标签延伸40 + 左内容186.65 + 右标签20 + 右标签延伸40 + 右内容186.65）
    name = entry.get("name") or ""
    formula = entry.get("molecular_formula") or ""
    un_no = entry.get("un_no") or ""
    cas_no = entry.get("cas_no") or ""
    hazard_statement = entry.get("hazard_statement") or ""
    label_elements = entry.get("label_elements") or ""

    # 顶部两行横排：标签与值黑体居中（对齐参考）
    table_data: list[list[object]] = [
        [st_label_top("名 称"), "", st_value_top(name), st_label_top("UN No"), "", st_value_top(un_no)],
        [st_label_top("分子式"), "", Paragraph(_formula_markup(formula), style["value_top"]), st_label_top("CAS No"), "", st_value_top(cas_no)],
    ]
    # 危险性说明 / 标签要素（竖排标签 + 内容跨 2 列；内容放 SPAN 锚点列；
    #   标签要素 = GHS 象形图网格 + 信号词，2026-11-02 业务要求图片形式）
    table_data.append(
        [st_label("危险性说明"), st_body(hazard_statement), "", st_label("标签要素"), _ghs_cell(label_elements) or "", ""]
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
    # 大块左右分栏 + 底部操作处置（内容放 SPAN 锚点列；空列表置 ""）
    table_data.append([left_cells or "", "", "", right_cells or "", "", ""])
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
