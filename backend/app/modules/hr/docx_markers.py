"""docx 模板标记替换工具 — 培训导出模板（用户可自维护）共用。

模板里的 ``{中文}`` 标记经常被 Word 拆分到多个 run，逐 run 替换必然漏掉；
统一走「整段合并 → 替换 → 写回首个 run」的方式（保留首 run 格式）。
覆盖范围：正文段落、表格单元格（含嵌套表格）、页眉页脚段落。

各生成器的标记清单见 training_template_registry（同一份数据源驱动上传校验
与前端占位符说明）。
"""

import re
from collections.abc import Iterator
from io import BytesIO

from docx import Document
from docx.document import Document as DocumentObject
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

# 残留标记清理：{xxx} / {#xxx} / {/xxx}（成绩单清理逻辑同款正则）
LEFTOVER_MARKER_RE = re.compile(r"\{[#/]?[^}]*\}")


# ───────────────────────── 段落遍历 ─────────────────────────


def _iter_cell_paragraphs(cell: _Cell) -> Iterator[Paragraph]:
    yield from cell.paragraphs
    for nested in cell.tables:
        yield from _iter_table_paragraphs(nested)


def _iter_table_paragraphs(table: Table) -> Iterator[Paragraph]:
    for row in table.rows:
        for cell in row.cells:
            yield from _iter_cell_paragraphs(cell)


def iter_document_paragraphs(doc: DocumentObject) -> Iterator[Paragraph]:
    """正文段落 + 表格单元格段落（含嵌套）+ 页眉页脚段落。"""
    yield from doc.paragraphs
    for table in doc.tables:
        yield from _iter_table_paragraphs(table)
    for section in doc.sections:
        for part in (
            section.header, section.footer,
            section.first_page_header, section.first_page_footer,
            section.even_page_header, section.even_page_footer,
        ):
            if part is not None:
                yield from part.paragraphs


def _paragraph_text(paragraph: Paragraph) -> str:
    return "".join(r.text or "" for r in paragraph.runs)


def _rewrite_paragraph(paragraph: Paragraph, text: str) -> None:
    """整段写回首个 run（保留首 run 格式），其余 run 清空。"""
    if paragraph.runs:
        paragraph.runs[0].text = text
        for r in paragraph.runs[1:]:
            r.text = ""
    else:
        paragraph.add_run(text)


# ───────────────────────── 标记替换 / 校验 ─────────────────────────


def replace_markers(doc: DocumentObject, mapping: dict[str, str]) -> None:
    """全文替换标记；标记跨 run 拆分也能命中。未变化的段落不动（保留原格式）。"""
    for paragraph in iter_document_paragraphs(doc):
        _replace_in_paragraph(paragraph, mapping)


def _replace_in_paragraph(paragraph: Paragraph, mapping: dict[str, str]) -> None:
    full = _paragraph_text(paragraph)
    if "{" not in full:
        return
    replaced = full
    for name, value in mapping.items():
        if name in replaced:
            replaced = replaced.replace(name, value)
    if replaced != full:
        _rewrite_paragraph(paragraph, replaced)


def replace_markers_in_row(row, mapping: dict[str, str]) -> None:
    """行级替换（克隆出的数据行填充用），语义同 replace_markers。"""
    seen_tcs: list = []
    for cell in row.cells:
        if cell._tc in seen_tcs:  # 合并单元格会重复出现，跳过已处理
            continue
        seen_tcs.append(cell._tc)
        for paragraph in cell.paragraphs:
            _replace_in_paragraph(paragraph, mapping)


def collect_template_text(source: bytes | DocumentObject) -> str:
    """收集模板全文（段落换行连接），供上传校验扫描必填标记。"""
    doc = source if isinstance(source, DocumentObject) else Document(BytesIO(source))
    return "\n".join(_paragraph_text(p) for p in iter_document_paragraphs(doc))


def find_missing_markers(required: list[str], source: bytes | DocumentObject) -> list[str]:
    """返回模板全文中缺失的必填标记清单。

    兼容日期过滤写法：注册键写 ``{入职日期}``，模板里 ``{入职日期| customDate:'…'}``
    也算命中（登记表/花名册的既有写法）。
    """
    text = collect_template_text(source)
    missing = []
    for name in required:
        if name in text:
            continue
        inner = name.strip("{}")
        if re.search(r"\{" + re.escape(inner) + r"\|[^}]*\}", text):
            continue
        missing.append(name)
    return missing


def clear_unused_markers(doc: DocumentObject) -> None:
    """清理替换后残留的 {xxx} 标记（含循环标记），避免字面量出现在导出文件里。"""
    for paragraph in iter_document_paragraphs(doc):
        full = _paragraph_text(paragraph)
        if "{" not in full:
            continue
        cleaned = LEFTOVER_MARKER_RE.sub("", full)
        if cleaned != full:
            _rewrite_paragraph(paragraph, cleaned)


# ───────────────────────── 行定位与克隆 ─────────────────────────


def row_text(row) -> str:
    return "".join(cell.text for cell in row.cells)


def find_row_index_by_marker(table: Table, marker: str) -> int | None:
    """返回第一个包含指定标记文本的行下标；找不到返回 None。"""
    for idx, row in enumerate(table.rows):
        if marker in row_text(row):
            return idx
    return None


def insert_cloned_row(table: Table, ref_idx: int) -> int:
    """在 ref_idx 行之后深拷贝插入一行，返回新行下标（样式随模板行）。"""
    import copy

    ref_tr = table.rows[ref_idx]._tr
    new_tr = copy.deepcopy(ref_tr)
    ref_tr.addnext(new_tr)
    return ref_idx + 1


def remove_row(table: Table, row_idx: int) -> None:
    table._tbl.remove(table.rows[row_idx]._tr)


def set_cell_text(cell, text: str) -> None:
    """写单元格文本，保留首 run 格式（与通知/签到生成器同语义）。"""
    first = None
    for p in cell.paragraphs:
        for r in p.runs:
            if first is None:
                first = r
            r.text = ""
    if first is not None:
        first.text = str(text or "")
    elif cell.paragraphs:
        cell.paragraphs[0].add_run(str(text or ""))
