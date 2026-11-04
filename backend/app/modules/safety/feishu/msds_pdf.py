"""MSDS 标准 PDF 生成器 — 参考件《丁醇；正丁醇.pdf》企业版式 1:1 复刻。

2026-11-03 起改用**绝对坐标画布**渲染（原 platypus 版本不再使用）：

- 版心与参考件一致：A4 595.3×841.9；表格左 51.5 / 右 544.0；标题「MSDS 表」
  36pt 黑体居中；10 条竖线、6 行理化特性、左右分栏（左窄右宽）与末尾
  「操作处置与储存注意事项」通栏行均按参考件 pdfplumber 实测坐标落笔。
- 标签要素：按「图形/象形图/图标」文本或危险性说明推导 GHS 象形图，
  57.8pt/枚、3 枚一行、在格内居中（参考件同尺寸同位置）；无图回退文字。
- 竖排标签：逐字一行、行距 12pt、垂直居中；「操作处置与储存注意事项」
  按参考件 4 字一行。
- 正文 9pt / 行距 12pt（宋体 STSong-Light）；标题与表头/节标题用粗体
  （宋体描边模拟，标题用 Noto Sans SC）。
- 单页自适应：内容过长时按档位整体缩字号（1.0→0.68），仍放不下时按
  字段截断兜底（保号 + 「…截断」），确保永远单页（打印要求）。
- 2026-11-03 突出修复：行高下限强制容纳竖排栏目标签（危险性说明 5 行、
  操作处置与储存 4 行、UN 值 2 行）；闭合标点追い出し不再悬挂出格；
  UN No 占位值 NA/N.A./none 显示「无」。

公共 API 保持：``build_standard_msds_pdf(entry, output_path)``、
``standard_pdf_filename(entry, collection_id, idx)``。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from app.modules.safety.feishu.msds_docx import (
    _SECTION_FIELD,
    _SUB_LABEL_SPECS,
    _split_into_parts,
)

logger = logging.getLogger(__name__)

# ── 字体 ──────────────────────────────────────────────────────────────
pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
BODY_FONT = "STSong-Light"
HEITI_FONT = BODY_FONT


def _asset_dir(name: str) -> Path | None:
    for base in (Path("assets"), Path(__file__).resolve().parents[4] / "assets"):
        d = base / name
        if d.exists():
            return d
    return None


_font_dir = _asset_dir("fonts")
if _font_dir is not None:
    try:
        pdfmetrics.registerFont(TTFont("NotoSansSC", str(_font_dir / "NotoSansSC-Medium.ttf")))
        HEITI_FONT = "NotoSansSC"
    except Exception:  # pragma: no cover - 字体缺失降级
        logger.warning("NotoSansSC-Medium 注册失败, 标题回退 STSong-Light", exc_info=True)

# ── GHS 象形图 ────────────────────────────────────────────────────────
_GHS = {
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
_GHS_ORDER = ["爆炸", "火焰", "火焰加圆圈", "气瓶", "骷髅和交叉骨", "感叹号", "腐蚀", "健康危害", "环境"]
_GHS_ALIAS = {
    "易燃": "火焰", "氧化性": "火焰加圆圈", "氧化": "火焰加圆圈",
    "有毒": "骷髅和交叉骨", "剧毒": "骷髅和交叉骨",
    "刺激": "感叹号", "有害": "感叹号",
    "致癌": "健康危害", "生殖毒性": "健康危害",
    "水生": "环境", "压缩气体": "气瓶", "腐蚀性": "腐蚀",
}

# ── 版式常量（参考件实测）────────────────────────────────────────────
PAGE_W, PAGE_H = 595.28, 841.89
XS = [51.5, 71.2, 93.4, 129.6, 170.6, 201.8, 279.4, 300.7, 344.9, 544.0]
Y0 = 66.8          # 表格上边线
Y_MAX = 778.2      # 表格下边线（内容可短于该值，单页上限）
AVAIL = Y_MAX - Y0
SCALES = (1.0, 0.96, 0.92, 0.88, 0.84, 0.80, 0.76, 0.72, 0.68)

# 理化特性 6 行的左右分界（参考件：前两行整格，3-5 行分界 170.6，第 6 行 201.8）
_PHYS_CFG = [
    [(XS[1], XS[6])],
    [(XS[1], XS[6])],
    [(XS[1], XS[4]), (XS[4], XS[6])],
    [(XS[1], XS[4]), (XS[4], XS[6])],
    [(XS[1], XS[4]), (XS[4], XS[6])],
    [(XS[1], XS[5]), (XS[5], XS[6])],
]

# Unicode 上下标 / 罗马数字 → 可渲染字符（STSong-Light 无上下标字形）
_NORMALIZE_MAP = str.maketrans({
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5", "₆": "6",
    "₇": "7", "₈": "8", "₉": "9", "⁰": "0", "¹": "1", "²": "2", "³": "3",
    "⁴": "4", "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
    "Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV", "Ⅴ": "V",
})


_CJK_CLASS = r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\u201c-\u201d’‘]"
_CJK_GAP_RE = re.compile(rf"(?<={_CJK_CLASS})[\s\u3000]+(?={_CJK_CLASS})")
_HALF_TO_FULL = {",": "，", ";": "；", ":": "：", "?": "？", "!": "！"}
_HALF_FULL_RES = [
    (re.compile(rf"(?<={_CJK_CLASS}){re.escape(half)}"), full)
    for half, full in _HALF_TO_FULL.items()
] + [
    (re.compile(rf"{re.escape(half)}(?={_CJK_CLASS})"), full)
    for half, full in _HALF_TO_FULL.items()
]


def _normalize_quotes(s: str) -> str:
    out: list[str] = []
    open_q = False
    for ch in s:
        if ch == "“":
            out.append("“"); open_q = True
        elif ch == "”":
            out.append("”"); open_q = False
        elif ch == '"':
            out.append("”" if open_q else "“"); open_q = not open_q
        else:
            out.append(ch)
    return "".join(out)


def _norm(text: str | None) -> str:
    if not text:
        return ""
    s = str(text)
    s = _INVISIBLE_RE.sub("", s)
    s = _CJK_GAP_RE.sub("", s)
    for pattern, full in _HALF_FULL_RES:
        s = pattern.sub(full, s)
    s = _normalize_quotes(s)
    return s.translate(_NORMALIZE_MAP).strip()


def _sw(text: str, font: str, size: float) -> float:
    return pdfmetrics.stringWidth(text, font, size)


def _wrap(text: str, font: str, size: float, width: float) -> list[str]:
    """按宽度折行：CJK 任意断、拉丁按词、行首闭合标点挂行尾。"""
    text = _norm(text)
    if not text:
        return []
    lines: list[str] = []
    cur = ""
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\n":
            lines.append(cur)
            cur = ""
            i += 1
            continue
        trial = cur + ch
        if _sw(trial, font, size) <= width or not cur:
            cur = trial
            i += 1
            continue
        if ch in "，。、；：？！）】》”’%,.;:?!)]":
            # 闭合标点不悬挂出格：连同前一字推到下一行，保证行宽≤格宽（2026-11-03 突出修复）
            if len(cur) >= 2:
                lines.append(cur[:-1])
                cur = cur[-1] + ch
            else:
                cur = trial
            i += 1
            continue
        if ch.isascii() and ch.isalnum():
            m = re.search(r"([A-Za-z0-9.\-]+)$", cur)
            if m and m.start() > 0:
                word = m.group(1)
                lines.append(cur[: m.start()])
                cur = word + ch
                i += 1
                continue
        lines.append(cur)
        cur = ch
        i += 1
    if cur:
        lines.append(cur)
    return lines


def _fit_lines(text: str, width: float, base: float, min_size: float = 7.0,
               max_lines: int = 2) -> tuple[list[str], float]:
    """顶部表头值：先缩字号再折行，最多 max_lines 行（超出加省略号）。"""
    size = base
    while size > min_size:
        lines = _wrap(text, BODY_FONT, size, width)
        if len(lines) <= max_lines:
            return lines, size
        size -= 0.5
    lines = _wrap(text, BODY_FONT, min_size, width)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-1] + "…"
    return lines, min_size


# ── 标签要素 / 象形图 ────────────────────────────────────────────────


def _explicit_icons(text: str) -> list[str]:
    if not text:
        return []
    m = re.search(r"(?:图形|象形图|图标)[：:](.+?)(?:[；;]|$)", text)
    if not m:
        return []
    names: list[str] = []
    for part in re.split(r"[、,，/]", m.group(1)):
        token = part.strip()
        for key in _GHS:
            if key in token:
                if key not in names:
                    names.append(key)
                break
        else:
            for key, mapped in _GHS_ALIAS.items():
                if key in token and mapped not in names:
                    names.append(mapped)
                    break
    return names


def _derive_icons(text: str) -> list[str]:
    t = text or ""
    out: list[str] = []
    if "爆炸" in t:
        out.append("爆炸")
    if re.search(r"易燃|极易燃|高度易燃", t) and "不燃" not in t:
        out.append("火焰")
    if re.search(r"氧化性|氧化剂", t):
        out.append("火焰加圆圈")
    if re.search(r"压缩气体|液化气体", t):
        out.append("气瓶")
    if re.search(r"剧毒|(会|可)中毒|急性毒性[^。；]{0,8}(类别|第)[12]", t):
        out.append("骷髅和交叉骨")
    if re.search(r"腐蚀|灼伤|严重眼损伤", t):
        out.append("腐蚀")
    if re.search(r"刺激|致敏|有害|昏昏欲睡|眩晕|麻醉", t):
        out.append("感叹号")
    if re.search(r"可能致癌|致癌性|可致癌|一类致癌|1类致癌|致突变|遗传性缺陷|生殖毒性", t) \
            or re.search(r"损害[^。；]{0,6}器官|器官[^。；]{0,4}损害", t):
        out.append("健康危害")
    return out


def _icons(label_text: str, hazard: str, env: str) -> list[str]:
    derived = _derive_icons(" ".join(x for x in (label_text, hazard) if x))
    if re.search(r"对水生生物(有毒|有害)|危害水生环境|对水环境有危害", " ".join(x for x in (env, hazard) if x)):
        derived.append("环境")
    names = derived or _explicit_icons(label_text)
    return [n for n in _GHS_ORDER if n in names]


# ── 内容模型 ─────────────────────────────────────────────────────────

def _un_display(value: str) -> str:
    """UN No 展示值：NA/N.A./none 类占位统一显示「无」（2026-11-03 业务拍板）。"""
    token = re.sub(r"[\s./\\]", "", value or "").lower()
    return "无" if token in {"na", "none", "无", "notapplicable"} else value


def _bullet_lines(section: str, entry: dict, parts: dict) -> list[str]:
    raw = _norm(entry.get(_SECTION_FIELD[section]))
    if not raw:
        return []
    if section == "泄漏应急处理":
        return [raw]
    out: list[str] = []
    pd = parts.get(section, {})
    for _lbl, (sec, aliases) in _SUB_LABEL_SPECS.items():
        if sec != section:
            continue
        for alias in aliases:
            if alias in pd:
                out.append(f"{alias}：{pd[alias]}")
                break
    return out


def _build_model(entry: dict) -> dict:
    parts: dict[str, dict[str, str]] = {}
    for section, fk in _SECTION_FIELD.items():
        aliases = {a for _k, (sec, al) in _SUB_LABEL_SPECS.items() if sec == section for a in al}
        parts[section] = _split_into_parts(entry.get(fk) or "", list(aliases))

    def v(key: str) -> str:
        return _norm(entry.get(key))

    model = {
        "name": v("name"),
        "formula": v("molecular_formula").replace("（", "(").replace("）", ")"),
        "un": _un_display(v("un_no")), "cas": v("cas_no"),
        "hazard": v("hazard_statement"), "labels": v("label_elements"),
        "phys": [
            [("外观与性状", v("appearance"))],
            [("溶解性", v("solubility"))],
            [("熔点", v("melting_point")), ("闪点", v("flash_point"))],
            [("沸点", v("boiling_point")), ("相对密度（空）", v("relative_density"))],
            [("爆炸上限(%)", v("explosion_upper_limit")), ("爆炸下限(%)", v("explosion_lower_limit"))],
            [("自燃温度", v("autoignition_temperature")), ("分解温度", v("decomposition_temperature"))],
        ],
        "oel": [("时间加权平均容许浓度（PC-TWA）", v("pc_twa")),
                ("短时间接触容许浓度（PC-STEL）", v("pc_stel")),
                ("最高容许浓度（MAC）", v("mac"))],
        "sections": {},
        "handling": [],
    }
    model["sections"]["健康危害"] = [v("health_hazard")] if v("health_hazard") else []
    model["sections"]["环境危害"] = [v("environmental_hazard")] if v("environmental_hazard") else []
    for sec in ("急救措施", "接触控制/个体防护", "稳定性和反应性",
                "泄漏应急处理", "消防措施", "废弃处置"):
        model["sections"][sec] = _bullet_lines(sec, entry, parts)
    hs = parts.get("操作处置与储存注意事项", {})
    for label, aliases in (("操作注意事项", ("操作注意事项",)),
                           ("储存注意事项", ("储存注意事项", "储存事项"))):
        seg = next((x for k, x in hs.items() if k in aliases), None)
        if seg:
            model["handling"].append(f"{label}：{seg}")
    if not model["handling"] and v("handling_storage"):
        model["handling"].append(v("handling_storage"))
    return model


# ── 版面计算 ─────────────────────────────────────────────────────────


def _layout(model: dict, scale: float) -> dict:
    body = 9 * scale
    lead = 12 * scale
    pad = 5.2 * scale
    icon = 57.8 * scale
    lay = {"scale": scale, "body": body, "lead": lead, "pad": pad, "icon": icon}
    lay["icons"] = _icons(model["labels"], model["hazard"],
                          " ".join(model["sections"].get("环境危害") or []))

    name_w = XS[6] - XS[3] - 10 * scale
    lay["name_lines"], lay["name_size"] = _fit_lines(model["name"], name_w, 12 * scale,
                                                      max_lines=3)
    un_w = XS[9] - XS[8] - 10 * scale
    lay["un_lines"], lay["un_size"] = _fit_lines(model["un"], un_w, 12 * scale)

    lay["hazard"] = _wrap(model["hazard"], BODY_FONT, body, (XS[6] - XS[1]) - 2 * pad)
    lay["phys"] = []
    for i, row in enumerate(model["phys"]):
        cells = []
        for j, (label, value) in enumerate(row):
            x0, x1 = _PHYS_CFG[i][j]
            cells.append(_wrap(f"{label}：{value}", BODY_FONT, body, (x1 - x0) - 2 * pad))
        lay["phys"].append(cells)
    lay["oel"] = [_wrap(f"{label}：{value}", BODY_FONT, body, (XS[9] - XS[7]) - 2 * pad)
                  for label, value in model["oel"]]

    left = [(n, model["sections"][n]) for n in
            ("健康危害", "环境危害", "急救措施", "接触控制/个体防护", "稳定性和反应性")
            if model["sections"].get(n)]
    right = [(n, model["sections"][n]) for n in
             ("泄漏应急处理", "消防措施", "废弃处置")
             if model["sections"].get(n)]

    def wrap_blocks(blocks, width):
        out = []
        for name, lines in blocks:
            out.append((name, [_wrap(ln, BODY_FONT, body, width - 30 * scale) for ln in lines]))
        return out

    lay["left_wrap"] = wrap_blocks(left, XS[6] - XS[0])
    lay["right_wrap"] = wrap_blocks(right, XS[9] - XS[6])

    def blocks_h(wrapped):
        h = 0.0
        for _n, lines in wrapped:
            h += lead
            for ws in lines:
                h += max(1, len(ws)) * lead
            h += 3 * scale
        return h

    main_h = max(blocks_h(lay["left_wrap"]), blocks_h(lay["right_wrap"])) + 2 * scale
    icon_rows = max(1, (len(lay["icons"]) + 2) // 3) if lay["icons"] else 0
    # 竖排栏目标签高度下限（危险性说明 5 字一行=5 行）：行高不足会顶穿行上边线（2026-11-03 突出修复）
    r2_h = max(icon_rows * icon + 20 * scale if lay["icons"] else 0,
               len(lay["hazard"]) * lead + 12 * scale, 40 * scale,
               5 * lead + 8 * scale)

    phys_h = []
    for i, cells in enumerate(lay["phys"]):
        n = max(len(c) for c in cells)
        base = 24.4 * scale if i < 2 else (15 * scale if i == 2 else 12.5 * scale)
        phys_h.append(max(base, n * lead + 2.5 * scale))

    lay["op"] = []
    for para in model["handling"]:
        lay["op"].extend(_wrap(para, BODY_FONT, body, (XS[9] - XS[2]) - 2 * pad))
    # 竖排标签「操作处置与储存注意事项」11 字 3 字一行=4 行：行高必须容纳，否则顶穿上边线
    op_h = max(len(lay["op"]) * lead + 4 * scale, 40 * scale, 4 * lead + 8 * scale)

    # r0 行同时承载名称值与 UN 值（各最多 16pt 行距×行数）：取两者高度较大者
    r0_h = max(27.6 * scale,
               len(lay["name_lines"]) * 16 * scale + 6 * scale,
               len(lay["un_lines"]) * 16 * scale + 6 * scale)
    r1_h = max(23.4 * scale, 16 * scale + 6 * scale)
    ys = [Y0, Y0 + r0_h, Y0 + r0_h + r1_h]
    ys.append(ys[-1] + r2_h)
    for h in phys_h:
        ys.append(ys[-1] + h)
    ys.append(ys[-1] + main_h)
    ys.append(ys[-1] + op_h)
    lay.update(ys=ys, r2_h=r2_h, total=ys[-1] - Y0)
    return lay


def _clip_entry(entry: dict, limit: int) -> dict:
    out = {}
    for k, v in entry.items():
        if isinstance(v, str) and len(v) > limit:
            out[k] = v[:limit].rstrip() + "…截断"
        else:
            out[k] = v
    return out


# ── 渲染 ─────────────────────────────────────────────────────────────


def _render(model: dict, lay: dict, output_path: str) -> None:
    c = canvas.Canvas(output_path, pagesize=A4)
    c.setLineWidth(0.48)
    scale, body, lead, pad, icon = (lay["scale"], lay["body"], lay["lead"],
                                    lay["pad"], lay["icon"])
    ys = lay["ys"]

    def Y(y: float) -> float:
        return PAGE_H - y

    def solid(text, x, yy, size, bold=False, centered=False, font=None):
        c.setFont(font or BODY_FONT, size)
        offsets = [(0, 0)] if not bold else [(0, 0), (0.26 * scale, 0), (0, 0.16 * scale)]
        for dx, dy in offsets:
            if centered:
                c.drawCentredString(x + dx, yy + dy, text)
            else:
                c.drawString(x + dx, yy + dy, text)

    def text_line(text, x, ytop, size=None, bold=False, align="left", width=None):
        size = size or body
        yy = Y(ytop + size * 0.86)
        if align == "center":
            solid(text, x + (width or 0) / 2, yy, size, bold, centered=True)
        else:
            solid(text, x, yy, size, bold)

    def lines_block(lines, x, ytop, bold=False):
        for ln in lines:
            text_line(ln, x, ytop, bold=bold)
            ytop += lead
        return ytop

    def vertical_label(text, x0, x1, y0, y1, per_line=1):
        if not text:
            return
        lines = [text[i:i + per_line] for i in range(0, len(text), per_line)]
        top = y0 + (y1 - y0 - len(lines) * lead) / 2
        for ln in lines:
            text_line(ln, x0, top, align="center", width=x1 - x0)
            top += lead

    # 标题
    c.setFont(HEITI_FONT, 36 * scale)
    _title_y = PAGE_H - 42.6 * scale
    for _dx, _dy in ((0, 0), (0.6 * scale, 0), (0, 0.4 * scale), (0.3 * scale, 0.2 * scale)):
        c.drawCentredString(PAGE_W / 2 + _dx, _title_y + _dy, "MSDS 表")

    # 表格线
    c.rect(XS[0], Y(ys[-1]), XS[9] - XS[0], ys[-1] - ys[0], stroke=1, fill=0)
    for y in (ys[1], ys[2], ys[3], ys[9], ys[10]):
        c.line(XS[0], Y(y), XS[9], Y(y))
    for i in range(4, 9):
        c.line(XS[1], Y(ys[i]), XS[6], Y(ys[i]))
    for i in (5, 7):
        c.line(XS[7], Y(ys[i]), XS[9], Y(ys[i]))
    c.line(XS[0], Y(ys[-1]), XS[0], Y(ys[0]))
    c.line(XS[9], Y(ys[-1]), XS[9], Y(ys[0]))
    c.line(XS[1], Y(ys[2]), XS[1], Y(ys[9]))
    c.line(XS[2], Y(ys[10]), XS[2], Y(ys[11]))
    c.line(XS[3], Y(ys[0]), XS[3], Y(ys[2]))
    c.line(XS[4], Y(ys[5]), XS[4], Y(ys[8]))
    c.line(XS[5], Y(ys[8]), XS[5], Y(ys[9]))
    c.line(XS[6], Y(ys[0]), XS[6], Y(ys[10]))
    c.line(XS[7], Y(ys[2]), XS[7], Y(ys[9]))
    c.line(XS[8], Y(ys[0]), XS[8], Y(ys[2]))

    # 名称行（「名 称」按参考件两字分散）
    mid = (XS[0] + XS[3]) / 2
    base12 = 12 * scale
    for ch, dx in (("名", -12 * scale), ("称", 12 * scale)):
        yy = Y((ys[0] + ys[1]) / 2 + base12 * 0.35)
        solid(ch, mid + dx, yy, base12, bold=True, centered=True)
    name_y0 = ys[0] + (ys[1] - ys[0] - len(lay["name_lines"]) * 16 * scale) / 2
    tmp = name_y0
    for ln in lay["name_lines"]:
        text_line(ln, XS[3], tmp + (16 * scale - lay["name_size"]) / 2 + 2 * scale,
                  size=lay["name_size"], bold=True, align="center", width=XS[6] - XS[3])
        tmp += 16 * scale
    text_line("UN No", XS[6], (ys[0] + ys[1]) / 2 - base12 * 0.5, size=base12, bold=True, align="center", width=XS[8] - XS[6])
    un_y0 = ys[0] + (ys[1] - ys[0] - len(lay["un_lines"]) * 16 * scale) / 2
    for ln in lay["un_lines"]:
        text_line(ln, XS[8], un_y0 + (16 * scale - lay["un_size"]) / 2 + 2 * scale,
                  size=lay["un_size"], bold=True, align="center", width=XS[9] - XS[8])
        un_y0 += 16 * scale
    text_line("分子式", XS[0], (ys[1] + ys[2]) / 2 - base12 * 0.5, size=base12, bold=True, align="center", width=XS[3] - XS[0])
    text_line("CAS No", XS[6], (ys[1] + ys[2]) / 2 - base12 * 0.5, size=base12, bold=True, align="center", width=XS[8] - XS[6])
    text_line(model["cas"], XS[8], (ys[1] + ys[2]) / 2 - base12 * 0.5, size=base12, bold=True, align="center", width=XS[9] - XS[8])

    # 分子式（下标 + 粗体居中）
    formula = model["formula"]
    runs = []
    for mm in re.finditer(r"([A-Za-z\)]+)|(\d+)|([^A-Za-z\)\d]+)", formula):
        runs.append((mm.group(0), bool(mm.group(2))))
    # 中点「·」STSong-Light 无字形：单独用黑体（Noto）补，保住水合物写法
    def run_font(t: str) -> str:
        return HEITI_FONT if "·" in t and HEITI_FONT != BODY_FONT else BODY_FONT

    total = sum(_sw(t, run_font(t), base12 * (0.62 if sub else 1)) for t, sub in runs)
    cx = (XS[3] + XS[6]) / 2 - total / 2
    yy = Y((ys[1] + ys[2]) / 2 + base12 * 0.35)
    for t, sub in runs:
        s = base12 * (0.62 if sub else 1)
        f = run_font(t)
        solid(t, cx, yy - (base12 * 0.25 if sub else 0), s, bold=True, font=f)
        cx += _sw(t, f, s)

    # 危险性说明 / 标签要素
    vertical_label("危险性说明", XS[0], XS[1], ys[2], ys[3])
    lines_block(lay["hazard"], XS[1] + pad,
                ys[2] + (lay["r2_h"] - len(lay["hazard"]) * lead) / 2)
    vertical_label("标签要素", XS[6], XS[7], ys[2], ys[3])
    icons = lay["icons"]
    if icons:
        rows = (len(icons) + 2) // 3
        for r in range(rows):
            group = icons[r * 3:r * 3 + 3]
            x = XS[7] + ((XS[9] - XS[7]) - len(group) * icon) / 2
            top = ys[2] + (lay["r2_h"] - rows * icon) / 2 + r * icon
            for n in group:
                d = _asset_dir("ghs")
                path = d / _GHS[n] if d else None
                if path and path.exists():
                    c.drawImage(ImageReader(str(path)), x, Y(top + icon),
                                width=icon, height=icon, mask="auto")
                x += icon
    else:
        ls = _wrap(model["labels"], BODY_FONT, body, (XS[9] - XS[7]) - 2 * pad)
        lines_block(ls, XS[7] + pad, ys[2] + (lay["r2_h"] - len(ls) * lead) / 2)

    # 理化特性
    vertical_label("理化特性", XS[0], XS[1], ys[3], ys[9])
    for i, cells in enumerate(lay["phys"]):
        y0, y1 = ys[3 + i], ys[4 + i]
        for j, ls in enumerate(cells):
            x0, _x1 = _PHYS_CFG[i][j]
            lines_block(ls, x0 + pad, y0 + (y1 - y0 - len(ls) * lead) / 2)

    # 职业接触限值
    vertical_label("职业接触限值", XS[6], XS[7], ys[3], ys[9])
    for i, ls in enumerate(lay["oel"]):
        y0, y1 = ((ys[3], ys[5]), (ys[5], ys[7]), (ys[7], ys[9]))[i]
        lines_block(ls, XS[7] + pad, y0 + (y1 - y0 - len(ls) * lead) / 2)

    # 大块左右栏
    def draw_blocks(wrapped, x0, x1, y0):
        ycur = y0 + 2 * scale
        for name, lines in wrapped:
            text_line(name, x0, ycur, align="center", width=x1 - x0, bold=True)
            ycur += lead
            for ws in lines:
                for k, wl in enumerate(ws):
                    if k == 0:
                        text_line("●", x0 + 5.3 * scale, ycur)
                    text_line(wl, x0 + 26.4 * scale, ycur)
                    ycur += lead
            ycur += 3 * scale

    draw_blocks(lay["left_wrap"], XS[0], XS[6], ys[9])
    draw_blocks(lay["right_wrap"], XS[6], XS[9], ys[9])

    # 操作处置与储存注意事项
    vertical_label("操作处置与储存注意事项", XS[0], XS[2], ys[10], ys[11], per_line=3)
    lines_block(lay["op"], XS[2] + pad, ys[10] + 3 * scale)

    # 页码
    c.setFont(BODY_FONT, 9)
    c.drawCentredString(PAGE_W / 2, Y(782.2 + 9 * 0.86), "1")

    c.showPage()
    c.save()


# ── 兼容层（2026-11-03 画布版保留：旧测试与外部引用）─────────────────
_FONT = BODY_FONT
_HEITI = HEITI_FONT
_SUBSCRIPT_MAP = {chr(0x2080 + i): str(i) for i in range(10)}
_SUPERSCRIPT_MAP = {
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
    "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
    "⁺": "+", "⁻": "−", "ⁿ": "n",
}
_INVISIBLE_RE = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")
_FORMULA_DIGIT_RE = re.compile(r"(?<=[A-Za-z\)])\d+")


def _rich_markup(value: str) -> str:
    """XML 转义 + 中文排版规范化（保留旧接口；画布渲染用 _norm 纯文本版）。"""
    import html

    s = _INVISIBLE_RE.sub("", value or "")
    s = _CJK_GAP_RE.sub("", s)
    for pattern, full in _HALF_FULL_RES:
        s = pattern.sub(full, s)
    s = _normalize_quotes(s)
    s = html.escape(s, quote=False)
    s = re.sub(r"([mg]/m)3\b", r"\1<sup>3</sup>", s)
    out: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch in _SUBSCRIPT_MAP:
            digits = []
            while i < len(s) and s[i] in _SUBSCRIPT_MAP:
                digits.append(_SUBSCRIPT_MAP[s[i]]); i += 1
            out.append("<sub>" + "".join(digits) + "</sub>")
        elif ch in _SUPERSCRIPT_MAP:
            digits = []
            while i < len(s) and s[i] in _SUPERSCRIPT_MAP:
                digits.append(_SUPERSCRIPT_MAP[s[i]]); i += 1
            out.append("<sup>" + "".join(digits) + "</sup>")
        else:
            out.append(ch); i += 1
    return "".join(out)


def _formula_markup(value: str) -> str:
    """分子式 HTML 标记（保留旧接口）：字母/右括号后的数字转 <sub>。"""
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
    """解析标签要素 → (图形名列表, 信号词)（旧接口）。"""
    names = _explicit_icons(text)
    m = re.search(r"信号词[：:]\s*(危险|警告)", text or "")
    return names, (m.group(1) if m else "")


def _scaled_styles(scale: float) -> dict:
    """旧接口：按缩放系数返回 ParagraphStyle 字典（仅兼容引用，不参与画布渲染）。"""
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.styles import ParagraphStyle

    top = round(12 * scale, 1)
    body = round(9 * scale, 2)
    return {
        "title": ParagraphStyle("msds_title", fontName=BODY_FONT, fontSize=round(36 * scale), leading=42 * scale, alignment=1),
        "label_top": ParagraphStyle("msds_label_top", fontName=HEITI_FONT, fontSize=top, leading=16 * scale, alignment=TA_CENTER),
        "value_top": ParagraphStyle("msds_value_top", fontName=HEITI_FONT, fontSize=top, leading=16 * scale, alignment=TA_CENTER),
        "label": ParagraphStyle("msds_label", fontName=BODY_FONT, fontSize=body, leading=12 * scale),
        "body": ParagraphStyle("msds_body", fontName=BODY_FONT, fontSize=body, leading=12 * scale),
        "section_head": ParagraphStyle("msds_section_head", fontName=HEITI_FONT, fontSize=body, leading=12 * scale, alignment=TA_CENTER),
    }


# ── 公共 API ─────────────────────────────────────────────────────────


def build_standard_msds_pdf(entry: dict, output_path: str) -> str:
    """将单条 28 字段填充为企业标准 PDF（参考件版式，强制单页）。

    内容过长时按档位整体缩放字号；最小档仍放不下时逐级截断字段内容。
    """
    model = _build_model(entry)
    lay = None
    for scale in SCALES:
        lay = _layout(model, scale)
        if lay["total"] <= AVAIL:
            break
    if lay is None or lay["total"] > AVAIL:
        scale = SCALES[-1]
        for limit in (1500, 1000, 700, 500, 350, 240, 160, 100):
            model = _build_model(_clip_entry(entry, limit))
            lay = _layout(model, scale)
            if lay["total"] <= AVAIL:
                logger.warning("MSDS PDF 内容超长已截断(每字段≤%d字): %s", limit, entry.get("name"))
                break
    _render(model, lay, output_path)
    logger.info("MSDS 标准 PDF 已生成(参考件版式 scale=%.2f): %s", lay["scale"], output_path)
    return output_path


def standard_pdf_filename(entry: dict, collection_id: str, idx: int) -> str:
    """标准 pdf 文件名（sanitized）。"""
    name = (entry.get("name") or "unknown").replace("/", "_").replace("\\", "_")
    cas = (entry.get("cas_no") or "no_cas").replace("/", "_").replace("\\", "_")
    return f"{name}_{cas}_{collection_id[:8]}_{idx}.pdf"
