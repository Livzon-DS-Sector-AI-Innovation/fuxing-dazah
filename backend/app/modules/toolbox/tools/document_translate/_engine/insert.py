"""译文回写：直接对 document.xml 做最小化手术，不动任何格式定义结构。

- 双语对照：深拷贝原段落 XML 插入其后，译文写入拷贝（格式 100% 继承）
- 标题：同段追加 " / 译文"
- 替换模式：原段落重建为单一 run（沿用首个有文字 run 的字符格式）
- 自动编号：项目符号保留；有序编号在拷贝中取消编号并对齐缩进（避免 1,2,3,4 重编号）
"""
from __future__ import annotations

from copy import deepcopy

from docx.oxml.ns import qn
from lxml import etree

XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

# w:pPr 子元素的 schema 顺序（常用子集），保证插入的节点位置合法，
# 避免触发 Word 的"文件损坏修复"。
_PPR_ORDER = [
    "pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl",
    "numPr", "suppressLineNumbers", "pBdr", "shd", "tabs", "suppressAutoHyphens",
    "kinsoku", "wordWrap", "overflowPunct", "topLinePunct", "autoSpaceDE", "autoSpaceDN",
    "bidi", "adjustRightInd", "snapToGrid", "spacing", "ind", "contextualSpacing",
    "mirrorIndents", "suppressOverlap", "jc", "textDirection", "textAlignment",
    "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr", "sectPr", "pPrChange",
]
_PPR_RANK = {qn(f"w:{t}"): i for i, t in enumerate(_PPR_ORDER)}

_CONTENT_TAGS = {
    qn("w:r"), qn("w:hyperlink"), qn("w:fldSimple"), qn("w:proofErr"), qn("w:smartTag"),
    qn("w:softHyphen"), qn("w:noBreakHyphen"), qn("w:ins"), qn("w:del"),
    qn("w:moveFrom"), qn("w:moveTo"),
}


def _el(tag: str, **attrs) -> etree._Element:
    e = etree.Element(qn(f"w:{tag}"))
    for k, v in attrs.items():
        e.set(qn(f"w:{k}"), v)
    return e


def _insert_ppr_ordered(ppr, child) -> None:
    rank = _PPR_RANK.get(child.tag, 10_000)
    for existing in ppr:
        if _PPR_RANK.get(existing.tag, 10_000) > rank:
            existing.addprevious(child)
            return
    ppr.append(child)


def _first_nonempty_rpr(p):
    """第一个有文字的 run 的字符格式（rPr），作为整段统一格式。"""
    for r in p.iter(qn("w:r")):
        if any((t.text or "").strip() for t in r.findall(qn("w:t"))):
            rpr = r.find(qn("w:rPr"))
            return deepcopy(rpr) if rpr is not None else None
    return None


def _rebuild_uniform(p, text: str, strip_all: bool) -> None:
    """删除段落全部内容节点，写入单一 run。

    strip_all=True  （双语拷贝）：仅保留 pPr，连书签一并去掉（避免书签名重复）
    strip_all=False（替换原文）：保留书签与批注锚点，维持交叉引用可解析
    """
    ppr = p.find(qn("w:pPr"))
    rpr = _first_nonempty_rpr(p)
    for child in list(p):
        if child is ppr:
            continue
        if not strip_all and child.tag not in _CONTENT_TAGS:
            continue  # 书签/批注范围标记原样保留
        p.remove(child)
    run = _el("r")
    if rpr is not None:
        run.append(rpr)
    t = _el("t")
    t.set(XML_SPACE, "preserve")
    t.text = text
    run.append(t)
    p.append(run)


def get_numbering_element(doc):
    from docx.opc.constants import RELATIONSHIP_TYPE as RT

    for rel in doc.part.rels.values():
        if rel.reltype == RT.NUMBERING:
            return rel.target_part.element
    return None


def _numbering_info(num_el, num_id: str, ilvl: int):
    """返回 (是否项目符号, 编号缩进左值 twips 或 None)。"""
    if num_el is None or num_id in (None, "", "0"):
        return False, None
    abstract_id = None
    for num in num_el.findall(qn("w:num")):
        if num.get(qn("w:numId")) == num_id:
            aid = num.find(qn("w:abstractNumId"))
            abstract_id = aid.get(qn("w:val")) if aid is not None else None
            break
    if abstract_id is None:
        return False, None
    for absnum in num_el.findall(qn("w:abstractNum")):
        if absnum.get(qn("w:abstractNumId")) != abstract_id:
            continue
        for lvl in absnum.findall(qn("w:lvl")):
            if lvl.get(qn("w:ilvl")) != str(ilvl):
                continue
            fmt = lvl.find(qn("w:numFmt"))
            is_bullet = fmt is not None and fmt.get(qn("w:val")) == "bullet"
            left = None
            ind = lvl.find(qn("w:pPr") + "/" + qn("w:ind"))
            if ind is not None and ind.get(qn("w:left")):
                left = ind.get(qn("w:left"))
            return is_bullet, left
    return False, None


def _fix_copy_numbering(copy, unit, num_el, notes: list[str]) -> None:
    """双语拷贝中的自动编号处理。

    项目符号：保留（每段独立符号，不重编号）。
    有序编号：取消编号（直接 numPr 删除 / 样式编号用 numId=0 覆盖），
    并按编号定义的缩进对齐译文行，避免译文行参与 1,2,3,4 重编号。
    """
    if not unit.has_numbering:
        return
    ppr = copy.find(qn("w:pPr"))
    if ppr is None:
        return
    is_bullet, left = _numbering_info(num_el, unit.num_id, unit.ilvl)
    if is_bullet:
        return
    direct = ppr.find(qn("w:numPr"))
    if direct is not None:
        ppr.remove(direct)
    else:  # 编号来自段落样式 → 用 numId=0 显式覆盖
        override = _el("numPr")
        override.append(_el("ilvl", val="0"))
        override.append(_el("numId", val="0"))
        _insert_ppr_ordered(ppr, override)
    if left is not None:
        ind = ppr.find(qn("w:ind"))
        if ind is None:
            ind = _el("ind")
            _insert_ppr_ordered(ppr, ind)
        ind.set(qn("w:left"), left)
        for attr in ("w:firstLine", "w:hanging", "w:start", "w:end"):
            if ind.get(qn(attr)) is not None:
                del ind.attrib[qn(attr)]
    else:
        notes.append(f"#{unit.idx} 编号段落缩进未能精确对齐")


def insert_bilingual(unit, translation: str, num_el, notes: list[str]) -> str:
    """插入双语对照。标题走同段追加，其余插入深拷贝段落。"""
    if unit.is_heading:
        _append_heading_translation(unit.para, translation)
        return "heading"
    copy = deepcopy(unit.para)
    ppr = copy.find(qn("w:pPr"))
    if ppr is not None and ppr.find(qn("w:sectPr")) is not None:
        # 分节符不能随拷贝复制，否则版式结构被破坏
        ppr.remove(ppr.find(qn("w:sectPr")))
    _fix_copy_numbering(copy, unit, num_el, notes)
    _rebuild_uniform(copy, translation, strip_all=True)
    unit.para.addnext(copy)
    return "copy"


def _append_heading_translation(p, translation: str) -> None:
    """标题同段追加：'中文标题 / English Title'。"""
    src = None
    for r in p.iter(qn("w:r")):
        if any((t.text or "").strip() for t in r.findall(qn("w:t"))):
            src = r
            break
    if src is None:
        return
    new_r = deepcopy(src)
    rpr = new_r.find(qn("w:rPr"))
    for child in list(new_r):
        if child is not rpr:
            new_r.remove(child)
    t = _el("t")
    t.set(XML_SPACE, "preserve")
    t.text = f" / {translation}"
    new_r.append(t)
    p.append(new_r)


def replace_paragraph(unit, translation: str, notes: list[str]) -> None:
    """替换模式：原段重建为单一 run。注意：段内域会被静态化、超链接转纯文本。"""
    _rebuild_uniform(unit.para, translation, strip_all=False)


def set_update_fields(doc) -> None:
    """让 Word 下次打开时提示更新域（目录/页码随双语内容变化刷新）。"""
    settings = doc.settings.element
    if settings.find(qn("w:updateFields")) is None:
        settings.append(_el("updateFields", val="true"))


def refuse_if_tracked_changes(doc) -> None:
    """含修订痕迹的文档直接拒收，要求先接受/拒绝所有修订。"""
    root = doc.element
    if root.find(".//" + qn("w:ins")) is not None or root.find(".//" + qn("w:del")) is not None:
        raise ValueError("文档含有修订痕迹（tracked changes）。请先在 Word 中接受/拒绝全部修订后再翻译。")
