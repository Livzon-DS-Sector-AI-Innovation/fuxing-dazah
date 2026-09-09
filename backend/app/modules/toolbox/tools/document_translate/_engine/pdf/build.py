"""重排式 DOCX 生成：把抽取的结构块（标题/段落/表格/图片）+ 译文写成新 Word 文档。

PDF 无法原位回写（打印坐标流），输出为干净重排：
  - 标题 → Word 内置 Heading 样式（层级保留，导航窗格可用）
  - 段落 → 正文段落；对照模式下译文段紧随原文段（段后对照）
  - 表格 → Table Grid 样式重建；对照模式下单元格内"原文段+译文段"
  - 图片 → 不翻译，按原页面位置居中嵌入，宽度按原始显示宽度等比换算
  - 标题对照沿用 docx 流水线惯例：同段追加为 "原文 / 译文"
行内字符格式（粗斜体混排）不保留——重排输出以内容与结构为准。
"""
from __future__ import annotations

from io import BytesIO

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

# 中文正文字体（Word 全平台自带，避免目标机器缺字体）
_EAST_ASIA = "宋体"
# 嵌入图片的最大宽度（英寸）：默认模板 Letter/A4 页宽减页边距后的可用宽度
_MAX_IMAGE_WIDTH_IN = 6.3


def _set_cjk_font(style, latin: str):
    """样式同时设置西文与中文字体（python-docx 只设 latin，eastAsia 需手写 XML）。"""
    style.font.name = latin
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), _EAST_ASIA)


def _fill_para(p, text: str):
    """往已有段落填文本。换行转为软换行（保留表格单元格内的多行内容）。"""
    chunks = text.split("\n")
    for i, chunk in enumerate(chunks):
        if i:
            p.add_run().add_break(WD_BREAK.LINE)
        if chunk:
            p.add_run(chunk)
    return p


def _add_text_para(container, text: str, style=None):
    return _fill_para(container.add_paragraph(style=style), text)


def build_docx(blocks, mode: str, title: str = ""):
    """结构块 + 译文 → (Document, 段落总数)。

    mode: bilingual=段后对照；replace=仅译文（无译文的块保留原文）。
    mock 模式下译文=原文，对照行自动省略，避免重复。
    """
    doc = Document()
    _set_cjk_font(doc.styles["Normal"], "Times New Roman")
    doc.styles["Normal"].font.size = Pt(11)
    for i in range(1, 5):
        try:
            _set_cjk_font(doc.styles[f"Heading {i}"], "Times New Roman")
        except KeyError:
            break

    if title:
        _add_text_para(doc, title)

    for b in blocks:
        if b.kind == "table":
            _build_table(doc, b, mode)
            continue
        if b.kind == "image":
            _build_image(doc, b)
            continue
        trans = b.unit.translation if b.unit else ""
        if b.kind == "heading":
            style = f"Heading {min(max(b.level, 1), 4)}"
            if mode == "bilingual" and trans and trans != b.text:
                _add_text_para(doc, f"{b.text} / {trans}", style=style)
            else:
                _add_text_para(doc, trans or b.text, style=style)
        elif mode == "bilingual":
            _add_text_para(doc, b.text)
            if trans and trans != b.text:
                _add_text_para(doc, trans)
        else:
            _add_text_para(doc, trans or b.text)

    expected = len(list(doc.element.body.iter(qn("w:p"))))
    return doc, expected


def _build_image(doc, b):
    """图片块：居中嵌入，宽度 = 原始显示宽度（pt→英寸），超页宽等比缩到可用宽度。

    始终显式定宽（不依赖 PNG 分辨率元数据），高度按比例自适应。
    """
    if not b.image_bytes:
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    width_in = max(min(b.image_w_pt / 72.0, _MAX_IMAGE_WIDTH_IN), 0.3)
    try:
        p.add_run().add_picture(BytesIO(b.image_bytes), width=Inches(width_in))
    except Exception as e:  # noqa: BLE001 —— 显式报错，指明哪一页的图嵌入失败
        raise ValueError(f"第 {b.page} 页图片嵌入失败：{e}") from e


def _build_table(doc, b, mode: str):
    rows = b.rows
    if not rows:
        return
    n_cols = max(len(r) for r in rows)
    table = doc.add_table(rows=len(rows), cols=n_cols)
    table.style = "Table Grid"
    cell_map = {(r, c): u for r, c, u in b.cell_units}
    for r, row in enumerate(rows):
        for c in range(n_cols):
            text = row[c] if c < len(row) and row[c] else ""
            if not text:
                continue  # 空单元格保持默认空段
            u = cell_map.get((r, c))
            trans = u.translation if u else ""
            cell = table.cell(r, c)
            if mode == "bilingual":
                _fill_para(cell.paragraphs[0], text)
                if trans and trans != text:
                    _add_text_para(cell, trans)
            else:
                _fill_para(cell.paragraphs[0], trans or text)
