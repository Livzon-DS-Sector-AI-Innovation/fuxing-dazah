"""COA 模板编址与写入：地址稳定、按网格列编号、跨 run 原位替换。

用 python-docx 现搭小模板：真实 COA 的关键形态都在——项目名跨列、大类格跨行、
值被拆成多个 run、值两侧带排版空白、页眉页脚。
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

import pytest
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

from app.modules.qa.service.coa.template_address import (
    SlotMismatchError,
    TemplateDoc,
    TemplateDocError,
    display_text,
    flat_text,
    guess_inline_value,
    locate,
)


def _bytes(doc: Any) -> bytes:
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _fill(cell: Any, *lines: str) -> None:
    cell.text = lines[0]
    for line in lines[1:]:
        cell.add_paragraph(line)


def _items_table(doc: Any) -> Any:
    """项目表：表头 项目(跨2列)|标准|结果；行内格子数刻意不一致。"""
    table = doc.add_table(rows=4, cols=4)
    head = table.rows[0].cells
    _fill(head[0].merge(head[1]), "项目", "Tests")
    _fill(head[2], "标准", "Specifications")
    _fill(head[3], "结果", "Results")
    plain = table.rows[1].cells  # 项目名跨两列：3 个格子
    _fill(plain[0].merge(plain[1]), "外观", "Appearance")
    _fill(plain[2], "白色粉末")
    grouped = table.rows[2].cells  # 大类 | 项目 | 标准 | 结果：4 个格子
    _fill(grouped[0], "有关物质", "Related substances")
    _fill(grouped[1], "杂质A", "Impurity A")
    _fill(grouped[2], "≤3.0%")
    _fill(grouped[3], "0.25%")
    last = table.rows[3].cells
    last[0].merge(grouped[0])  # 大类格跨行：续行自己没有文字
    _fill(last[1], "杂质C", "Impurity C")
    _fill(last[2], "≤1.0%")
    return table


class TestAddressing:
    def test_result_column_keeps_one_id_across_uneven_rows(self) -> None:
        """按网格列编号：项目名跨两列的行和多一格的行，结果列都是 G3。"""
        doc = Document()
        _items_table(doc)
        view = TemplateDoc(_bytes(doc))
        assert [s for s in view.by_id if s.endswith("G3.p0")] == [
            "T0.R0.G3.p0",
            "T0.R1.G3.p0",
            "T0.R2.G3.p0",
            "T0.R3.G3.p0",
        ]
        assert view.result_columns() == {"T0": 3}
        assert view.by_id["T0.R1.G0.p0"].span == 2

    def test_addressed_text_is_the_model_facing_format(self) -> None:
        doc = Document()
        doc.add_paragraph("CERTIFICATE OF ANALYSIS   XXXXXXXX")
        _items_table(doc)
        text = TemplateDoc(_bytes(doc)).addressed()
        assert text.startswith("【正文】\n[P0] CERTIFICATE OF ANALYSIS   XXXXXXXX\n表格 T0（4 行）：")
        assert "[T0.R0.G0.p0]〖跨2列〗项目 ⏎ [T0.R0.G0.p1]〖跨2列〗Tests" in text
        assert "[T0.R3.G0.p0]〖同上〗(空)" in text
        assert "[T0.R2.G3.p0]0.25%" in text

    def test_header_footer_and_textbox_are_addressed(self) -> None:
        doc = Document()
        doc.add_paragraph("正文")
        doc.sections[0].header.paragraphs[0].text = "丽珠集团福州福兴医药有限公司"
        doc.sections[0].footer.paragraphs[0].text = "Page 1"
        view = TemplateDoc(_bytes(doc))
        assert [view.by_id[s].text for s in ("P0", "H.P0", "F.P0")] == [
            "正文",
            "丽珠集团福州福兴医药有限公司",
            "Page 1",
        ]
        assert "【页眉】\n[H.P0]" in view.addressed()

    def test_resolve_tolerates_paragraph_suffix(self) -> None:
        doc = Document()
        doc.add_paragraph("正文")
        _items_table(doc)
        view = TemplateDoc(_bytes(doc))
        cell = view.resolve("T0.R2.G3")  # 格子地址缺段号
        body = view.resolve("P0.p0")  # 正文段落多写了段号
        assert cell is not None and cell.sid == "T0.R2.G3.p0"
        assert body is not None and body.sid == "P0"
        assert view.resolve("T0.R9.G9.p0") is None

    def test_row_context_carries_merged_group_label(self) -> None:
        """续行的大类格是空的，上下文要带上合并起点那一行的大类名。"""
        doc = Document()
        _items_table(doc)
        view = TemplateDoc(_bytes(doc))
        context = view.row_context(view.by_id["T0.R3.G3.p0"], exclude_cell="T0.R3.G3")
        assert "有关物质" in context and "杂质C" in context
        assert "0.25%" not in context  # 别的行的值不串进来

    def test_grid_carries_real_column_widths(self) -> None:
        """预览按真实比例画列：每张表带网格列宽（缇），个数与网格列数一致。"""
        doc = Document()
        _items_table(doc)
        (table,) = [b for b in TemplateDoc(_bytes(doc)).grid()[0]["blocks"] if b["type"] == "table"]
        assert len(table["col_widths"]) == table["ncols"] == 4
        assert all(width > 0 for width in table["col_widths"])

    def test_grid_without_column_widths_is_marked_unknown(self) -> None:
        """文件里没写列宽（或写成 0）：不输出 col_widths，前端退回自动列宽。"""
        doc = Document()
        table = _items_table(doc)
        for col in table._tbl.find(qn("w:tblGrid")).findall(qn("w:gridCol")):
            col.set(qn("w:w"), "0")
        (block,) = [b for b in TemplateDoc(_bytes(doc)).grid()[0]["blocks"] if b["type"] == "table"]
        assert "col_widths" not in block

    def test_grid_carries_paragraph_alignment(self) -> None:
        """结果列的值在模板里是居中的：预览照原样排，左对齐/没写的段落在数据里不带 align。"""
        doc = Document()
        table = _items_table(doc)
        table.rows[2].cells[3].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        table.rows[2].cells[1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.LEFT
        (block,) = [b for b in TemplateDoc(_bytes(doc)).grid()[0]["blocks"] if b["type"] == "table"]
        cells = block["rows"][2]["cells"]
        assert cells[3]["paras"][0]["align"] == "center"
        assert "align" not in cells[1]["paras"][0]  # 左对齐就是默认，不带
        assert "align" not in cells[2]["paras"][0]  # 没写对齐

    def test_not_a_docx_is_rejected_with_one_message(self) -> None:
        with pytest.raises(TemplateDocError, match="无法读取"):
            TemplateDoc(b"PK\x03\x04 not really a package")


class TestTextTools:
    def test_locate_ignores_whitespace_and_excludes_padding(self) -> None:
        assert locate("\u2002\u2002SYN0001\u2002\u2002\u2002", "SYN0001") == "SYN0001"
        assert locate("符合规定Conform", "符合规定 Conform") == "符合规定Conform"
        assert locate("HAF2607001A", "HAF2607002A") is None

    def test_guess_inline_value_only_when_embedded(self) -> None:
        title = "CERTIFICATE OF ANALYSIS                  XXXXXXXX   "
        assert guess_inline_value(title) == "XXXXXXXX"
        assert guess_inline_value("CERTIFICATE OF ANALYSIS   26081215") == "26081215"
        assert guess_inline_value("XXXXXXXX") is None  # 整段就是值


class TestWriting:
    def _view(self) -> TemplateDoc:
        doc = Document()
        title = doc.add_paragraph()
        title.add_run("CERTIFICATE OF ANALYSIS   ")
        title.add_run("XXXX")
        title.add_run("XXXX")
        table = _items_table(doc)
        # 值两侧的排版空白、值内部换行：真实模板里都有
        padded = table.rows[1].cells[3].paragraphs[0]
        padded.add_run("\u2002\u2002")
        padded.add_run("SYN")
        padded.add_run("0001")
        padded.add_run("\u2002\u2002\u2002")
        return TemplateDoc(_bytes(doc))

    def test_inplace_across_runs_keeps_static_text(self) -> None:
        view = self._view()
        view.write("P0", "inplace", "XXXXXXXX", "26112401")
        assert view.by_id["P0"].text.startswith("CERTIFICATE OF ANALYSIS   26112401")
        assert "XXXX" not in view.by_id["P0"].text

    def test_inplace_preserves_padding_around_value(self) -> None:
        view = self._view()
        view.write("T0.R1.G3.p0", "inplace", "SYN0001", "SYN0002")
        assert display_text(view.by_id["T0.R1.G3.p0"].element) == (
            "\u2002\u2002SYN0002\u2002\u2002\u2002"
        )

    def test_replace_writes_into_empty_slot_and_keeps_padding_of_old(self) -> None:
        view = self._view()
        view.write("T0.R3.G3.p0", "replace", "", "0.10%")  # 模板没填值的空格
        assert flat_text(view.by_id["T0.R3.G3.p0"].element) == "0.10%"
        view.write("T0.R2.G3.p0", "replace", "0.25%", "0.30%")
        assert flat_text(view.by_id["T0.R2.G3.p0"].element) == "0.30%"
        view.write("T0.R1.G3.p0", "replace", "\u2002\u2002SYN0001\u2002\u2002\u2002", "SYN0009")
        assert display_text(view.by_id["T0.R1.G3.p0"].element) == (
            "\u2002\u2002SYN0009\u2002\u2002\u2002"
        )

    def test_newline_becomes_word_break_and_old_breaks_are_replaced(self) -> None:
        doc = Document()
        para = doc.add_table(rows=1, cols=1).rows[0].cells[0].paragraphs[0]
        para.add_run("符合规定")
        para.add_run().add_break()
        para.add_run("Conform")
        view = TemplateDoc(_bytes(doc))
        assert view.by_id["T0.R0.G0.p0"].text == "符合规定\nConform"
        view.write("T0.R0.G0.p0", "replace", "符合规定Conform", "未检出\nNot detected")
        assert view.by_id["T0.R0.G0.p0"].text == "未检出\nNot detected"
        reopened = TemplateDoc(view.bytes())
        assert reopened.by_id["T0.R0.G0.p0"].text == "未检出\nNot detected"

    def test_writing_back_every_slot_changes_nothing(self) -> None:
        view = self._view()
        before = view.snapshot()
        for sid, text in before.items():
            if view.by_id[sid].in_table:
                view.write(sid, "replace", text, text.strip() or text)
            elif text.strip():
                value = guess_inline_value(text) or text.strip()
                view.write(sid, "inplace", locate(text, value) or text, value)
        assert view.snapshot() == before

    def test_unknown_slot_is_an_error(self) -> None:
        with pytest.raises(SlotMismatchError, match="不存在"):
            self._view().write("T9.R9.G9.p0", "replace", "", "x")
