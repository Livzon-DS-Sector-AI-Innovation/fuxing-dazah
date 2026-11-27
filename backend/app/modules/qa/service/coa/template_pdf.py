"""COA 快速打印：把回填好的 docx 转成 PDF，让浏览器直接打开打印。

打印件会交给客户，版式要和平时用 WPS 打印的一致，所以不在浏览器里重排，
而是在服务端用 LibreOffice 转 PDF（镜像里装 ``libreoffice-writer-nogui``）。

- **同一份 docx 只转一次**：转换结果按 docx 内容的指纹缓存。每次请求都先
  重新回填 docx（纯代码，很快）再查缓存——登记数据、模板标注一改，指纹就变，
  自然拿不到旧 PDF，不需要任何失效逻辑。
- **出文件即留档**，与下载同一口径；同一份内容已经留过底稿（下载过或打印过）
  就不重复留，只记一条操作日志。
- 这个地址是在新标签页里直接打开的，出错时要给人看一页提示，而不是一段 JSON
  （页面由 api 层拼，这里只负责把拦截原因说成人话）。
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import weakref
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from docx.opc.oxml import serialize_part_xml
from docx.oxml import parse_xml
from docx.oxml.ns import qn
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.qa.repository import coa as repo
from app.modules.qa.service.coa.common import (
    get_report_or_404,
    get_standard_or_404,
)
from app.modules.qa.service.coa.render_archive import archive_render
from app.modules.qa.service.coa.report_log import (
    COA_LOG_ACTION_RENDERED,
    record_report_log,
)
from app.modules.qa.service.coa.template_render import build_report_docx
from app.platform.identity.models import User

logger = logging.getLogger(__name__)

COA_PDF_MIME = "application/pdf"

# 转换结果缓存在容器本地的临时目录。不放 uploads 卷：都是能重新生成的文件，
# 不该跟着备份走。容器重建后清空，每份首次打开重新转换（约 1 秒）。
_CACHE_TTL = 7 * 24 * 3600
_SWEEP_INTERVAL = 3600
# 同一时间只跑一个 LibreOffice：内存可控（峰值约 200MB）；排队的请求等它转完
# 直接命中缓存，同一份 docx 不会被转两遍
_CONVERT_CONCURRENCY = 1
_CONVERT_TIMEOUT = 120

_SOFFICE_CANDIDATES = {
    "darwin": ("/Applications/LibreOffice.app/Contents/MacOS/soffice",),
    "linux": (
        "/usr/bin/soffice",
        "/usr/local/bin/soffice",
        "/opt/libreoffice/program/soffice",
    ),
    "win32": (r"C:\Program Files\LibreOffice\program\soffice.exe",),
}

# 模板里的微软字体（宋体、黑体…）服务器上没有：转 PDF 时用随代码打包的开源字体兜底。
# 只是兜底——哪天把真字体放进 assets/fonts，真字体自动优先，不用改这里。
_FONT_FALLBACKS = (
    ("宋体", "Noto Serif SC"),
    ("SimSun", "Noto Serif SC"),
    ("新宋体", "Noto Serif SC"),
    ("NSimSun", "Noto Serif SC"),
    ("楷体", "Noto Serif SC"),
    ("KaiTi", "Noto Serif SC"),
    ("仿宋", "Noto Serif SC"),
    ("FangSong", "Noto Serif SC"),
    ("黑体", "Noto Sans SC"),
    ("SimHei", "Noto Sans SC"),
    ("微软雅黑", "Noto Sans SC"),
    ("Microsoft YaHei", "Noto Sans SC"),
    ("等线", "Noto Sans SC"),
    ("DengXian", "Noto Sans SC"),
    ("Arial", "Liberation Sans"),
    ("Arial Black", "Liberation Sans"),
    ("Times New Roman", "Liberation Serif"),
)
# 仓库 assets 根候选（与 apr/report.py 同口径）：parents[5] 即 backend 根，再兜底 cwd 与上级
_ASSET_ROOTS = (
    Path(__file__).resolve().parents[5] / "assets",
    Path("assets"),
    Path("../assets"),
)


def bundled_fonts_dir() -> Path | None:
    """随代码打包的字体目录 ``assets/fonts``；找不到返回 None。"""
    for root in _ASSET_ROOTS:
        if (root / "fonts").is_dir():
            return root / "fonts"
    return None


def fontconfig_for_print() -> str:
    """只给转 PDF 的 LibreOffice 进程用的 fontconfig（环境变量 ``FONTCONFIG_FILE``）。

    不写进系统配置：别处的 HTML→PDF 也走 fontconfig，字体匹配不能被这里改变。
    镜像里除了随代码打包的字体没有别的中文字体，不把 ``assets/fonts`` 交进去，
    中文会整段丢失。LibreOffice 自带的字体替换表实测不生效，所以走 fontconfig。
    """
    lines = [
        '<?xml version="1.0"?>',
        '<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">',
        "<fontconfig>",
        '  <include ignore_missing="yes">/etc/fonts/fonts.conf</include>',
    ]
    fonts_dir = bundled_fonts_dir()
    if fonts_dir is not None:
        lines.append(f"  <dir>{fonts_dir}</dir>")
    for missing, fallback in _FONT_FALLBACKS:
        lines.append(
            f'  <alias binding="same"><family>{missing}</family>'
            f"<prefer><family>{fallback}</family></prefer></alias>"
        )
    lines.append("</fontconfig>")
    return "\n".join(lines) + "\n"


# ─────────────────────── 转换 ───────────────────────


def find_soffice() -> str | None:
    """LibreOffice 可执行文件；没装返回 None（调用方提示改用「下载 COA」）。"""
    for candidate in _SOFFICE_CANDIDATES.get(sys.platform, ()):
        if Path(candidate).is_file():
            return candidate
    return shutil.which("soffice") or shutil.which("libreoffice")


# 模板的表框写的是 0.5 磅的双线（内线是单线）。LibreOffice 画多线边框时，每条线的宽度和
# 间距都跟声明线宽成正比：double + sz=4 会画成两条 0.5 磅、相距 1 磅的线，比 Word 里粗
# 三倍，上下还各多占约 1 磅，把版面撑到分页。语料里 395 份模板的表框全是这种写法。
# 打印副本里把这类边框改成单线、线宽不变——出文件的外框按单线算，是 2026-11-26 定的口径。
_HAIRLINE_EIGHTHS = 4
_MULTI_LINE_BORDERS = frozenset(
    {
        "double",
        "triple",
        "thinThickSmallGap",
        "thickThinSmallGap",
        "thinThickThinSmallGap",
        "thinThickLargeGap",
        "thickThinLargeGap",
        "thinThickThinLargeGap",
    }
)
_BORDER_PARTS = re.compile(r"word/(?:document|header\d*|footer\d*|styles)\.xml")


def print_copy(docx: bytes) -> bytes:
    """交给 LibreOffice 的打印副本：只改它和 Word 画法不一样的地方。

    三处——表格、单元格边框里 0.5 磅及更细的多线边框改成单线；把会被削字顶的固定行高
    段落放宽到放得下（见 :func:`_fit_fixed_lines`）；关掉行网格，把靠网格撑行高的段落的
    行高写死（见 :func:`_release_grid`）。下载和留档的原件不动；除此之外逐字节保持原样。
    """
    out = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(docx)) as archive,
        zipfile.ZipFile(out, "w") as target,
    ):
        names = set(archive.namelist())
        styles = _Styles(
            archive.read("word/styles.xml") if "word/styles.xml" in names else None
        )
        # 页眉页脚里的段落没有自己的小节，版心宽度也按正文的算
        width = (
            _text_width(archive.read("word/document.xml"))
            if "word/document.xml" in names
            else None
        )
        for info in archive.infolist():
            payload = archive.read(info.filename)
            if _BORDER_PARTS.fullmatch(info.filename):
                payload = _flatten_borders(payload)
            if _TEXT_PARTS.fullmatch(info.filename):
                payload = _fit_fixed_lines(payload, styles, width)
                if info.filename == "word/document.xml":
                    payload = _release_grid(payload, styles)
            target.writestr(info, payload)
    return out.getvalue()


def _flatten_borders(xml: bytes) -> bytes:
    """把细多线边框改成单线；没有要改的就原样返回这一段的字节。"""
    root = parse_xml(xml)
    changed = False
    for holder in root.iter(qn("w:tcBorders"), qn("w:tblBorders")):
        for edge in holder:
            if edge.get(qn("w:val")) not in _MULTI_LINE_BORDERS:
                continue
            size = edge.get(qn("w:sz")) or "0"
            if size.isdigit() and int(size) <= _HAIRLINE_EIGHTHS:
                edge.set(qn("w:val"), "single")
                changed = True
    return serialize_part_xml(root) if changed else xml


# ─────────────────────── 打印副本：行网格 ───────────────────────

# 模板都设了 15.6 磅的行网格（docGrid lines，语料 395 份全是）。Word 的网格从正文起点往下排；
# LibreOffice 会把页眉下方正文的起点对齐到网格线上——页眉一高就把正文多推一截（约 7~8 磅），
# 临界版面因此多出一页；个别模板还会把表格行排重叠（文字压行、行间线丢失）。
# 打印副本里关掉行网格，同时把「靠网格撑行高」的段落（非固定行距、没关网格对齐）的行高
# 写死成「网格行高 × 行数」：行高不变，只去掉上面两个副作用。
_GRID_PITCH = 312  # 缇；15.6 磅，Word 中文文档的默认行网格
_WORD_LINE_FACTOR = 1.15  # Word 里一行的自然高度约为字号的 1.15 倍
_DEFAULT_FONT_HALF_POINTS = 20
_OFF = frozenset({"false", "0", "off"})
_LINE_GRID_TYPES = frozenset({"lines", "linesAndChars"})
# pPr 子元素的先后顺序里排在 w:spacing 之后的；新建 w:spacing 时要插在它们前面
_AFTER_SPACING = frozenset(
    {
        "ind",
        "contextualSpacing",
        "mirrorIndents",
        "suppressOverlap",
        "jc",
        "textDirection",
        "textAlignment",
        "textboxTightWrap",
        "outlineLvl",
        "divId",
        "cnfStyle",
        "rPr",
        "sectPr",
        "pPrChange",
    }
)


class _Styles:
    """段落样式表：按「段落自身 → 段落样式及 basedOn 链 → 默认样式 → 文档默认」找有效属性。"""

    def __init__(self, xml: bytes | None) -> None:
        self.styles: dict[str, Any] = {}
        self.default: Any = None
        self.defaults_ppr: Any = None
        self.defaults_rpr: Any = None
        if xml is None:
            return
        root = parse_xml(xml)
        for style in root.findall(qn("w:style")):
            self.styles[style.get(qn("w:styleId"))] = style
        self.default = next(
            (
                style
                for style in self.styles.values()
                if style.get(qn("w:type")) == "paragraph"
                and style.get(qn("w:default")) == "1"
            ),
            None,
        )
        defaults = root.find(qn("w:docDefaults"))
        if defaults is not None:
            ppr_default = defaults.find(qn("w:pPrDefault"))
            rpr_default = defaults.find(qn("w:rPrDefault"))
            if ppr_default is not None:
                self.defaults_ppr = ppr_default.find(qn("w:pPr"))
            if rpr_default is not None:
                self.defaults_rpr = rpr_default.find(qn("w:rPr"))

    def _chain(self, ppr: Any) -> list[Any]:
        """段落自身的 pPr 在最前，之后沿样式链由近及远；取不到的是 None。"""
        out = [ppr]
        node = ppr.find(qn("w:pStyle")) if ppr is not None else None
        style_id = node.get(qn("w:val")) if node is not None else None
        seen: set[str] = set()
        while style_id and style_id in self.styles and style_id not in seen:
            seen.add(style_id)
            style = self.styles[style_id]
            out.append(style.find(qn("w:pPr")))
            based = style.find(qn("w:basedOn"))
            style_id = based.get(qn("w:val")) if based is not None else None
        if self.default is not None:
            out.append(self.default.find(qn("w:pPr")))
        out.append(self.defaults_ppr)
        return out

    def first(self, ppr: Any, tag: str, attr: str) -> Any:
        """沿样式链找第一个带 attr 的 ``<w:tag>``；都没有返回 None。"""
        for holder in self._chain(ppr):
            if holder is None:
                continue
            element = holder.find(qn(f"w:{tag}"))
            if element is not None and element.get(qn(f"w:{attr}")) is not None:
                return element
        return None

    def _paragraph_half_points(self, ppr: Any) -> int:
        """段落这一级的字号（半磅）：段落样式及 basedOn 链 → 默认样式 → 文档默认。"""
        holders: list[Any] = []
        node = ppr.find(qn("w:pStyle")) if ppr is not None else None
        style_id = node.get(qn("w:val")) if node is not None else None
        seen: set[str] = set()
        while style_id and style_id in self.styles and style_id not in seen:
            seen.add(style_id)
            holders.append(self.styles[style_id].find(qn("w:rPr")))
            based = self.styles[style_id].find(qn("w:basedOn"))
            style_id = based.get(qn("w:val")) if based is not None else None
        if self.default is not None:
            holders.append(self.default.find(qn("w:rPr")))
        holders.append(self.defaults_rpr)
        for holder in holders:
            size = holder.find(qn("w:sz")) if holder is not None else None
            if size is not None and (size.get(qn("w:val")) or "").isdigit():
                return int(size.get(qn("w:val")))
        return _DEFAULT_FONT_HALF_POINTS

    def font_half_points(self, para: Any, ppr: Any) -> int:
        """段落里最大的字号（半磅）：文字里的 → 段落标记的 → 样式链上的 → 文档默认。"""
        sizes = [
            int(size.get(qn("w:val")))
            for size in para.iter(qn("w:sz"))
            if (size.get(qn("w:val")) or "").isdigit()
        ]
        if sizes:
            return max(sizes)
        return self._paragraph_half_points(ppr)

    def run_half_points(self, run: Any, ppr: Any) -> int:
        """这一个 run 的字号（半磅）：自己写的 → 所在段落的样式链 → 文档默认。"""
        rpr = run.find(qn("w:rPr"))
        size = rpr.find(qn("w:sz")) if rpr is not None else None
        if size is not None and (size.get(qn("w:val")) or "").isdigit():
            return int(size.get(qn("w:val")))
        return self._paragraph_half_points(ppr)


def _grid_pitch(sect: Any) -> int | None:
    """小节的行网格行距（缇）；没有行网格返回 None。"""
    grid = sect.find(qn("w:docGrid")) if sect is not None else None
    if grid is None or grid.get(qn("w:type")) not in _LINE_GRID_TYPES:
        return None
    try:
        return int(grid.get(qn("w:linePitch")) or _GRID_PITCH)
    except ValueError:
        return _GRID_PITCH


def _section_pitches(body: Any) -> list[int | None]:
    """按顶层块的下标给出所属小节的行网格行距。

    小节由段内 sectPr 结尾，最后一节是正文级的 sectPr。按下标而不是按元素对象查：
    lxml 的元素是按需生成的代理，拿 id() 跨函数当键不可靠。
    """
    children = list(body)
    ends: list[tuple[int, int | None]] = []
    for index, child in enumerate(children):
        if child.tag == qn("w:p"):
            sect = child.find(f"{qn('w:pPr')}/{qn('w:sectPr')}")
            if sect is not None:
                ends.append((index, _grid_pitch(sect)))
    last = body.find(qn("w:sectPr"))
    ends.append((len(children) - 1, _grid_pitch(last)))
    return [
        next(pitch for end, pitch in ends if end >= index)
        for index in range(len(children))
    ]


def _release_grid(xml: bytes, styles: _Styles) -> bytes:
    """关掉行网格，并把靠网格撑行高的段落的行高写死；没有行网格就原样返回。"""
    root = parse_xml(xml)
    body = root.find(qn("w:body"))
    grids = [
        grid
        for grid in root.iter(qn("w:docGrid"))
        if grid.get(qn("w:type")) in _LINE_GRID_TYPES
    ]
    if body is None or not grids:
        return xml
    pitches = _section_pitches(body)  # 先读各小节的行距，再改网格类型
    for grid in grids:
        grid.set(
            qn("w:type"), "default" if grid.get(qn("w:type")) == "lines" else "chars"
        )
    for para in body.iter(qn("w:p")):
        if any(a.tag == qn("w:txbxContent") for a in para.iterancestors()):
            continue  # 文本框里的文字不受页面网格约束
        top = para
        while top.getparent() is not body:
            top = top.getparent()
        pitch = pitches[body.index(top)]
        if not pitch:
            continue
        ppr = para.find(qn("w:pPr"))
        snap = styles.first(ppr, "snapToGrid", "val")
        if snap is not None and snap.get(qn("w:val")) in _OFF:
            continue
        rule = styles.first(ppr, "spacing", "lineRule")
        if rule is not None and rule.get(qn("w:lineRule")) == "exact":
            continue
        height = styles.font_half_points(para, ppr) * 10 * _WORD_LINE_FACTOR  # 缇
        line = styles.first(ppr, "spacing", "line")
        declared = line.get(qn("w:line")) if line is not None else None
        if declared is not None and declared.isdigit():
            if rule is not None and rule.get(qn("w:lineRule")) == "atLeast":
                height = max(height, int(declared))
            else:
                height *= int(declared) / 240  # 倍数行距：先折算出这一行的自然高度
        rows = max(1, math.ceil(height / pitch))
        spacing = _own_spacing(para)
        spacing.set(qn("w:lineRule"), "exact")
        spacing.set(qn("w:line"), str(rows * pitch))
    return serialize_part_xml(root)


def _own_spacing(para: Any) -> Any:
    """段落自己的 ``<w:spacing>``，没有就按元素顺序新建；只往这里写，不动样式。"""
    ppr = para.find(qn("w:pPr"))
    if ppr is None:
        ppr = para.makeelement(qn("w:pPr"), {})
        para.insert(0, ppr)
    spacing = ppr.find(qn("w:spacing"))
    if spacing is None:
        spacing = ppr.makeelement(qn("w:spacing"), {})
        later = next(
            (
                i
                for i, child in enumerate(ppr)
                if child.tag.split("}")[-1] in _AFTER_SPACING
            ),
            len(ppr),
        )
        ppr.insert(later, spacing)
    return spacing


# ─────────────────────── 打印副本：固定行高的字顶 ───────────────────────

# 标题都是「字号 = 固定行高」（16 磅黑体配 16 磅行高），少数更挤（14 磅字配 12 磅行高）。Word/WPS 里真黑体
# 的下伸只占 14%，字顶放得下；替代的思源黑体下伸占 28.8%，LibreOffice 排固定行高的行时把行框按字体的
# 上伸/下伸切成 80.1% : 19.9%，字顶超出上伸的笔画就被裁掉（两种标题分别被削 0.9 磅、2.4 磅）。
# LibreOffice 25.2 不裁（照画），26.8 起裁。打印副本里把这类行的行框加高到放得下，等量从段前、段后距里扣，
# 段落总高不变——文字基本原地不动，两个版本排出来一样；借不到间距的（表格里的段落）退而求其次，把文字在
# 行框内下移（w:position）。只处理会被削 0.85 磅以上的（标题这类一眼可见的），表格正文里被削零点几磅的不动。
_TEXT_PARTS = re.compile(r"word/(?:document|header\d*|footer\d*)\.xml")
_ASCENT_SHARE = (
    1.16 / 1.448
)  # 思源黑体的上伸占其行高的比例，也就是固定行高里基线以上的占比
_FALLBACK_LINES = 1.448  # 思源黑体的行高（em）
_CJK = re.compile(r"[\u2e80-\u9fff\uf900-\ufaff]")
_DEEP = re.compile(r"[，；gjpqyQ(){}\[\];@_]")  # 字底很低的全角标点、拉丁字母和括号
_IDEOGRAPH_TOP = 0.87  # 语料用到的汉字里最高的字顶（em，思源黑体粗体实测 0.866）
_CJK_BOTTOM = 0.105  # 汉字、全角括号最低的字底（实测 0.103）
_DEEP_BOTTOM = 0.23  # 上面那类字符最低的字底（思源宋体粗体的全角逗号实测 0.222）
_VISIBLE_CLIP = 17  # 缇（0.85 磅）：削不到这么多的看不出，不动
_BOTTOM_SLACK = 3  # 缇：下移后字底允许出框这一点点
_KEEP_BEFORE = 20  # 缇：借段前距时至少留 1 磅，别让文字贴到上方（比如页眉横线）
# 自动段距（beforeAutospacing / afterAutospacing 开着）时 LibreOffice 不看 before / after，扣不动。
# 按行数写的 beforeLines / afterLines 不用管：只要写了 before / after，LibreOffice 就只认后者（两版实测）
_AUTOSPACING = ("beforeAutospacing", "afterAutospacing")
# 修订标记、超链接这类包装要穿过去；图片、文本框、公式里的 run 不属于这一行
_NESTED = (
    qn("w:drawing"),
    qn("w:pict"),
    qn("w:object"),
    qn("w:txbxContent"),
    qn("w:pPr"),
    qn("w:rPr"),
)
# rPr 子元素的先后顺序里排在 w:position 之后的；新建 w:position 时要插在它们前面
_AFTER_POSITION = (
    "w:sz",
    "w:szCs",
    "w:highlight",
    "w:u",
    "w:effect",
    "w:bdr",
    "w:shd",
    "w:fitText",
    "w:vertAlign",
    "w:rtl",
    "w:cs",
    "w:em",
    "w:lang",
    "w:eastAsianLayout",
    "w:specVanish",
    "w:oMath",
)


def _text_width(xml: bytes) -> int | None:
    """正文版心宽度（缇）：最后一节的页宽减左右页边距。"""
    sect = parse_xml(xml).find(f"{qn('w:body')}/{qn('w:sectPr')}")
    size = sect.find(qn("w:pgSz")) if sect is not None else None
    margin = sect.find(qn("w:pgMar")) if sect is not None else None
    if size is None or margin is None:
        return None
    try:
        return (
            int(size.get(qn("w:w")))
            - int(margin.get(qn("w:left")) or 0)
            - int(margin.get(qn("w:right")) or 0)
        )
    except (TypeError, ValueError):
        return None


def _own_runs(parent: Any) -> Iterator[Any]:
    """这一行自己的 run：穿过修订标记、超链接这类包装，不进图片、文本框和公式。"""
    for child in parent:
        if child.tag == qn("w:r"):
            yield child
        elif child.tag not in _NESTED:
            yield from _own_runs(child)


def _text_runs(para: Any) -> list[Any]:
    """这一行里画得出字的 run：只有空白的、图片、域代码都不算。"""
    return [
        run
        for run in _own_runs(para)
        if any((node.text or "").strip() for node in run.iter(qn("w:t")))
    ]


def _line_text(para: Any) -> str:
    """这一行的文字；制表符记作 \\t、换行记作 \\n，用来估宽和判断是不是单行。"""
    out: list[str] = []
    for run in _own_runs(para):
        for node in run.iter(qn("w:t"), qn("w:tab"), qn("w:br")):
            if node.tag == qn("w:t"):
                out.append(node.text or "")
            else:
                out.append("\t" if node.tag == qn("w:tab") else "\n")
    return "".join(out)


def _fits_one_line(text: str, size: int, width: int) -> bool:
    """按偏宽的估算判断这段文字排得下在一行里（缇）。加行高只对单行段落是「总高不变」的。"""
    em = sum(
        1.0 if ord(ch) > 0x2E7F or ch == "\t" else 0.3 if ch == " " else 0.6
        for ch in text
    )
    return em * size <= 0.9 * width


def _twips(element: Any, attr: str) -> int:
    value = element.get(qn(f"w:{attr}")) if element is not None else None
    return int(value) if value is not None and value.isdigit() else 0


def _is_on(element: Any, attr: str) -> bool:
    """开关型属性是否开着；没写，或写成 false / 0 / off 的都算关。"""
    value = element.get(qn(f"w:{attr}")) if element is not None else None
    return value is not None and value not in _OFF


def _grow_line(
    spacing: Any, styles: _Styles, ppr: Any, height: int, target: float
) -> int:
    """行高往 target（缇）加，等量从段前、段后距里扣（先扣段前）；返回实际加了多少。"""
    if any(_is_on(styles.first(ppr, "spacing", name), name) for name in _AUTOSPACING):
        return 0
    before = _twips(styles.first(ppr, "spacing", "before"), "before")
    after = _twips(styles.first(ppr, "spacing", "after"), "after")
    # 先扣段前距但给它留一磅（别让文字贴到页眉横线上），不够再扣段后距
    spare = max(0, before - _KEEP_BEFORE)
    grown = min(math.ceil(target) - height, spare + after)
    if grown <= 0:
        return 0
    taken = min(grown, spare)
    if taken:
        spacing.set(qn("w:before"), str(before - taken))
    if grown > taken:
        spacing.set(qn("w:after"), str(after - (grown - taken)))
    spacing.set(qn("w:line"), str(height + grown))
    return grown


def _lowering(step: int, size: int) -> int:
    """``w:position`` 取 step 个半磅时文字实际下移多少（缇；size 是字号，缇）。

    LibreOffice 先把它折成「字号的百分之几」（四舍五入到整百分比），再按替代字体的行高
    （1.448 倍字号）位移，所以实际位移比标称值大四成多，字号越小档距越粗。本机 26.8 与
    镜像 25.2.3 实测一致。
    """
    percent = math.floor(1000 * step / size + 0.5)
    return math.floor(percent * _FALLBACK_LINES * size / 100)


def _lower_runs(para: Any, step: int) -> bool:
    """这一行里有字的 run 都下移 step 个半磅（上下标不跟着动）；返回有没有改到。"""
    changed = False
    for run in _text_runs(para):
        rpr = run.find(qn("w:rPr"))
        if rpr is not None and rpr.find(qn("w:vertAlign")) is not None:
            continue
        if rpr is None:
            rpr = run.makeelement(qn("w:rPr"), {})
            run.insert(0, rpr)
        position = rpr.find(qn("w:position"))
        if position is None:
            position = rpr.makeelement(qn("w:position"), {})
            rpr.insert_element_before(position, *_AFTER_POSITION)
        current = position.get(qn("w:val")) or "0"
        raised = int(current) if current.lstrip("-").isdigit() else 0
        position.set(qn("w:val"), str(raised - step))
        changed = True
    return changed


def _fit_fixed_lines(xml: bytes, styles: _Styles, width: int | None) -> bytes:
    """让会被削字顶的固定行高段落放得下字；没有要改的就原样返回这一段的字节。"""
    root = parse_xml(xml)
    changed = False
    for para in root.iter(qn("w:p")):
        text = _line_text(para)
        if not _CJK.search(text):
            continue  # 只有拉丁字母的行字顶够低，不会被削
        ppr = para.find(qn("w:pPr"))
        rule = styles.first(ppr, "spacing", "lineRule")
        line = styles.first(ppr, "spacing", "line")
        declared = line.get(qn("w:line")) if line is not None else None
        if (
            rule is None
            or rule.get(qn("w:lineRule")) != "exact"
            or declared is None
            or not declared.isdigit()
            or declared == "0"
        ):
            continue
        height = int(declared)
        # 按「画得出字的 run」各自求有效字号再取最大：段落里混着的空 run、段落标记的字号不算数
        runs = _text_runs(para)
        if not runs:
            continue
        size = max(styles.run_half_points(run, ppr) for run in runs) * 10  # 缇
        top = _IDEOGRAPH_TOP * size
        if top - _ASCENT_SHARE * height < _VISIBLE_CLIP:
            continue
        bottom = (_DEEP_BOTTOM if _DEEP.search(text) else _CJK_BOTTOM) * size
        spacing = _own_spacing(para)
        if (
            width is not None
            and "\n" not in text
            and not any(a.tag == qn("w:tc") for a in para.iterancestors())
            and _fits_one_line(text, size, width)
        ):
            # 行框加高到字顶字底都放得下；多出来的高度从段前段后距里来，段落总高不变
            grown = _grow_line(
                spacing,
                styles,
                ppr,
                height,
                max(size, top / _ASCENT_SHARE, bottom / (1 - _ASCENT_SHARE)),
            )
            changed = changed or grown > 0
            height += grown
        clip = top - _ASCENT_SHARE * height
        if clip <= 1:
            continue
        # 借不到（够）段距：把文字在行框内往下挪，取刚好够的最小一档，且字底不出框
        room = (1 - _ASCENT_SHARE) * height - bottom + _BOTTOM_SLACK
        steps = [step for step in range(1, 9) if _lowering(step, size) <= room]
        if not steps:
            continue
        enough = [step for step in steps if _lowering(step, size) >= clip]
        changed = _lower_runs(para, enough[0] if enough else steps[-1]) or changed
    return serialize_part_xml(root) if changed else xml


def docx_to_pdf(docx: bytes, *, soffice: str | None = None) -> bytes:
    """回填后的 docx → PDF 字节；转不出来抛 503（提示里带「改用下载」）。

    交给 LibreOffice 的是 :func:`print_copy`，不是原件。一次转换一个 soffice 进程、
    一个临时目录（配置目录 + 输入输出 + 字体配置），用完即删：多个进程共用配置目录
    会互相锁住。LibreOffice 按源文件名给输出命名（``<源名>.pdf``），所以源文件用
    固定名字，批号不落到临时文件名里。
    """
    binary = soffice or find_soffice()
    if binary is None:
        raise AppException(
            status_code=503,
            message="服务器没有安装 LibreOffice，不能生成打印版。请改用「下载 COA」，"
            "用 Word 或 WPS 打开后打印。",
        )
    with tempfile.TemporaryDirectory(prefix="coa-print-") as work:
        root = Path(work)
        (root / "profile").mkdir()
        (root / "out").mkdir()
        source = root / "COA.docx"
        source.write_bytes(print_copy(docx))
        fonts_conf = root / "fonts.conf"
        fonts_conf.write_text(fontconfig_for_print(), encoding="utf-8")
        try:
            proc = subprocess.run(
                [
                    binary,
                    "--headless",
                    "--norestore",
                    "--nolockcheck",
                    f"-env:UserInstallation={(root / 'profile').as_uri()}",
                    "--convert-to",
                    "pdf:writer_pdf_Export",
                    "--outdir",
                    str(root / "out"),
                    str(source),
                ],
                capture_output=True,
                timeout=_CONVERT_TIMEOUT,
                env={**os.environ, "FONTCONFIG_FILE": str(fonts_conf)},
            )
        except subprocess.TimeoutExpired as exc:
            raise AppException(
                status_code=503,
                message="打印版转换超时。请稍后重试；仍然不行请改用「下载 COA」。",
            ) from exc
        produced = root / "out" / "COA.pdf"
        pdf = produced.read_bytes() if produced.is_file() else b""
    if not pdf.startswith(b"%PDF-"):
        # javaldx 一类警告即使成功也会写到 stderr，所以只在失败时才看它
        logger.warning(
            "COA 打印版转换失败：exit=%s stderr=%s",
            proc.returncode,
            proc.stderr.decode("utf-8", "replace")[-300:],
        )
        raise AppException(
            status_code=503,
            message="打印版转换失败。请稍后重试；仍然不行请改用「下载 COA」。",
        )
    return pdf


def pdf_name_of(docx_name: str) -> str:
    """打印版的文件名：与下载的 docx 同名，只换扩展名（浏览器标签页和打印任务名都用它）。"""
    stem = (
        docx_name[: -len(".docx")] if docx_name.lower().endswith(".docx") else docx_name
    )
    return f"{stem}.pdf"


# ─────────────────────── 缓存 ───────────────────────

# 转换规则版本：打印副本的处理或字体映射变了就加一，旧缓存自动作废
_PRINT_POLICY = 6


def cache_key(docx: bytes) -> str:
    """docx 内容的指纹，缓存靠它认「同一份」。

    不能直接对字节做摘要：python-docx 保存时把当前时间写进 zip 条目，同一份内容
    每隔两秒生成的字节就不一样，缓存会莫名失效。这里只看各条目的名字和内容校验值，
    再带上转换规则版本——打印副本或字体映射变了，同一份 docx 也要重新转。
    """
    digest = hashlib.sha256(f"coa-print-policy:{_PRINT_POLICY}\n".encode())
    with zipfile.ZipFile(io.BytesIO(docx)) as archive:
        for info in sorted(archive.infolist(), key=lambda item: item.filename):
            digest.update(f"{info.filename}\0{info.CRC:08x}\0".encode())
    return digest.hexdigest()


def _cache_root() -> Path:
    return Path(tempfile.gettempdir()) / "dazah-coa-print"


def _cache_file(root: Path, key: str) -> Path:
    return root / key[:2] / f"{key}.pdf"


def read_cached_pdf(key: str) -> bytes | None:
    """命中返回 PDF 字节；没有、或者内容不是一份完整 PDF（写了一半/损坏）都算没命中。"""
    try:
        data = _cache_file(_cache_root(), key).read_bytes()
    except OSError:
        return None
    intact = data.startswith(b"%PDF-") and data.rstrip().endswith(b"%%EOF")
    return data if intact else None


_last_sweep = 0.0


def write_cached_pdf(key: str, pdf: bytes, *, now: float | None = None) -> None:
    """先写临时文件再改名：读的一方不会看到写了一半的 PDF。

    写不进去只记日志、不影响出文件——缓存只是省时间。顺带清一次过期文件。
    """
    root = _cache_root()
    target = _cache_file(root, key)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(f"{key}.{os.getpid()}.tmp")
        partial.write_bytes(pdf)
        os.replace(partial, target)
    except OSError:
        logger.warning("COA 打印版缓存写入失败", exc_info=True)
        return
    _sweep_if_due(root, now if now is not None else time.time())


def _sweep_if_due(root: Path, now: float) -> None:
    """每小时清一次过期文件；只跟在写入之后调用，不会并发扫。"""
    global _last_sweep
    if now - _last_sweep < _SWEEP_INTERVAL:
        return
    _last_sweep = now
    removed = 0
    for path in root.glob("*/*.pdf"):
        try:
            expired = now - path.stat().st_mtime > _CACHE_TTL
        except OSError:
            continue
        if expired:
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
    if removed:
        logger.info("COA 打印版缓存清理：%d 个过期文件", removed)


# 每个事件循环一个信号量：模块级的 asyncio 锁会绑死在第一次用到它的那个循环上
_gates: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


def _gate() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    gate = _gates.get(loop)
    if gate is None:
        gate = _gates[loop] = asyncio.Semaphore(_CONVERT_CONCURRENCY)
    return gate


async def _pdf_for(docx: bytes) -> bytes:
    key = cache_key(docx)
    cached = await asyncio.to_thread(read_cached_pdf, key)
    if cached is not None:
        return cached
    async with _gate():
        # 排队期间，前面那个请求可能已经把同一份转好了
        cached = await asyncio.to_thread(read_cached_pdf, key)
        if cached is not None:
            return cached
        pdf = await asyncio.to_thread(docx_to_pdf, docx)
        await asyncio.to_thread(write_cached_pdf, key, pdf)
        return pdf


# ─────────────────────── 留档与日志 ───────────────────────


async def _record_print(
    db: AsyncSession,
    report_id: uuid.UUID,
    *,
    docx: bytes,
    docx_name: str,
    check: dict[str, Any],
    user: User | None,
) -> None:
    """出文件即留档，与下载同一口径；同一份内容已经留过底稿时只记日志，不重复留。"""
    report = await get_report_or_404(db, report_id)
    standard = await get_standard_or_404(db, report.standard_id)
    # 「同一份内容」= 同一份模板 + 写入了同样的值。不能比文件摘要：留档存的是 docx
    # 的原始字节，里面带保存时间，同一份内容每次生成的摘要都不一样
    history, _total = await repo.list_render_records(db, report_id=report.id)
    kept = [
        record
        for record in history
        if record.template_sha256 == standard.template_sha256
        and (record.values_snapshot or {}).get("fields") == check.get("writes")
    ]
    if kept:
        product = await repo.get_product(db, report.product_id)
        await record_report_log(
            db,
            action=COA_LOG_ACTION_RENDERED,
            report=report,
            user=user,
            product_name=product.name if product else None,
            standard_code=standard.code,
            new_cells={
                "COA 文件": {
                    "值": pdf_name_of(docx_name),
                    "备注": "快速打印；内容与已有留档一致，没有重复留档",
                }
            },
            record_id=str(kept[0].id),
            file_sha256=kept[0].file_sha256,
        )
        return
    await archive_render(
        db,
        report=report,
        standard=standard,
        data=docx,
        filename=docx_name,
        check=check,
        user=user,
    )


async def render_report_pdf(
    db: AsyncSession, report_id: uuid.UUID, user: User | None = None
) -> tuple[bytes, str]:
    """生成打印版 PDF 及其文件名；有拦截项时抛 422（与下载是同一套预检）。

    先拿到 PDF、再留档记日志、最后才返回：留不下来就不出文件，与下载同一口径。
    """
    docx, docx_name, check = await build_report_docx(db, report_id)
    pdf = await _pdf_for(docx)
    await _record_print(
        db, report_id, docx=docx, docx_name=docx_name, check=check, user=user
    )
    return pdf, pdf_name_of(docx_name)


def print_failure_lines(exc: AppException) -> list[str]:
    """把拦截原因说成人话，给新标签页里的错误提示用；说不出细节的错误返回空。"""
    detail = exc.detail_msg
    if isinstance(detail, dict) and isinstance(detail.get("blocking"), list):
        lines: list[str] = []
        for item in detail["blocking"]:
            kind = str(item.get("kind"))
            if kind == "missing":
                lines.append(f"没有登记值：{item.get('label')}")
            elif kind == "stale":
                lines.append(
                    f"模板里的旧值「{item.get('sample')}」还会出现在输出里，有位置没标注到"
                )
        return lines
    if isinstance(detail, list):
        return [str(item) for item in detail]
    return []
