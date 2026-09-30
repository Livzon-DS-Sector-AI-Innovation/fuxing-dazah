"""三个解析器纯逻辑测试（此前零覆盖）。

覆盖：标准文档文本解析（文件头/数值结构化/表格块）、液相模板解析
（坐标/表号/批号）、旧解析器边界行为。
"""

import pytest

from app.modules.quality.standard_doc_parser import (
    _structure_numeric,
    parse_standard_doc,
)

# ── 标准文档：数值标准结构化 ──


def test_structure_le():
    assert _structure_numeric("≤3.0%") == ("≤", None, 3.0)


def test_structure_pharmacopeia_text_operators():
    # 药典式文字限度（「不得过/不得少于」等）结构化
    assert _structure_numeric("不得过3.0%") == ("≤", None, 3.0)
    assert _structure_numeric("不得少于91.0%") == ("≥", 91.0, None)
    assert _structure_numeric("应不低于95%") == ("≥", 95.0, None)
    assert _structure_numeric("不得大于0.5%") == ("<", None, 0.5)


def test_structure_ge():
    assert _structure_numeric("≥91.0%") == ("≥", 91.0, None)


def test_structure_range_fullwidth():
    assert _structure_numeric("2.5～4.5") == ("范围", 2.5, 4.5)


def test_structure_range_tilde():
    assert _structure_numeric("3.5~4.5") == ("范围", 3.5, 4.5)


def test_structure_lt_gt():
    assert _structure_numeric("＜0.25IU/mg") == ("<", None, 0.25)
    assert _structure_numeric(">95%") == (">", 95.0, None)


def test_structure_plain_text_not_numeric():
    # 文字标准不带运算符 → 不结构化（人工判定）
    assert _structure_numeric("应为白色粉末") == (None, None, None)


def test_structure_number_without_operator_ignored():
    # 附带数字但无运算符（如「乙醇（96%）」）不当作限度
    assert _structure_numeric("乙醇（96%）") == (None, None, None)


def test_structure_operator_without_number():
    assert _structure_numeric("≤") == (None, None, None)


# ── 标准文档：全文解析 ──


def _sample_text() -> str:
    return "\n".join([
        "产品名称：盐酸万古霉素",
        "产品代号：HAF",
        "文件编号：SOP.02.3205.010",
        "有效期：36个月",
        "",
        "质量标准：",
        "1",
        "水分",
        "不得过3.0%",
        "SOP.03.1111",
        "2",
        "性状",
        "应为白色粉末",
        "SOP.03.2222",
        "备注：",
    ])


def test_parse_header_fields():
    doc = parse_standard_doc(_sample_text())
    assert doc.product_name == "盐酸万古霉素"
    assert doc.product_code == "HAF"
    assert doc.file_no == "SOP.02.3205.010"
    assert doc.valid_years == "36个月"


def test_parse_items_with_sop_anchors():
    doc = parse_standard_doc(_sample_text())
    items = {it.item_name: it for it in doc.items}
    assert set(items) == {"水分", "性状"}
    assert items["水分"].sop_no == "SOP.03.1111"
    assert items["水分"].operator == "≤" and items["水分"].limit_max == 3.0
    assert items["性状"].operator is None  # 文字标准保留人工判定


def test_parse_empty_text_returns_empty_doc():
    doc = parse_standard_doc("")
    assert not doc.product_name and not doc.items


# ── 液相模板解析：纯函数 ──


def test_lc_col_letter():
    from app.modules.quality.lc_template_parser import _col_letter

    assert _col_letter(1) == "A"
    assert _col_letter(26) == "Z"
    assert _col_letter(27) == "AA"
    assert _col_letter(28) == "AB"


def test_lc_cell_coord():
    from app.modules.quality.lc_template_parser import _cell_coord

    # 1-indexed，(行, 列)
    assert _cell_coord("A1") == (1, 1)
    assert _cell_coord("M22") == (22, 13)
    assert _cell_coord("AA10") == (10, 27)


def test_lc_parse_value():
    from app.modules.quality.lc_template_parser import _parse_value

    assert _parse_value(0.956) == pytest.approx(0.956)
    assert _parse_value("0.956") == pytest.approx(0.956)
    assert _parse_value("95.6%") == pytest.approx(95.6)
    assert _parse_value("N/A") is None
    assert _parse_value("未检出") is None
    assert _parse_value(None) is None


def test_lc_detect_table_no_from_sheet():
    import io

    import openpyxl

    from app.modules.quality.lc_template_parser import detect_table_no, open_sheet

    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "检验记录"
    ws["A2"] = "EX-HA-5246-001"
    buf = io.BytesIO()
    wb.save(buf)
    get, max_row, max_col = open_sheet(buf.getvalue(), "t.xlsx")
    assert detect_table_no(get, max_row, max_col) == "EX-HA-5246-001"


def test_lc_find_batch():
    import io

    import openpyxl

    from app.modules.quality.lc_template_parser import find_batch, open_sheet

    wb = openpyxl.Workbook()
    ws = wb.active
    ws["B3"] = "批号"
    ws["C3"] = "HAF2608001B"
    buf = io.BytesIO()
    wb.save(buf)
    get, max_row, max_col = open_sheet(buf.getvalue(), "t.xlsx")
    assert find_batch(get, max_row, max_col) == "HAF2608001B"


# ── 旧解析器边界行为 ──


def test_parse_lc_excel_rejects_garbage():
    from app.modules.quality.excel_parser import parse_lc_excel

    with pytest.raises(Exception):
        parse_lc_excel(b"not an excel file", "bad.xlsx")
