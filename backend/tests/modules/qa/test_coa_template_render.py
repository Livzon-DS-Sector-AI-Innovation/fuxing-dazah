"""COA 回填：格式规则、缺项拦截、旧值泄漏扫描、标注与模板一致性守卫。

用仿真模板直接驱动 ``_build``（不出网的纯函数路径），模型不参与。
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from app.core.exceptions import AppException
from app.modules.qa.models import CoaReport, CoaStandard
from app.modules.qa.service.coa import template_bind as bind
from app.modules.qa.service.coa import template_render as render
from app.modules.qa.service.coa.template_address import TemplateDoc, flat_text
from tests.modules.qa._coa_template_builder import build_template

SERIAL = bind.FieldDef("batch:serial_no", "batch", "流水号", "Serial No.")
BATCH_NO = bind.FieldDef("batch:batch_no", "batch", "批  号", "Batch No.")
MFG_DATE = bind.FieldDef("batch:mfg_date", "batch", "生产日期", "Mfg. Date", "date")
APPEARANCE = bind.FieldDef("item:appearance", "item", "外观", "Appearance", value_type="text")
WATER = bind.FieldDef("item:water", "item", "水分", "Water", unit="%", spec_text="≤5.0%")
IMPURITY_C = bind.FieldDef("item:impurity_c", "item", "杂质C-RRT约1.86", "Impurity C (RRT 1.86)", unit="%", spec_text="≤1.0%")
UNBOUND = bind.FieldDef("item:impurity_a", "item", "杂质A-RRT约0.76", "Impurity A (RRT 0.76)", unit="%", spec_text="≤3.0%")
FIELDS = {f.key: f for f in (SERIAL, BATCH_NO, MFG_DATE, APPEARANCE, WATER, IMPURITY_C, UNBOUND)}

VERDICT = {"kind": "text", "bilingual": True, "joiner": "", "suffix": ""}
PERCENT = {"kind": "number", "decimals": 2, "suffix": "%"}
DOT_DATE = {"kind": "date", "pattern": "%Y.%m.%d"}


def _data(filled: bool = True, leak: bool = False) -> bytes:
    return build_template(filled=filled, leak=leak)


def _binding(data: bytes, **required: bool) -> dict[str, Any]:
    """与仿真模板对得上的标注：样例取模板里当前的文字。"""
    doc = TemplateDoc(data)

    def text(sid: str) -> str:
        return flat_text(doc.by_id[sid].element)

    specs = {
        "batch:serial_no": ("P1", "inplace", "XXXXXXXX" if text("P1").endswith("XXXXXXXX") else "26081215", {"kind": "text"}),
        "batch:batch_no": ("T0.R0.G1.p0", "replace", text("T0.R0.G1.p0"), {"kind": "text"}),
        "batch:mfg_date": ("T0.R0.G3.p0", "replace", text("T0.R0.G3.p0"), DOT_DATE),
        "item:appearance": ("T1.R1.G3.p0", "replace", text("T1.R1.G3.p0"), VERDICT),
        "item:water": ("T1.R2.G3.p0", "replace", text("T1.R2.G3.p0"), PERCENT),
        "item:impurity_c": ("T1.R4.G3.p0", "replace", text("T1.R4.G3.p0"), PERCENT),
    }
    return {
        "version": 1,
        "template_sha256": hashlib.sha256(data).hexdigest(),
        "verdicts": {},
        "fields": [
            {
                "field": key,
                "required": required.get(key.split(":", 1)[1], True),
                "slots": [{"sid": sid, "mode": mode, "sample": sample, "fmt": fmt}],
            }
            for key, (sid, mode, sample, fmt) in specs.items()
        ],
        "static_slots": [],
    }


def _values(**overrides: str) -> dict[str, str]:
    values: dict[str, str] = {
        "batch:serial_no": "26112402",
        "batch:batch_no": "HAF2607002A",
        "batch:mfg_date": "2026-07-30",
        "item:appearance": "符合规定",
        "item:water": "1.5",
        "item:impurity_c": "0.06",
    }
    values.update(overrides)
    return {k: v for k, v in values.items() if v != ""}


def _context(
    data: bytes, values: dict[str, str], binding: dict[str, Any] | None = None
) -> render._Context:
    return render._Context(
        CoaStandard(code="3205-006"),
        CoaReport(batch_no="HAF2607002A"),
        TemplateDoc(data),
        binding or _binding(data),
        FIELDS,
        values,
    )


class TestFormatValue:
    def test_number_rounds_half_up_to_template_decimals(self) -> None:
        assert render.format_value({"kind": "number", "decimals": 2, "suffix": "%"}, "0.125", {}) == ("0.13%", False)
        assert render.format_value({"kind": "number", "decimals": 2, "suffix": "%"}, "4.5", {})[0] == "4.50%"
        assert render.format_value({"kind": "number", "decimals": 0, "suffix": "IU/mg"}, "1099.5", {})[0] == "1100IU/mg"
        assert render.format_value({"kind": "number", "decimals": 3}, "0.5", {})[0] == "0.500"

    def test_non_numeric_value_under_number_rule_keeps_comparator_and_unit(self) -> None:
        """数值型项目登记成了文字（＜1、未检出）：按文字出并补单位；比较符不转全角。"""
        fmt = {"kind": "number", "decimals": 2, "suffix": "cfu/g"}
        assert render.format_value(fmt, "<1", {}) == ("<1cfu/g", False)
        assert render.format_value(fmt, "未检出", {}) == ("未检出", False)  # 判定词后面不带单位
        assert render.format_value({**fmt, "bilingual": True}, "未检出", {})[0] == "未检出Not detected"

    def test_verdict_gets_english_when_dictionary_has_it(self) -> None:
        assert render.format_value(VERDICT, "符合规定", {})[0] == "符合规定Conform"
        assert render.format_value(VERDICT, "符合规定", {"符合规定": "Conforms"})[0] == "符合规定Conforms"
        newline = {**VERDICT, "joiner": "\n"}
        assert render.format_value(newline, "未检出", {})[0] == "未检出\nNot detected"
        # 已经是英文的值原样输出；词典里没有的只出中文并回报缺英文
        assert render.format_value(VERDICT, "Conform", {}) == ("Conform", False)
        assert render.format_value(VERDICT, "无色", {}) == ("无色", True)

    def test_date_follows_template_pattern(self) -> None:
        assert render.format_value(DOT_DATE, "2026-07-29", {})[0] == "2026.07.29"
        assert render.format_value({"kind": "date", "pattern": "%Y年%m月%d日"}, "2026-07-29", {})[0] == "2026年07月29日"

    def test_unit_suffix_keeps_its_original_characters(self) -> None:
        text, _missing = render.format_value({"kind": "number", "decimals": 0, "suffix": "µg/mg"}, "900", {})
        assert text == "900µg/mg" and "\u00b5" in text  # µ 不能被归一成希腊字母 μ


class TestBuild:
    def test_writes_values_and_leaves_everything_else_untouched(self) -> None:
        ctx = _context(_data(), _values())
        blob, check = render._build(ctx)
        assert blob is not None and check["ok"] and check["blocking"] == []
        assert check["template"] is None  # 这里的标准对象没有模板文件名
        assert check["written"] == {"batch": 3, "items": 3, "positions": 6}
        out = TemplateDoc(blob).by_id
        assert out["P1"].text == "CERTIFICATE OF ANALYSIS   26112402"  # 固定文字还在
        assert flat_text(out["T0.R0.G1.p0"].element) == "HAF2607002A"
        assert flat_text(out["T0.R0.G3.p0"].element) == "2026.07.30"
        assert flat_text(out["T1.R2.G3.p0"].element) == "1.50%"
        assert flat_text(out["T1.R1.G3.p0"].element) == "符合规定Conform"
        before = TemplateDoc(_data()).by_id
        for sid in ("T1.R1.G2.p0", "T1.R2.G2.p0", "P2", "H.P0", "F.P0", "T0.R0.G0.p0"):
            assert out[sid].text == before[sid].text

    def test_missing_required_value_blocks_and_lists_it(self) -> None:
        ctx = _context(_data(), _values(**{"item:water": ""}))
        blob, check = render._build(ctx)
        assert blob is None
        assert check["ok"] is False
        assert check["blocking"] == [{"kind": "missing", "field": "item:water", "label": "水分", "item": True}]

    def test_optional_value_left_empty_blanks_the_old_sample(self) -> None:
        """非必填字段没值：清空该位置，绝不带着模板旧值出报告。"""
        ctx = _context(_data(), _values(**{"item:impurity_c": ""}), _binding(_data(), impurity_c=False))
        blob, check = render._build(ctx)
        assert blob is not None and check["ok"]
        assert check["written"] == {"batch": 3, "items": 2, "positions": 5}  # 被清空的位置不算写入
        assert flat_text(TemplateDoc(blob).by_id["T1.R4.G3.p0"].element) == ""

    def test_old_batch_value_left_anywhere_blocks(self) -> None:
        ctx = _context(_data(leak=True), _values())
        blob, check = render._build(ctx)
        assert blob is None
        assert check["blocking"] == [
            {"kind": "stale", "sample": "HAF2607001A", "found_in": ["P4"]}
        ]

    def test_value_equal_to_the_new_one_is_not_a_leak(self) -> None:
        """模板里出现的批号与新批号相同（没换批）不算泄漏。"""
        ctx = _context(_data(leak=True), _values(**{"batch:batch_no": "HAF2607001A"}))
        blob, check = render._build(ctx)
        assert blob is not None and check["ok"]

    def test_blank_template_renders_into_empty_slots(self) -> None:
        data = _data(filled=False)
        ctx = _context(data, _values())
        blob, check = render._build(ctx)
        assert blob is not None and check["ok"]
        out = TemplateDoc(blob).by_id
        assert out["P1"].text == "CERTIFICATE OF ANALYSIS   26112402"
        assert flat_text(out["T1.R2.G3.p0"].element) == "1.50%"
        assert flat_text(out["T0.R0.G3.p0"].element) == "2026.07.30"

    def test_unbound_items_and_missing_english_are_warnings_not_blocks(self) -> None:
        ctx = _context(_data(), _values(**{"item:appearance": "无色", "item:impurity_a": "0.23"}))
        blob, check = render._build(ctx)
        assert blob is not None and check["ok"]
        kinds = sorted(w["kind"] for w in check["warnings"])
        assert kinds == ["no_english", "unbound_items"]
        no_english = next(w for w in check["warnings"] if w["kind"] == "no_english")
        assert no_english["text"] == "无色" and no_english["label"] == "外观"
        unbound = next(w for w in check["warnings"] if w["kind"] == "unbound_items")
        assert unbound["labels"] == ["杂质A-RRT约0.76"]
        assert blob is not None
        assert flat_text(TemplateDoc(blob).by_id["T1.R1.G3.p0"].element) == "无色"

    def test_unbound_batch_field_with_value_warns_but_does_not_block(self) -> None:
        """「包装规格」确认标注时没标注位置（人认可了）：有登记值只提示，不再悄悄不出现在 COA 上。"""
        fields = dict(FIELDS)
        fields["batch:packaging"] = bind.FieldDef("batch:packaging", "batch", "包装规格", "Packaging")
        ctx = render._Context(
            CoaStandard(code="3205-006"),
            CoaReport(batch_no="HAF2607002A"),
            TemplateDoc(_data()),
            _binding(_data()),
            fields,
            _values(**{"batch:packaging": "6kg/Tin"}),
        )
        blob, check = render._build(ctx)
        assert blob is not None and check["ok"]
        assert check["warnings"] == [
            {"kind": "unbound_batch", "count": 1, "labels": ["包装规格"]}
        ]
        # 没标注位置就不写：模板里的原文原样留着
        assert flat_text(TemplateDoc(blob).by_id["T0.R1.G1.p0"].element) == "5kg/Tin"

    def test_binding_verdict_dictionary_wins_over_builtin(self) -> None:
        ctx = _context(_data(), _values())
        ctx.binding["verdicts"] = {"符合规定": "Complies"}
        blob, _check = render._build(ctx)
        assert blob is not None
        assert flat_text(TemplateDoc(blob).by_id["T1.R1.G3.p0"].element) == "符合规定Complies"

    def test_filename_is_batch_and_standard_code(self) -> None:
        assert render._filename(_context(_data(), _values())) == "HAF2607002A_3205-006_COA.docx"


class TestGuards:
    def test_binding_that_no_longer_matches_template_is_rejected(self) -> None:
        doc = TemplateDoc(_data())
        binding = _binding(_data())
        render._verify_slots(doc, binding)  # 原样：通过
        binding["fields"][1]["slots"][0]["sample"] = "HAF2699999A"
        with pytest.raises(AppException) as exc:
            render._verify_slots(doc, binding)
        assert exc.value.status_code == 409 and exc.value.detail_msg == ["T0.R0.G1.p0"]

    def test_unknown_slot_in_binding_is_rejected(self) -> None:
        doc = TemplateDoc(_data())
        binding = _binding(_data())
        binding["fields"][4]["slots"][0]["sid"] = "T9.R9.G9.p0"
        with pytest.raises(AppException) as exc:
            render._verify_slots(doc, binding)
        assert "对不上" in exc.value.message and exc.value.detail_msg == ["T9.R9.G9.p0"]
