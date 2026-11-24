"""COA AI 解析：载荷装配 + 确定性复判 + 调用编排。

fixture 载荷（coa_ai_payload.json）来自真实 DeepSeek 提取（丽珠盐酸万古
霉素 COA，30 个检测项目，已按 3025A 样本口径校正），并故意保留一处模型
错误值（需氧菌总数结果 ＜1cfu/g 却给 value_num=1）——确定性复判必须
将其置空。调用编排整体打桩（``_ocr_recognize``/``_chat_extract`` 返回固定
结果），不依赖真实模型；纯函数工具保留确定性单测。
"""

from __future__ import annotations

import json
from datetime import date
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from docx import Document

from app.core.exceptions import AppException
from app.modules.qa.service.coa import ai_parse
from app.modules.qa.service.coa.ai_parse import (
    _build_parse,
    _fallback_report_no,
    parse_docx_ai,
)
from app.modules.qa.service.coa.docx_parse import (
    item_code,
    parse_number,
    parse_spec,
    split_bilingual,
    strip_result_affixes,
)

PAYLOAD = json.loads(
    (Path(__file__).parent / "fixtures" / "coa_ai_payload.json").read_text()
)

# 结构版载荷（模板导入）：标签清单+品名+项目定义，无任何值类字段
STRUCTURE_PAYLOAD: dict[str, object] = {
    "report_no": "COA-DA-3310-006",
    "batch_info_fields": [
        {"label_cn": "品  名", "label_en": "Product Name"},
        {"label_cn": "批  号", "label_en": "Batch No."},
        {"label_cn": "生产日期", "label_en": "Mfg. Date"},
        {"label_cn": "复验期", "label_en": "Retest Date"},
        {"label_cn": "储存条件", "label_en": "Storage Conditions"},
        {"label_cn": None, "label_en": None},  # 空标签行：丢弃
        {"label_cn": "贸易项", "label_en": None},  # 无英文：中文 key
    ],
    "batch_info": {"product": "达托霉素 Daptomycin"},
    "items": [
        {
            "name_cn": "外观",
            "name_en": "Appearance",
            "unit": None,
            "spec_text": "黄色或淡黄色粉末。",
            "spec_text_en": "Yellow or yellowish powder.",
            "spec_min": None,
            "spec_max": None,
        },
        {
            "name_cn": "水分",
            "name_en": "Water",
            "unit": "%",
            "spec_text": "≤5.0%",
            "spec_text_en": "NMT 5.0%",
            "spec_min": None,
            "spec_max": 5.0,
        },
    ],
}


def _settings(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = dict(
        QA_AI_ENABLED=True,
        QA_AI_API_KEY="sk-test",
        QA_AI_BASE_URL="https://api.deepseek.com",
        QA_AI_MODEL="deepseek-flash",
        QA_AI_MAX_RETRIES=2,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestBuildParse:
    """AI 载荷 → 域模型：表头装配与逐字段确定性复判。"""

    def _parse(self):
        return _build_parse(PAYLOAD)

    def test_batch_info_and_codes(self):
        parse = self._parse()
        info = parse.batch_info
        assert info["batch_no"] == "HAF2607025A"
        assert info["batch_size"] == "41.120kg"
        assert "盐酸万古霉素" in info["product"]
        assert parse.serial_no == "26081215"
        assert parse.report_no == "COA-HAF-3205-006"
        assert parse.suggested_product_code == "HAF"
        assert parse.suggested_standard_code == "HAF-3205-006"

    def test_structure_mode_assembly(self):
        """结构版载荷：batch_fields 装配（key/type 系统生成），值字段全空。"""
        parse = _build_parse(STRUCTURE_PAYLOAD)
        assert parse.report_no == "COA-DA-3310-006"
        assert parse.serial_no is None
        fields = {f.key: f for f in parse.batch_fields}
        assert set(fields) == {
            "product_name",
            "batch_no",
            "mfg_date",
            "retest_date",
            "storage_conditions",
            "贸易项",  # 无英文标签：中文原样作 key
        }
        assert fields["retest_date"].label_cn == "复验期"
        assert fields["retest_date"].field_type == "date"
        assert fields["mfg_date"].field_type == "date"
        assert fields["storage_conditions"].field_type == "text"
        # items 照常装配（项目定义）；结构版无结果值
        assert [it.name_cn for it in parse.items] == ["外观", "水分"]
        assert parse.items[1].spec_max == 5.0
        assert parse.items[1].result is None

    def test_values_payload_has_no_batch_fields(self):
        """值版载荷（无 batch_info_fields 键）→ batch_fields 为空，值照常。"""
        parse = _build_parse(PAYLOAD)
        assert parse.batch_fields == []
        assert parse.items and parse.items[0].result is not None

    def test_values_mode_batch_fields_with_value(self):
        """值版载荷的 batch_info_fields 带 value（模板动态字段，如复验期）。"""
        payload = {
            "batch_info_fields": [
                {"label_cn": "复验期", "label_en": "Retest Date", "value": "2027-07-01"},
                {"label_cn": "贸易项", "label_en": None, "value": None},
            ],
            "items": [],
        }
        fields = _build_parse(payload).batch_fields
        assert fields[0].value == "2027-07-01"
        assert fields[1].value is None

    def test_batch_field_cn_fallback_for_en_only_label(self):
        """只有英文标签：label_cn 回退英文（非空约束），key 走英文归一。"""
        payload = {
            "batch_info_fields": [{"label_cn": None, "label_en": "Retest Date"}],
            "items": [],
        }
        fields = _build_parse(payload).batch_fields
        assert len(fields) == 1
        assert fields[0].label_cn == "Retest Date"
        assert fields[0].key == "retest_date"

    def test_dates_parsed(self):
        parse = self._parse()
        assert parse.mfg_date == date(2026, 7, 29)
        assert parse.exp_date == date(2028, 7, 28)

    def test_product_bilingual(self):
        parse = self._parse()
        assert parse.product_cn == "盐酸万古霉素"
        assert parse.product_en == "Vancomycin Hydrochloride"

    def test_item_count(self):
        parse = self._parse()
        assert len(parse.items) == 30

    def test_comparison_semantics_guarded(self):
        """结果含比较符（＜1cfu/g）时模型 value_num 一律作废——＜1 ≠ 1；
        结果列剥尾缀单位只留数值形态（＜1）。"""
        parse = self._parse()
        micro = {it.name: it for it in parse.items}["需氧菌总数"]
        assert micro.result == "＜1"
        assert micro.value_num is None
        assert micro.value_type == "number"  # 标准限 ≤100 可结构化 → 数值列
        assert micro.unit == "cfu/g"  # 单位剥到 item.unit，不随值走

    def test_result_affixes_stripped(self):
        """结果列剥修饰（确定性后处理）：尾缀单位与英文尾巴剥掉，
        描述性文本原样保留。"""
        parse = self._parse()
        items = {it.name: it for it in parse.items}
        assert items["单去氯万古霉素"].result == "1.7"  # 1.7%
        assert items["含量(以无水物计)"].result == "1091"  # 1091µg/mg
        assert items["残留溶剂(乙醇)"].result == "294"  # 294ppm
        assert items["需氧菌总数"].result == "＜1"  # ＜1cfu/g
        assert items["外观"].result == "符合规定"  # 纯文字不动

    def test_strip_result_affixes_edges(self):
        """剥离函数边界：剥后非数值形态一律保留原文。"""
        strip = strip_result_affixes
        assert strip(None) is None
        assert strip("＜1cfu/g") == "＜1"
        assert strip("符合规定 Conform") == "符合规定"  # 模型未分列时的英文尾巴
        assert strip("白色粉末") == "白色粉末"  # 描述无单位不动
        assert strip("USP trial") == "USP trial"  # 恰以单位字母结尾的非数值不动
        assert strip("1091µg/mg") == "1091"
        assert strip("2.5~4.5") == "2.5~4.5"  # 区间无单位不动

    def test_numeric_items(self):
        parse = self._parse()
        items = {it.name: it for it in parse.items}
        ph = items["pH"]
        assert ph.spec_min == 2.5 and ph.spec_max == 4.5
        assert ph.value_num == 2.85
        van_b = items["万古霉素B"]
        assert van_b.spec_text == "≥93.0%"
        assert van_b.spec_min == 93.0
        assert van_b.value_num == 95.5
        endo = items["细菌内毒素"]
        assert endo.spec_max == 0.25
        assert endo.value_num is None  # 判定词走文字

    def test_bilingual_split_fields(self):
        """中英分列：name/spec/result 只留中文，英文进 *_en 留底。"""
        parse = self._parse()
        items = {it.name: it for it in parse.items}
        appearance = items["外观"]
        assert appearance.name_en == "Appearance"
        assert appearance.spec_text == "白色或类白色粉末。"
        assert appearance.spec_en == "White or almost white powder."
        assert appearance.result == "符合规定"
        assert appearance.result_en == "Conform"
        assert appearance.value_type == "text"
        assert items["红外"].name_en == "IR"  # 全大写缩写也是译名
        assert items["RS1"].name_en is None  # 纯代号无译名

    def test_unit_extraction(self):
        """单位从标准/结果原文确定性剥取；文字型项目的模型单位一律丢弃。"""
        parse = self._parse()
        items = {it.name: it for it in parse.items}
        assert items["杂质A"].unit == "%"
        assert "g/mg" in (items["含量(以无水物计)"].unit or "")
        assert items["细菌内毒素"].unit == "EU/mg"
        assert items["需氧菌总数"].unit == "cfu/g"
        assert items["pH"].unit is None  # 无量纲区间
        assert items["外观"].unit is None  # 载荷里模型给了 "g"，文字型必须杀掉

    def test_unit_ai_fallback_for_number_items(self):
        """数值型项目确定性剥不出单位（如「应不得过0.5」）时，采信模型。"""
        payload = {
            "items": [
                {
                    "name_cn": "干燥失重",
                    "spec_text": "应不得过0.5",
                    "result": "0.3",
                    "value_num": 0.3,
                    "unit": "%",
                }
            ]
        }
        it = _build_parse(payload).items[0]
        assert it.value_type == "number"
        assert it.unit == "%"


@pytest.mark.anyio
class TestParseDocxAi:
    """调用编排：打桩上传/提取，覆盖重试与配置门禁。"""

    async def test_success(self):
        async def _ocr(client, filename, content):
            assert filename == "coa.docx" and content
            return "ocr-text-x"

        async def _extract(client, document_text, prompt):
            assert document_text == "ocr-text-x"
            return PAYLOAD

        with (
            patch.object(ai_parse, "get_settings", lambda: _settings()),
            patch.object(ai_parse, "_ocr_recognize", new=_ocr),
            patch.object(ai_parse, "_chat_extract", new=_extract),
        ):
            parse = await parse_docx_ai(b"docx-bytes")
        assert parse.serial_no == "26081215"
        assert len(parse.items) == 30

    async def test_retry_then_success(self):
        """提取失败按配置重试（MAX_RETRIES=2 → 3 次尝试），最终成功。"""
        calls = {"extract": 0, "ocr": 0}

        async def _ocr(client, filename, content):
            calls["ocr"] += 1
            return "ocr-text-x"

        async def _extract(client, document_text, prompt):
            calls["extract"] += 1
            if calls["extract"] == 1:
                raise RuntimeError("模型提取失败 HTTP 500: boom")
            return PAYLOAD

        with (
            patch.object(ai_parse, "get_settings", lambda: _settings()),
            patch.object(ai_parse, "_ocr_recognize", new=_ocr),
            patch.object(ai_parse, "_chat_extract", new=_extract),
        ):
            parse = await parse_docx_ai(b"docx-bytes")
        assert calls == {"extract": 2, "ocr": 1}  # OCR 只做一次，仅提取重试
        assert len(parse.items) == 30

    async def test_ocr_failure_returns_502_without_retry(self):
        """OCR 失败直接 502，不占提取重试额度（重跑同一份长文档没意义）。"""
        calls = {"ocr": 0}

        async def _ocr(client, filename, content):
            calls["ocr"] += 1
            raise RuntimeError("OCR 识别失败 HTTP 502")

        async def _extract(client, document_text, prompt):
            raise AssertionError("OCR 失败后不应再调用提取")

        with (
            patch.object(ai_parse, "get_settings", lambda: _settings()),
            patch.object(ai_parse, "_ocr_recognize", new=_ocr),
            patch.object(ai_parse, "_chat_extract", new=_extract),
        ):
            with pytest.raises(AppException) as ei:
                await parse_docx_ai(b"docx-bytes")
        assert ei.value.status_code == 502
        assert calls["ocr"] == 1

    async def test_exhausted_retries_returns_502(self):
        async def _ocr(client, filename, content):
            return "ocr-text-x"

        async def _extract(client, document_text, prompt):
            raise RuntimeError("模型输出被截断（finish_reason != stop）")

        with (
            patch.object(ai_parse, "get_settings", lambda: _settings()),
            patch.object(ai_parse, "_ocr_recognize", new=_ocr),
            patch.object(ai_parse, "_chat_extract", new=_extract),
        ):
            with pytest.raises(AppException) as ei:
                await parse_docx_ai(b"docx-bytes")
        assert ei.value.status_code == 502

    async def test_ai_not_configured_returns_503(self):
        with patch.object(ai_parse, "get_settings", lambda: _settings(QA_AI_ENABLED=False)):
            with pytest.raises(AppException) as ei:
                await parse_docx_ai(b"docx-bytes")
        assert ei.value.status_code == 503

    async def test_mode_selects_prompt(self):
        """mode 分流：structure 用结构 prompt（无值字段），values 用值版。"""
        seen: dict[str, str] = {}

        async def _ocr(client, filename, content):
            return "ocr-text-x"

        async def _extract(client, document_text, prompt):
            seen["prompt"] = prompt
            return STRUCTURE_PAYLOAD if "batch_info_fields" in prompt else PAYLOAD

        with (
            patch.object(ai_parse, "get_settings", lambda: _settings()),
            patch.object(ai_parse, "_ocr_recognize", new=_ocr),
            patch.object(ai_parse, "_chat_extract", new=_extract),
        ):
            await parse_docx_ai(b"docx-bytes", mode="structure")
        assert "batch_info_fields" in seen["prompt"]
        assert "value_num" not in seen["prompt"]
        assert '"value": "对应值原文"' not in seen["prompt"]  # 结构版不带值

        with (
            patch.object(ai_parse, "get_settings", lambda: _settings()),
            patch.object(ai_parse, "_ocr_recognize", new=_ocr),
            patch.object(ai_parse, "_chat_extract", new=_extract),
        ):
            await parse_docx_ai(b"docx-bytes", mode="values")
        assert "value_num" in seen["prompt"]
        assert '"value": "对应值原文"' in seen["prompt"]  # 值版按标签取值

    async def test_unknown_mode_rejected(self):
        with pytest.raises(ValueError, match="未知 COA 解析模式"):
            await parse_docx_ai(b"docx-bytes", mode="bogus")

    async def test_report_no_fallback_when_ai_misses(self):
        """AI 漏提 report_no 时兜底 No. 标签，并重跑产品码/模板码建议链。"""
        payload = {"batch_info": {"product": "达托霉素"}, "items": []}

        async def _ocr(client, filename, content):
            return "ocr-text-x"

        async def _extract(client, document_text, prompt):
            return payload

        with (
            patch.object(ai_parse, "get_settings", lambda: _settings()),
            patch.object(ai_parse, "_ocr_recognize", new=_ocr),
            patch.object(ai_parse, "_chat_extract", new=_extract),
        ):
            parse = await parse_docx_ai(_docx_bytes(["No.:COA-DA-3310-006"]))
        assert parse.report_no == "COA-DA-3310-006"
        assert parse.suggested_product_code == "DA"
        assert parse.suggested_standard_code == "DA-3310-006"


def _docx_bytes(
    paragraphs: list[str],
    batch_no: str | None = "HAF2607025A",
    batch_label: str = "批  号 / Batch No.",
) -> bytes:
    """构造含 No. 段落与批号表格的最小 docx。"""
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    if batch_no is not None:
        row = doc.add_table(rows=1, cols=2).rows[0]
        row.cells[0].text = batch_label
        row.cells[1].text = batch_no
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


class TestFallbackReportNo:
    """report_no 确定性兜底：No. 标签写法变体 + 批号引导词排除。"""

    def test_paragraph_no_with_dot_colon(self):
        """达托模板实测写法：独立段落 No.:COA-DA-3310-006。"""
        data = _docx_bytes(
            ["检验报告单", "CERTIFICATE OF ANALYSIS   XXXXXXXX", "No.:COA-DA-3310-006"]
        )
        assert _fallback_report_no(data) == "COA-DA-3310-006"

    def test_no_label_variants(self):
        for line, expect in [
            ("No.COA-HAF-3205-006", "COA-HAF-3205-006"),
            ("No：COA-HAF-3205-006", "COA-HAF-3205-006"),
            ("报告编号 No. COA-HAF-3205-006", "COA-HAF-3205-006"),
        ]:
            assert _fallback_report_no(_docx_bytes([line])) == expect

    def test_batch_and_lot_no_excluded(self):
        """批号引导词（Batch/Lot No.）不是报告编号。"""
        assert _fallback_report_no(_docx_bytes(["批号 / Lot No. 2607025"])) is None
        assert _fallback_report_no(_docx_bytes([], batch_label="批号 / Batch No.")) is None
        # 段落在前：段落里的 No. 优先于表格里的 Batch No.
        assert (
            _fallback_report_no(_docx_bytes(["No.:COA-DA-3310-006"]))
            == "COA-DA-3310-006"
        )

    def test_uppercase_batch_and_lot_excluded(self):
        """大写引导词（BATCH NO. / LOT NO.）同样排除，不能把批号当报告编号。"""
        assert (
            _fallback_report_no(_docx_bytes([], batch_label="批号 / BATCH NO.")) is None
        )
        assert _fallback_report_no(_docx_bytes(["LOT NO.: 2607025"])) is None

    def test_short_number_rejected(self):
        """过短命中（Page No. 1）丢弃，避免把杂项当编号。"""
        assert _fallback_report_no(_docx_bytes(["Page No. 1"])) is None

    def test_no_label_returns_none(self):
        assert _fallback_report_no(_docx_bytes(["检验报告单", "CERTIFICATE OF ANALYSIS"])) is None

    def test_garbage_bytes_returns_none(self):
        assert _fallback_report_no(b"not a docx") is None


class TestHelpers:
    """归一化/匹配键/数值语义的确定性。"""

    def test_item_code_stable_across_layouts(self):
        # 同一项目：中英分行 vs 同行，两种排版必须得到同一匹配键
        a = item_code(*split_bilingual("溶解度\nSolubility"))
        b = item_code("溶解度Solubility", None)
        assert a == b == "溶解度solubility"

    def test_split_bilingual_inline(self):
        assert split_bilingual("外观Appearance") == ("外观", "Appearance")
        assert split_bilingual("万古霉素B Vancomycin B") == ("万古霉素B", "Vancomycin B")
        assert split_bilingual("任何未知杂质 Any unknown impurity") == (
            "任何未知杂质", "Any unknown impurity")
        assert split_bilingual("RS1") == ("RS1", None)
        assert split_bilingual("溶解度\nSolubility") == ("溶解度", "Solubility")

    def test_parse_number_fullwidth(self):
        assert parse_number("95.5%") == 95.5
        assert parse_number("1091µg/mg") == 1091.0
        assert parse_number("0.062ppm") == 0.062
        assert parse_number("＜1cfu/g") is None  # 半定量走文字
        assert parse_number("符合规定Conform") is None

    def test_parse_spec_shapes(self):
        assert parse_spec("≤3.0%") == (None, 3.0)
        assert parse_spec("＜0.25EU/mg") == (None, 0.25)
        assert parse_spec("≥93.0%") == (93.0, None)
        assert parse_spec("2.5～4.5") == (2.5, 4.5)
        assert parse_spec("白色粉末") == (None, None)
        assert parse_spec("≤5000ppm") == (None, 5000.0)


class TestOcrEndpoint:
    """OCR URL 兼容 base 带/不带 /v1 两种配置口径。"""

    @pytest.mark.parametrize(
        ("base", "expected"),
        [
            ("https://api.deepseek.com", "/v1/tools/ocr"),
            ("https://api.deepseek.com/", "/v1/tools/ocr"),
            ("https://api.deepseek.com/v1", "/tools/ocr"),
            ("https://api.deepseek.com/v1/", "/tools/ocr"),
        ],
    )
    def test_ocr_path_single_v1_prefix(self, base: str, expected: str):
        assert ai_parse._ocr_path(base) == expected

    @pytest.mark.parametrize(
        "base",
        ["https://api.deepseek.com", "https://api.deepseek.com/v1"],
    )
    async def test_ocr_request_url(self, base: str):
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            return httpx.Response(200, json={"pages": [{"text": "ok"}]})

        async with httpx.AsyncClient(
            base_url=base, transport=httpx.MockTransport(handler)
        ) as client:
            text = await ai_parse._ocr_recognize(client, "coa.docx", b"x")
        assert text == "ok"
        assert seen["url"] == "https://api.deepseek.com/v1/tools/ocr"

    async def test_empty_ocr_text_rejected(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"pages": []})

        async with httpx.AsyncClient(
            base_url="https://api.deepseek.com",
            transport=httpx.MockTransport(handler),
        ) as client:
            with pytest.raises(RuntimeError, match="未识别到文本"):
                await ai_parse._ocr_recognize(client, "coa.docx", b"x")
