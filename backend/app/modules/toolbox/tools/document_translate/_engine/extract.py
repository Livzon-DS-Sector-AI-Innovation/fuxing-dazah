"""从 docx 中抽取可翻译的段落单元。

核心原则：以 w:p（段落）为最小翻译单位，覆盖正文与表格单元格；
跳过目录（TOC）与文本框内容（后者仅计数并写入报告）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from docx.oxml.ns import qn

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]")

_HEADING_STYLE_RE = re.compile(r"^(heading|标题)\s*\d", re.IGNORECASE)
_TITLE_STYLE_RE = re.compile(r"^(title|标题)$", re.IGNORECASE)
_TOC_STYLE_RE = re.compile(r"^(toc|目录)", re.IGNORECASE)


@dataclass
class Unit:
    """一个待处理段落。para 是 lxml 的 w:p 元素引用，全程有效。"""

    idx: int
    para: object
    text: str
    lang: str = "other"          # zh / en / other
    style_name: str = ""
    is_heading: bool = False
    in_table: bool = False
    has_field: bool = False       # 含域代码（SEQ/PAGE/交叉引用等）
    has_hyperlink: bool = False   # 含超链接
    has_numbering: bool = False   # 直接或经由样式带自动编号/项目符号
    num_id: str | None = None
    ilvl: int = 0
    mixed_format: bool = False    # 段内存在多种字符格式（替换后会被拉平）

    action: str = "skip"          # translate / skip
    reason: str = ""
    translation: str = ""


@dataclass
class ExtractStats:
    total_paragraphs: int = 0
    empty: int = 0
    toc_skipped: int = 0
    textbox_skipped: int = 0
    no_translatable_text: int = 0
    comment_refs: int = 0


def _para_text(p) -> str:
    return "".join(t.text or "" for t in p.iter(qn("w:t"))).strip()


def _ancestors(p):
    return p.iterancestors()


def _in_textbox(p) -> bool:
    return any(a.tag == qn("w:txbxContent") for a in _ancestors(p))


def _in_table(p) -> bool:
    return any(a.tag == qn("w:tc") for a in _ancestors(p))


def _in_toc_sdt(p) -> bool:
    """目录常被包裹在 w:sdt（内容控件）中，通过 docPartGallery 识别。"""
    for a in _ancestors(p):
        if a.tag == qn("w:sdt"):
            gal = a.find(qn("w:sdtPr") + "/" + qn("w:docPartObj") + "/" + qn("w:docPartGallery"))
            if gal is not None and "table of contents" in (gal.get(qn("w:val")) or "").lower():
                return True
    return False


def _style_maps(doc):
    """返回 (style_id -> 样式名, style_id -> 样式元素)。"""
    names, elems = {}, {}
    for st in doc.styles._element.findall(qn("w:style")):
        sid = st.get(qn("w:styleId")) or ""
        names[sid] = sid
        name_el = st.find(qn("w:name"))
        if name_el is not None and name_el.get(qn("w:val")):
            names[sid] = name_el.get(qn("w:val"))
        elems[sid] = st
    return names, elems


def _style_numpr(style_el, elems, depth=0):
    """沿 basedOn 链查找样式上的自动编号（List Number 等模板样式即此情况）。"""
    if style_el is None or depth > 4:
        return None
    ppr = style_el.find(qn("w:pPr"))
    if ppr is not None:
        numpr = ppr.find(qn("w:numPr"))
        if numpr is not None:
            return numpr
    based = style_el.find(qn("w:basedOn"))
    if based is not None:
        return _style_numpr(elems.get(based.get(qn("w:val"))), elems, depth + 1)
    return None


def _is_mixed_format(p) -> bool:
    """段内有文本的 run 之间字符格式（rPr）不一致 → 替换后格式会被拉平。"""
    import lxml.etree as etree

    seen = set()
    for r in p.iter(qn("w:r")):
        if not any((t.text or "").strip() for t in r.findall(qn("w:t"))):
            continue
        rpr = r.find(qn("w:rPr"))
        seen.add(etree.tostring(rpr) if rpr is not None else b"")
        if len(seen) > 1:
            return True
    return False


def detect_lang(text: str) -> str:
    cjk = len(CJK_RE.findall(text))
    latin = len(LATIN_RE.findall(text))
    if cjk == 0 and latin == 0:
        return "other"
    if cjk == 0:
        return "en"
    if latin == 0:
        return "zh"
    return "zh" if cjk / (cjk + latin) >= 0.25 else "en"


def extract(doc):
    """遍历 document.xml，返回 (units, stats)。"""
    style_names, style_elems = _style_maps(doc)
    body = doc.element.body
    units: list[Unit] = []
    stats = ExtractStats()

    for i, p in enumerate(body.iter(qn("w:p"))):
        stats.total_paragraphs += 1
        text = _para_text(p)

        if not text:
            stats.empty += 1
            continue
        if _in_textbox(p):
            stats.textbox_skipped += 1
            continue
        if _in_toc_sdt(p):
            stats.toc_skipped += 1
            continue

        ppr = p.find(qn("w:pPr"))
        style_id = ""
        if ppr is not None:
            ps = ppr.find(qn("w:pStyle"))
            if ps is not None:
                style_id = ps.get(qn("w:val")) or ""
        style_name = style_names.get(style_id, style_id)

        has_field = bool(
            p.findall(".//" + qn("w:fldChar"))
            or p.findall(".//" + qn("w:instrText"))
            or p.findall(".//" + qn("w:fldSimple"))
        )
        has_hyperlink = bool(p.findall(".//" + qn("w:hyperlink")))

        # 目录段落：样式为 TOC、含 TOC 域代码、或含指向 _Toc 书签的内部链接
        is_toc_para = _TOC_STYLE_RE.match(style_name or "") is not None
        if not is_toc_para:
            for it in p.findall(".//" + qn("w:instrText")):
                if it.text and "TOC" in it.text.upper():
                    is_toc_para = True
                    break
        if not is_toc_para:
            for h in p.findall(".//" + qn("w:hyperlink")):
                if (h.get(qn("w:anchor")) or "").startswith("_Toc"):
                    is_toc_para = True
                    break
        if is_toc_para:
            stats.toc_skipped += 1
            continue

        if p.findall(".//" + qn("w:commentReference")):
            stats.comment_refs += 1

        is_heading = bool(
            _HEADING_STYLE_RE.match(style_name or "")
            or _TITLE_STYLE_RE.match(style_name or "")
            or (ppr is not None and ppr.find(qn("w:outlineLvl")) is not None)
        )

        # 自动编号：段内直接 numPr 优先，否则查样式链
        num_id, ilvl = None, 0
        numpr = None
        if ppr is not None:
            numpr = ppr.find(qn("w:numPr"))
        if numpr is None and style_id:
            numpr = _style_numpr(style_elems.get(style_id), style_elems)
        if numpr is not None:
            nid = numpr.find(qn("w:numId"))
            lvl = numpr.find(qn("w:ilvl"))
            num_id = nid.get(qn("w:val")) if nid is not None else None
            ilvl = int(lvl.get(qn("w:val"))) if lvl is not None else 0

        lang = detect_lang(text)
        if lang == "other":
            stats.no_translatable_text += 1
            continue

        units.append(
            Unit(
                idx=i,
                para=p,
                text=text,
                lang=lang,
                style_name=style_name,
                is_heading=is_heading,
                in_table=_in_table(p),
                has_field=has_field,
                has_hyperlink=has_hyperlink,
                has_numbering=numpr is not None,
                num_id=num_id,
                ilvl=ilvl,
                mixed_format=_is_mixed_format(p),
            )
        )
    return units, stats
