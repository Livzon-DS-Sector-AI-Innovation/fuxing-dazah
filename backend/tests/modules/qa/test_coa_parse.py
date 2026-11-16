"""COA docx 解析器：真实样本全量断言。

样本为丽珠盐酸万古霉素 COA（HAF2607025A_3205.docx，30 个检测项目），
覆盖：批次信息收割、右上角流水号/报告编号（run 碎片化）、vMerge 大类继承、
表头分组≠数据行分组的右锚定、全角限值解析、双语拆分。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.modules.qa.service.coa.docx_parse import (
    item_code,
    parse_docx,
    parse_number,
    parse_spec,
    split_bilingual,
)

FIXTURE = Path(__file__).parent / "fixtures" / "coa_haf_sample.docx"


@pytest.fixture(scope="module")
def parsed() -> dict:
    return parse_docx(FIXTURE.read_bytes()).__dict__


@pytest.mark.anyio
class TestBatchInfo:
    """表1 基础信息 + 编号区。"""

    async def test_batch_info(self, parsed):
        info = parsed["batch_info"]
        assert info["batch_no"] == "HAF2607025A"
        assert info["packaging"] == "5kg/Tin"
        assert info["batch_size"] == "41.120kg"
        assert "盐酸万古霉素" in info["product"]

    async def test_serial_and_report_no(self, parsed):
        # 流水号在 docx 中被拆成 26081|215 两个 run，段落级拼接才拿得到
        assert parsed["serial_no"] == "26081215"
        assert parsed["report_no"] == "COA-HAF-3205-006"

    async def test_dates_parsed(self, parsed):
        assert parsed["mfg_date"] == date(2026, 7, 29)
        assert parsed["exp_date"] == date(2028, 7, 28)

    async def test_product_bilingual(self, parsed):
        assert parsed["product_cn"] == "盐酸万古霉素"
        assert parsed["product_en"] == "Vancomycin Hydrochloride"

    async def test_code_suggestions(self, parsed):
        assert parsed["suggested_product_code"] == "HAF"
        assert parsed["suggested_standard_code"] == "3205"


@pytest.mark.anyio
class TestItems:
    """表2 检测项目：右锚定 + vMerge 继承。"""

    async def test_item_count(self, parsed):
        assert len(parsed["items"]) == 30

    async def test_conclusion(self, parsed):
        assert "本品符合美国药典及企业内控标准" in (parsed["conclusion"] or "")

    async def test_vmerge_prefix_ignored(self, parsed):
        items = {it.name: it for it in parsed["items"]}
        # 万古霉素组分段 14 行共享同一 vMerge 大类列——不提取；子项目名
        # 物理格落在表头「标准」列区间，右锚定不得错位
        assert items["万古霉素B"].spec_text == "≥93.0%"
        assert items["万古霉素B"].result == "95.5%"
        assert items["万古霉素B"].spec_min == 93.0
        assert items["总杂质"].spec_max == 7.0

    async def test_cross_boundary_item(self, parsed):
        items = {it.name: it for it in parsed["items"]}
        # 吸光度行项目名横跨表头「标准」组第一列，spec 不得被项目名污染
        a450 = items["吸光度(450nm)"]
        assert a450.spec_text == "≤0.10"
        assert a450.spec_max == 0.10
        assert a450.result == "0.005"
        assert a450.value_num == 0.005
        assert a450.value_type == "number"

    async def test_numeric_and_text_values(self, parsed):
        items = {it.name: it for it in parsed["items"]}
        assert items["pH"].spec_min == 2.5 and items["pH"].spec_max == 4.5
        assert items["pH"].value_num == 2.85
        # 半定量（全角＜）与判定词走文字列
        endo = items["细菌内毒素"]
        assert endo.spec_text == "＜0.25EU/mg"
        assert endo.spec_max == 0.25
        assert endo.value_num is None
        assert endo.result == "符合规定Conform"
        assert endo.value_type == "number"  # 标准限可结构化 → 数值列
        micro = items["需氧菌总数"]
        assert micro.result == "＜1cfu/g" and micro.value_num is None
        assay = items["含 量(以无水物计)"]
        assert assay.value_num == 1091.0

    async def test_qualitative_item(self, parsed):
        items = {it.name: it for it in parsed["items"]}
        appearance = items["外观"]  # 中英同行也拆分
        assert appearance.name_en == "Appearance"
        assert not hasattr(appearance, "group")  # 大类已不提取
        assert appearance.value_type == "text"
        assert appearance.result == "符合规定Conform"

    async def test_inline_names_split(self, parsed):
        items = {it.name: it for it in parsed["items"]}
        # 中文名自身含拉丁片段：拆分锚点须跳过 B / B(B1+B2) / N-
        assert items["万古霉素B"].name_en == "Vancomycin B"
        assert items["杂质B(B1+B2)"].name_en == "Impurity B(Impurity B1+Impurity B2)"
        assert items["N-亚硝基-万古霉素"].name_en == "N-nitroso-vancomycin"
        assert items["RS1"].name_en is None      # 纯代号不拆
        assert items["红外IR"].name_en is None   # 全大写缩写不是译名起点


@pytest.mark.anyio
class TestHelpers:
    """归一化/匹配键的确定性。"""

    async def test_item_code_stable_across_layouts(self):
        # 同一项目：中英分行 vs 同行，两种排版必须得到同一匹配键
        a = item_code(*split_bilingual("溶解度\nSolubility"))
        b = item_code("溶解度Solubility", None)
        assert a == b == "溶解度solubility"

    async def test_split_bilingual_inline(self):
        assert split_bilingual("外观Appearance") == ("外观", "Appearance")
        assert split_bilingual("万古霉素B Vancomycin B") == ("万古霉素B", "Vancomycin B")
        assert split_bilingual("任何未知杂质 Any unknown impurity") == (
            "任何未知杂质", "Any unknown impurity")
        assert split_bilingual("RS1") == ("RS1", None)
        assert split_bilingual("溶解度\nSolubility") == ("溶解度", "Solubility")

    async def test_parse_number_fullwidth(self):
        assert parse_number("95.5%") == 95.5
        assert parse_number("1091µg/mg") == 1091.0
        assert parse_number("0.062ppm") == 0.062
        assert parse_number("＜1cfu/g") is None  # 半定量走文字
        assert parse_number("符合规定Conform") is None

    async def test_parse_spec_shapes(self):
        assert parse_spec("≤3.0%") == (None, 3.0)
        assert parse_spec("＜0.25EU/mg") == (None, 0.25)
        assert parse_spec("≥93.0%") == (93.0, None)
        assert parse_spec("2.5～4.5") == (2.5, 4.5)
        assert parse_spec("白色粉末") == (None, None)
        assert parse_spec("≤5000ppm") == (None, 5000.0)
