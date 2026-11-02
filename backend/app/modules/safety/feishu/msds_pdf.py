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

# ── 复刻《丁醇；正丁醇.pdf》企业标准版式（2026-11-02 pdfplumber 客观测量）──
# 页面：A4 595.3×841.9，左 51.5 / 右 51.3；标题「MSDS表」36pt 居中（无空格）；
# 表格全宽 51.5→544.0（492.5pt），9 竖线 10 列：
_XS = [51.5, 71.2, 93.4, 129.6, 170.6, 201.8, 279.4, 300.7, 344.9, 544.0]
_COLS = [round(_XS[i + 1] - _XS[i], 2) for i in range(len(_XS) - 1)]
#  = [19.7, 22.2, 36.2, 41.0, 31.2, 77.6, 21.3, 44.2, 199.1]
# 关键结构：
#  - 顶行 2 行（黑体 12pt 全居中）：[0-2 名称|3-5 值][6-7 UN No|8 值]
#  - 危标行：[0 竖排危险性说明 | 1-5 内容][6 竖排标签要素 | 7-8 内容(象形图)]
#  - 理化 6 行：[0 竖排理化特性跨6行 | 行1-2 整格 / 行3-5 分界170.6 / 行6 分界201.8]
#               [6 竖排职业接触限值跨6行 | 7-8 OEL 三行]
#  - 大块行：左[0-5](227.9pt 窄) 右[6-8](264.6pt 宽)——右宽左窄
#  - 操作行：[0-1 竖排标签 | 2-8 内容]（无 ●，段落式）

# 理化特性 6 行的左栏子项（模板标签，直接字段；每行最多两个并排）
# 「外观与性状」为 GB/T 16483 标准术语（2026-10-30 修正历史错别字「外观与现状」）
# 「相对密度（空）」照抄参考《丁醇》模板字面（疑为「空气」缺字，业务确认中）
_PHYS_ROW_LABELS: list[tuple[str, str | None]] = [
    ("外观与性状", None),
    ("溶解性", None),
    ("熔点", "闪点"),
    ("沸点", "相对密度（空）"),
    ("爆炸上限(%)", "爆炸下限(%)"),
    ("自燃温度", "分解温度"),
]

# 竖排标签行距（参考测量：字列居中成团，跨 6 行大标签近似撑满）；
# 随单页自适应档位整体缩放
_VERTICAL_LEADING: dict[str, float] = {
    "危险性说明": 13.0, "标签要素": 15.0,
    "理化特性": 22.0, "职业接触限值": 15.0,
    "操作处置与储存注意事项": 8.0,
}

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
    # m3 单位上标（参考实测 5.8pt 上标：100mg/m3 → 100mg/m³；转义后注入防二次转义）
    s = re.sub(r"([mg]/m)3\b", r"\1<sup>3</sup>", s)
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
        "body": ParagraphStyle("msds_body", fontName=_FONT, fontSize=body, leading=12 * scale, wordWrap="CJK"),
        "section_head": ParagraphStyle(
            "msds_section_head", fontName=heiti, fontSize=body, leading=12 * scale,
            alignment=TA_CENTER, spaceBefore=6 * scale,
        ),
        "heiti": ParagraphStyle("msds_heiti", fontName=heiti, fontSize=body, leading=12 * scale, wordWrap="CJK"),
        "signal": ParagraphStyle(
            "msds_signal", fontName=heiti, fontSize=body, leading=12 * scale,
            alignment=TA_CENTER, spaceBefore=2 * scale,
        ),
        "ghs_pt": 36 * scale,
        "scale": scale,  # type: ignore[dict-item]
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
    """组装流内容（复刻《丁醇；正丁醇.pdf》网格）：返回（标题, 主表格）。

    9 列网格布局见 _XS 注释；行内 SPAN 见 _build_table。
    """
    scale = style["scale"]

    def st_body(text: str) -> Paragraph:
        return Paragraph(_rich_markup(text), style["body"])

    def st_label(text: str) -> Paragraph:
        """竖排标签：逐字一行，行距按参考测量表（随档位缩放），垂直居中。"""
        lead = _VERTICAL_LEADING.get(text, 12.0) * scale
        vs = ParagraphStyle(
            f"v_{text[:2]}", fontName=style["label"].fontName,
            fontSize=style["label"].fontSize, leading=lead, wordWrap="CJK",
        )
        return Paragraph("<br/>".join(_esc(ch) for ch in text), vs)

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
        # 象形图格宽 = col7+col8 = 44.2+199.1 = 243.3
        inner = Table(
            rows, colWidths=[243.3 / 4] * min(4, len(imgs)), hAlign="CENTER",
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

    def _section_cell(header: str, body_paras: list) -> list:
        return [Paragraph(_esc(header), style["section_head"]), *body_paras]

    def _bullet(text: str) -> Paragraph:
        """● 行：悬挂缩进 21pt（参考 x56.8→77.8）。"""
        bs = ParagraphStyle(
            f"b_{style['body'].fontSize}", parent=style["body"],
            leftIndent=21 * scale, firstLineIndent=-21 * scale,
        )
        return Paragraph(_rich_markup(text), bs)

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

    # ② 大块：左列 5 节（健康危害→环境危害→急救→接触控制→稳定性），
    #    右列 3 节（泄漏→消防→废弃）——复刻参考编排
    left_cells: list = []
    for header, field_key in (
        ("健康危害", "health_hazard"), ("环境危害", "environmental_hazard"),
    ):
        v = entry.get(field_key) or ""
        if v:
            left_cells.extend(_section_cell(header, [_bullet(f"● {v}")]))

    for section in ("急救措施", "接触控制/个体防护", "稳定性和反应性"):
        lines_ = _bullet_lines(section, entry, section_parts)
        if lines_:
            left_cells.extend(_section_cell(header=section, body_paras=[_bullet(ln) for ln in lines_]))

    right_cells: list = []
    for section in ("泄漏应急处理", "消防措施", "废弃处置"):
        lines_ = _bullet_lines(section, entry, section_parts)
        if lines_:
            right_cells.extend(_section_cell(header=section, body_paras=[_bullet(ln) for ln in lines_]))

    # ③ 操作处置与储存注意事项：段落式无 ●（参考版式）
    hs_parts = section_parts.get("操作处置与储存注意事项", {})
    handling_paras: list[Paragraph] = []
    for lbl, aliases in (
        ("操作注意事项", ("操作注意事项",)),
        ("储存注意事项", ("储存注意事项", "储存事项")),
    ):
        seg = next((v for k, v in hs_parts.items() if any(a == k for a in aliases)), None)
        if seg:
            handling_paras.append(st_body(f"{lbl}：{seg}"))
    if not handling_paras:
        raw = (entry.get("handling_storage") or "").strip()
        if raw:
            handling_paras.append(st_body(raw))

    # ④ 组装 9 列 × 11 行网格
    name = entry.get("name") or ""
    formula = entry.get("molecular_formula") or ""
    un_no = entry.get("un_no") or ""
    cas_no = entry.get("cas_no") or ""
    hazard_statement = entry.get("hazard_statement") or ""
    label_elements = entry.get("label_elements") or ""

    grid: list[list[object]] = []
    # r0/r1 顶行两行（黑体 12pt 居中）
    grid.append([st_label_top("名 称"), "", "", st_value_top(name), "", "", st_label_top("UN No"), "", st_value_top(un_no)])
    grid.append([st_label_top("分子式"), "", "", Paragraph(_formula_markup(formula), style["value_top"]), "", "", st_label_top("CAS No"), "", st_value_top(cas_no)])
    # r2 危险性说明 / 标签要素
    grid.append([st_label("危险性说明"), st_body(hazard_statement), "", "", "", "", st_label("标签要素"), _ghs_cell(label_elements) or "", ""])
    # r3-r8 理化 6 行（左内容两格分界随行变化 + 右 OEL）；
    # 竖排标签锚在 r3（SPAN 覆盖 r3-r8）
    for i in range(6):
        if i < 2:  # 外观/溶解：整格 col1-5
            left = [st_body(phys_rows[i][0]), "", "", "", ""]
        elif i < 5:  # 熔闪/沸密/爆炸：col1-3 + col4-5（分界 170.6）
            pair = phys_rows[i][0].split("  ", 1)
            left = [st_body(pair[0]), "", "", st_body(pair[1] if len(pair) > 1 else ""), ""]
        else:  # 自燃/分解：col1-4 + col5（分界 201.8）
            pair = phys_rows[i][0].split("  ", 1)
            left = [st_body(pair[0]), "", "", "", st_body(pair[1] if len(pair) > 1 else "")]
        col0 = st_label("理化特性") if i == 0 else ""
        col6 = st_label("职业接触限值") if i == 0 else ""
        grid.append([col0] + left + [col6, st_body(oel_rows[i]), ""])
    # r9 大块：左 0-5 / 右 6-8
    grid.append([left_cells or "", "", "", "", "", "", right_cells or "", "", ""])
    # r10 操作处置：标签 0-1 / 内容 2-8（段落式无 ●）
    grid.append([st_label("操作处置与储存注意事项"), "", handling_paras or "", "", "", "", "", "", ""])

    title_para = Paragraph("MSDS表", style["title"])
    return title_para, _build_table(grid)


def _build_table(grid: list[list[object]]) -> Table:
    """9 列复刻网格的 SPAN/GRID（列界 _XS；局部竖线按参考 y 范围还原）。"""
    table = Table(grid, colWidths=_COLS)
    spans = [
        # 顶行两行：标签/值横跨
        ("SPAN", (0, 0), (2, 0)), ("SPAN", (3, 0), (5, 0)), ("SPAN", (6, 0), (7, 0)),
        ("SPAN", (0, 1), (2, 1)), ("SPAN", (3, 1), (5, 1)), ("SPAN", (6, 1), (7, 1)),
        # 危标行：内容横跨
        ("SPAN", (1, 2), (5, 2)), ("SPAN", (7, 2), (8, 2)),
        # 理化/职业接触限值竖排标签跨 6 行
        ("SPAN", (0, 3), (0, 8)), ("SPAN", (6, 3), (6, 8)),
        # 大块左右分栏
        ("SPAN", (0, 9), (5, 9)), ("SPAN", (6, 9), (8, 9)),
        # 操作处置标签跨 2 列、内容跨 7 列
        ("SPAN", (0, 10), (1, 10)), ("SPAN", (2, 10), (8, 10)),
    ]
    # 理化 6 行内容跨列（分界随行：r3/r4 整格；r5-r7 分界 col3|4；r8 分界 col4|5）
    for i in range(6):
        r = 3 + i
        spans.append(("SPAN", (7, r), (8, r)))  # OEL 内容
        if i < 2:
            spans.append(("SPAN", (1, r), (5, r)))
        elif i < 5:
            spans.append(("SPAN", (1, r), (3, r)))
            spans.append(("SPAN", (4, r), (5, r)))
        else:
            spans.append(("SPAN", (1, r), (4, r)))
    table.setStyle(
        TableStyle(
            spans
            + [
                ("GRID", (0, 0), (-1, -1), 0.48, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                # 竖排标签垂直居中
                ("VALIGN", (0, 2), (0, 2), "MIDDLE"),
                ("VALIGN", (6, 2), (6, 2), "MIDDLE"),
                ("VALIGN", (0, 3), (0, 8), "MIDDLE"),
                ("VALIGN", (6, 3), (6, 8), "MIDDLE"),
                ("VALIGN", (0, 10), (1, 10), "MIDDLE"),
                # 收紧单元格 padding
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
