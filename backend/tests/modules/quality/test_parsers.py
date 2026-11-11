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


def test_structure_le() -> None:
    assert _structure_numeric("≤3.0%") == ("≤", None, 3.0)


def test_structure_pharmacopeia_text_operators() -> None:
    # 药典式文字限度（「不得过/不得少于」等）结构化
    assert _structure_numeric("不得过3.0%") == ("≤", None, 3.0)
    assert _structure_numeric("不得少于91.0%") == ("≥", 91.0, None)
    assert _structure_numeric("应不低于95%") == ("≥", 95.0, None)
    assert _structure_numeric("不得大于0.5%") == ("<", None, 0.5)


def test_structure_ge() -> None:
    assert _structure_numeric("≥91.0%") == ("≥", 91.0, None)


def test_structure_range_fullwidth() -> None:
    assert _structure_numeric("2.5～4.5") == ("范围", 2.5, 4.5)


def test_structure_range_tilde() -> None:
    assert _structure_numeric("3.5~4.5") == ("范围", 3.5, 4.5)


def test_structure_lt_gt() -> None:
    assert _structure_numeric("＜0.25IU/mg") == ("<", None, 0.25)
    assert _structure_numeric(">95%") == (">", 95.0, None)


def test_structure_plain_text_not_numeric() -> None:
    # 文字标准不带运算符 → 不结构化（人工判定）
    assert _structure_numeric("应为白色粉末") == (None, None, None)


def test_structure_number_without_operator_ignored() -> None:
    # 附带数字但无运算符（如「乙醇（96%）」）不当作限度
    assert _structure_numeric("乙醇（96%）") == (None, None, None)


def test_structure_operator_without_number() -> None:
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


def test_parse_header_fields() -> None:
    doc = parse_standard_doc(_sample_text())
    assert doc.product_name == "盐酸万古霉素"
    assert doc.product_code == "HAF"
    assert doc.file_no == "SOP.02.3205.010"
    assert doc.valid_years == "36个月"


def test_parse_items_with_sop_anchors() -> None:
    doc = parse_standard_doc(_sample_text())
    items = {it.item_name: it for it in doc.items}
    assert set(items) == {"水分", "性状"}
    assert items["水分"].sop_no == "SOP.03.1111"
    assert items["水分"].operator == "≤" and items["水分"].limit_max == 3.0
    assert items["性状"].operator is None  # 文字标准保留人工判定


def test_parse_empty_text_returns_empty_doc() -> None:
    doc = parse_standard_doc("")
    assert not doc.product_name and not doc.items


# ── 液相模板解析：纯函数 ──


def test_lc_col_letter() -> None:
    from app.modules.quality.lc_template_parser import _col_letter

    assert _col_letter(1) == "A"
    assert _col_letter(26) == "Z"
    assert _col_letter(27) == "AA"
    assert _col_letter(28) == "AB"


def test_lc_cell_coord() -> None:
    from app.modules.quality.lc_template_parser import _cell_coord

    # 1-indexed，(行, 列)
    assert _cell_coord("A1") == (1, 1)
    assert _cell_coord("M22") == (22, 13)
    assert _cell_coord("AA10") == (10, 27)


def test_lc_parse_value() -> None:
    from app.modules.quality.lc_template_parser import _parse_value

    assert _parse_value(0.956) == pytest.approx(0.956)
    assert _parse_value("0.956") == pytest.approx(0.956)
    assert _parse_value("95.6%") == pytest.approx(95.6)
    assert _parse_value("N/A") is None
    assert _parse_value("未检出") is None
    assert _parse_value(None) is None


def test_lc_detect_table_no_from_sheet() -> None:
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


def test_lc_find_batch() -> None:
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


def test_parse_lc_excel_rejects_garbage() -> None:
    from app.modules.quality.excel_parser import parse_lc_excel

    with pytest.raises(Exception):
        parse_lc_excel(b"not an excel file", "bad.xlsx")


def test_detect_standard_type_variants() -> None:
    """标题识别药典标准类型：EP/CP 回退 USR 万古霉素版式解析，但标准类型需正确落库。"""
    from app.modules.quality.excel_parser import detect_standard_type

    assert detect_standard_type("盐酸万古霉素USP含量与有关物质计算表") == "USP"
    assert detect_standard_type("盐酸万古霉素EP含量与有关物质计算表") == "EP"
    assert detect_standard_type("盐酸万古霉素Ph.Eur含量与有关物质计算表") == "EP"
    assert detect_standard_type("盐酸万古霉素（欧洲药典）计算表") == "EP"
    assert detect_standard_type("盐酸万古霉素CP含量与有关物质计算表") == "CP"
    assert detect_standard_type("盐酸万古霉素中国药典计算表") == "CP"
    # 无法识别 → 空串（列表/汇总显示 '-'）
    assert detect_standard_type("某产品含量与有关物质计算表") == ""


def test_usr_parser_title_fields_ep_cp() -> None:
    """EP/CP 标题的产品名截取：不再把 EP/CP 记录落成空标准。"""
    from app.modules.quality.excel_parser import _UsrVancomycinParser

    p = _UsrVancomycinParser()
    assert p._extract_product_name("盐酸万古霉素EP含量与有关物质计算表") == "盐酸万古霉素"
    assert p._extract_product_name("盐酸万古霉素CP含量与有关物质计算表") == "盐酸万古霉素"
    assert p._extract_product_name("盐酸万古霉素USP含量与有关物质计算表") == "盐酸万古霉素"


def test_extract_peak_table_from_markdown() -> None:
    """图谱 Markdown 峰表提取：面积列优先、两位小数、非数据行跳过。"""
    from app.modules.quality.service.chromatogram import extract_peak_table

    md = """# 图谱报告

| 峰名 | 保留时间(min) | 面积 | %面积 |
| --- | --- | --- | --- |
| 万古霉素B | 12.345 | 1234567.891 | 98.52 |
| 单去氯万古霉素 | 14.2 | 18888.5 | 1.48 |
| 未知1 | 3.1 | 99.999 | 0.01 |
"""
    peaks = extract_peak_table(md)
    assert [p["name"] for p in peaks] == ["万古霉素B", "单去氯万古霉素", "未知1"]
    assert [p["area"] for p in peaks] == [1234567.89, 18888.5, 100.0]
    # 无表格时返回空
    assert extract_peak_table("纯文本没有表格") == []


def test_extract_peak_table_rt_and_raw_area_priority() -> None:
    """峰表提取增强：保留时间列可选提取；面积优先原始面积列（避开仪器 %面积口径）。"""
    from app.modules.quality.service.chromatogram import extract_peak_table

    md = """# 图谱报告

| 峰名 | 保留时间(min) | 面积 | %面积 |
| --- | --- | --- | --- |
| 万古霉素B | 12.345 | 1234567.891 | 98.52 |
| 单去氯万古霉素 | 14.2 | 18888.5 | 1.48 |
"""
    peaks = extract_peak_table(md)
    # 取原始面积列（1234567.89），不是 %面积列（98.52）——引擎需原始面积自行归一化
    assert peaks[0]["area"] == 1234567.89
    assert peaks[1]["area"] == 18888.5
    assert peaks[0]["rt"] == 12.345
    assert peaks[1]["rt"] == 14.2

    # 只有 %面积列：回退取 % 列（既有行为）；无保留时间列 → rt None
    md2 = """| 组分 | %面积 |
| --- | --- |
| 杂质F | 0.32 |
"""
    peaks2 = extract_peak_table(md2)
    assert peaks2[0]["area"] == 0.32
    assert peaks2[0]["rt"] is None


def test_match_task_row_by_sop_pattern() -> None:
    """表号数字段 ↔ 项目行 sop_no 自动关联：EX-HA-5246-002 优先匹配 SOP.03.5246 行池。"""
    from app.modules.quality.models import QualityTestResult
    from app.modules.quality.service.task_core import _TaskCore

    rows = [
        QualityTestResult(item_name="万古霉素B", sop_no="SOP.03.5246", judge_mode="auto"),
        QualityTestResult(item_name="单去氯万古霉素", sop_no="SOP.03.5230", judge_mode="auto"),
    ]
    # 无 pattern：全量名匹配
    hit = _TaskCore._match_task_row(rows, "万古霉素B", None, None)
    assert hit is not None and hit.item_name == "万古霉素B"
    # 带 pattern：限定 SOP.03.5246 池（无该池行时回落全量）
    hit2 = _TaskCore._match_task_row(rows, "万古霉素B", None, None, "5246")
    assert hit2 is not None and hit2.item_name == "万古霉素B"
    # pattern 不含目标行：池空 → 回落全量仍可匹配
    hit3 = _TaskCore._match_task_row(rows, "单去氯万古霉素", None, None, "9999")
    assert hit3 is not None and hit3.item_name == "单去氯万古霉素"


def test_any_unknown_rule_max_of_others() -> None:
    """任何未知杂质 = 排除清单外其余组分（含字段自身）的最大值。"""
    from app.modules.quality.service.task_parse import _TaskParse

    rule = {"exclude": ["万古霉素B", "杂质A", "杂质B", "杂质C", "杂质D", "总杂质"]}
    candidates = [
        ("Vancomycin B％", 95.6), ("杂质RS1％", 0.21), ("杂质RS2％", 0.27),
        ("杂质RS3％", 0.59), ("杂质A％", 0.62), ("杂质B1％", 0.31), ("杂质C％", 0.079),
        ("总杂质％", 4.4), ("任何未知杂质％", 0.29),
    ]
    out = _TaskParse._apply_any_unknown_rule(candidates, rule)
    by_name = {n: v for n, v in out}
    assert by_name["任何未知杂质"] == 0.59
    # 排除项原样保留
    assert by_name["杂质A％"] == 0.62 and by_name["总杂质％"] == 4.4
    # 空池（全被排除）时原样返回
    only_excluded = [("杂质A％", 1.0), ("总杂质％", 2.0)]
    assert _TaskParse._apply_any_unknown_rule(only_excluded, rule) == only_excluded
