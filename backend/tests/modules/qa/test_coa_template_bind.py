"""COA 模板标注：AI 输出解析、格式规则推断、确定性校验标记。

assemble 用仿真模板喂固定的标注载荷：每一类校验标记都对应一个实测里真实
出现过的模型错误（标到标准列、标题行流水号归给批号、同字段多处值不一致…）。
模型调用整体打桩（``_chat_json`` 返回固定结果），不依赖真实模型。
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

from app.modules.qa.service.coa import template_bind as bind
from app.modules.qa.service.coa.template_address import TemplateDoc
from tests.modules.qa._coa_template_builder import build_template


def _field(key: str, **overrides: Any) -> bind.FieldDef:
    base: dict[str, Any] = {
        "kind": "item",
        "label_cn": key,
        "label_en": None,
        "field_type": None,
        "unit": None,
        "spec_text": None,
        "value_type": "number",
    }
    base.update(overrides)
    return bind.FieldDef(key=key, **base)


def _fields() -> list[bind.FieldDef]:
    """与仿真模板对应的字段清单：5 个批次字段 + 外观/水分/杂质A/杂质C。"""
    return [
        _field("batch:batch_no", kind="batch", label_cn="批  号", label_en="Batch No."),
        _field("batch:serial_no", kind="batch", label_cn="流水号", label_en="Serial No."),
        _field("batch:mfg_date", kind="batch", label_cn="生产日期", label_en="Mfg. Date", field_type="date"),
        _field("batch:packaging", kind="batch", label_cn="包装规格", label_en="Packaging"),
        _field("batch:exp_date", kind="batch", label_cn="有效期", label_en="Exp. Date", field_type="date"),
        _field("item:appearance", label_cn="外观", label_en="Appearance", value_type="text"),
        _field("item:water", label_cn="水分", label_en="Water", unit="%", spec_text="≤5.0%"),
        _field("item:impurity_a", label_cn="杂质A-RRT约0.76", label_en="Impurity A (RRT 0.76)", unit="%", spec_text="≤3.0%"),
        _field("item:impurity_c", label_cn="杂质C-RRT约1.86", label_en="Impurity C (RRT 1.86)", unit="%", spec_text="≤1.0%"),
    ]


_AI_KEYS = {f.key: f for f in _fields()}


def _good_payload() -> dict[str, Any]:
    """模型标对时会给出的结果。"""
    return {
        "bindings": [
            {"field": "batch:serial_no", "slots": [{"id": "P1", "sample": "26081215"}]},
            {"field": "batch:batch_no", "slots": [{"id": "T0.R0.G1.p0", "sample": "HAF2607001A"}]},
            {"field": "batch:mfg_date", "slots": [{"id": "T0.R0.G3.p0", "sample": "2026.07.29"}]},
            {"field": "batch:packaging", "slots": [{"id": "T0.R1.G1.p0", "sample": "5kg/Tin"}]},
            {"field": "batch:exp_date", "slots": [{"id": "T0.R1.G3.p0", "sample": "2028.07.28"}]},
            {"field": "item:appearance", "slots": [{"id": "T1.R1.G3.p0", "sample": "符合规定Conform"}]},
            {"field": "item:water", "slots": [{"id": "T1.R2.G3.p0", "sample": "0.63%"}]},
            {"field": "item:impurity_a", "slots": [{"id": "T1.R3.G3.p0", "sample": "0.23%"}]},
            {"field": "item:impurity_c", "slots": [{"id": "T1.R4.G3.p0", "sample": "0.05%"}]},
        ],
        "unmapped": [],
    }


def _row(proposal: dict[str, Any], key: str) -> dict[str, Any]:
    return next(r for r in proposal["fields"] if r["field"] == key)


def _with(payload: dict[str, Any], field: str, slots: list[dict[str, Any]]) -> dict[str, Any]:
    """替换/追加某个字段的绑定。"""
    cloned = {"bindings": [dict(b) for b in payload["bindings"]], "unmapped": []}
    cloned["bindings"] = [b for b in cloned["bindings"] if b["field"] != field]
    if slots:
        cloned["bindings"].append({"field": field, "slots": slots})
    return cloned


def _assemble(payload: dict[str, Any], *, filled: bool = True, **kwargs: Any) -> dict[str, Any]:
    doc = TemplateDoc(build_template(filled=filled))
    return bind.assemble(doc, _fields(), _AI_KEYS, payload, **kwargs)


class TestParseAnnotation:
    def test_plain_payload_is_normalised(self) -> None:
        parsed = bind._parse_annotation(
            '{"bindings": [{"field": "item:1", "slots": [{"id": "T1.R2.G3.p0", "sample": 3}]}], "unmapped": ["item:2"]}'
        )
        assert parsed == {
            "bindings": [{"field": "item:1", "slots": [{"id": "T1.R2.G3.p0", "sample": "3"}]}],
            "unmapped": ["item:2"],
        }

    def test_enveloped_output_is_unwrapped(self) -> None:
        """实测里模型偶尔把结果多包一层 {"type", "content"}。"""
        inner = {"bindings": _good_payload()["bindings"], "unmapped": []}
        wrapped = json.dumps({"type": "json_object", "content": inner})
        assert bind._parse_annotation(wrapped)["bindings"] == inner["bindings"]

    def test_bare_list_is_accepted(self) -> None:
        assert len(bind._parse_annotation(json.dumps(_good_payload()["bindings"]))["bindings"]) == 9

    @pytest.mark.parametrize(
        "content",
        [
            "not json",
            '{"foo": 1}',
            '{"bindings": [{"field": 1, "slots": []}]}',
            '{"bindings": [{"field": "item:1", "slots": [{"sample": "x"}]}]}',
        ],
    )
    def test_malformed_output_raises_so_caller_retries(self, content: str) -> None:
        with pytest.raises(ValueError):
            bind._parse_annotation(content)


class TestFormatInference:
    def test_number_with_unit_from_sample(self) -> None:
        fmt = bind.infer_format(_field("item:x", unit="%"), "0.23%", "0.23%")
        assert fmt == {"kind": "number", "decimals": 2, "suffix": "%"}

    def test_padding_around_sample_does_not_hide_the_number(self) -> None:
        """整格记录的样例带着值两侧的排版空白，仍按数值推。"""
        fmt = bind.infer_format(_field("item:x", unit="%"), "\u2002\u20020.23%\u2002\u2002\u2002", "")
        assert fmt == {"kind": "number", "decimals": 2, "suffix": "%"}

    def test_number_without_unit_keeps_sample_decimals(self) -> None:
        fmt = bind.infer_format(_field("item:x"), "0.008", "0.008")
        assert fmt == {"kind": "number", "decimals": 3, "suffix": ""}

    def test_verdict_learns_english_and_joiner(self) -> None:
        same = bind.infer_format(_field("item:x", value_type="text"), "符合规定Conform", "符合规定Conform")
        assert same == {"kind": "text", "bilingual": True, "joiner": ""}
        split = bind.infer_format(_field("item:x", value_type="text"), "未检出", "未检出\nNot detected")
        assert split == {"kind": "text", "bilingual": True, "joiner": "\n"}

    def test_comparator_value_gets_unit_suffix(self) -> None:
        fmt = bind.infer_format(_field("item:x", unit="cfu/g", value_type="text"), "＜1cfu/g", "＜1cfu/g")
        assert fmt == {"kind": "text", "suffix": "cfu/g"}

    def test_blank_number_item_uses_defaults(self) -> None:
        # 登记成文字（未检出）时按文字规则补英文，所以数值格式也带上「补英文」
        water = bind.infer_format(_field("item:x", unit="%", spec_text="≤5.0%"), "", "")
        assert water == {
            "kind": "number", "decimals": 2, "suffix": "%", "bilingual": True, "joiner": "",
        }
        # 标准里的限度是「大的整数」（≥1050IU/mg、≤5000ppm）→ 0 位
        assay = bind.infer_format(_field("item:x", unit="IU/mg", spec_text="≥1050IU/mg"), "", "")
        assert assay["decimals"] == 0 and assay["suffix"] == "IU/mg"
        # 计数型限度（不得超过 5 个、≤1000cfu/g）结果是个数，也是 0 位——
        # 标准文字里同时带百分比阈值（＞0.30%）时照样算计数型
        count = bind.infer_format(_field("item:x", spec_text="＞0.30%的杂质不得超过5个"), "", "")
        assert count["decimals"] == 0
        cfu = bind.infer_format(_field("item:x", unit="cfu/g", spec_text="≤1000cfu/g"), "", "")
        assert cfu["decimals"] == 0
        # 带小数的百分比限度保持模板默认位数（≤5.0% 的结果印成 1.50%）
        assert bind.infer_format(_field("item:x", unit="%", spec_text="≤5%"), "", "")["decimals"] == 2

    def test_blank_text_item_gets_bilingual_default(self) -> None:
        fmt = bind.infer_format(_field("item:x", value_type="text"), "", "")
        assert fmt == {"kind": "text", "bilingual": True, "joiner": "", "suffix": ""}

    def test_batch_date_pattern_comes_from_sample(self) -> None:
        date_field = _field("batch:d", kind="batch", label_cn="d", field_type="date")
        assert bind.infer_format(date_field, "2026.07.29", "")["pattern"] == "%Y.%m.%d"
        assert bind.infer_format(date_field, "2026-07-29", "")["pattern"] == "%Y-%m-%d"
        assert bind.infer_format(date_field, "", "")["pattern"] == "%Y.%m.%d"

    def test_batch_text_is_written_as_entered(self) -> None:
        text_field = _field("batch:t", kind="batch", label_cn="t")
        assert bind.infer_format(text_field, "41.120kg", "") == {"kind": "text"}

    def test_normalize_fmt_fills_defaults_and_rejects_bad_date(self) -> None:
        assert bind.normalize_fmt({"kind": "number"}) == {
            "kind": "number", "decimals": 2, "suffix": "",
        }
        assert bind.normalize_fmt({"kind": "text", "joiner": "–"})["joiner"] == ""
        assert bind.normalize_fmt({"kind": "number", "decimals": 1, "bilingual": True}) == {
            "kind": "number", "decimals": 1, "suffix": "", "bilingual": True, "joiner": "",
        }
        # strftime 对未知指令不报错（%Q 原样输出），必须在这里拦住
        with pytest.raises(ValueError, match="只支持年月日"):
            bind.normalize_fmt({"kind": "date", "pattern": "%Y年%Q"})
        with pytest.raises(ValueError, match="只支持年月日"):
            bind.normalize_fmt({"kind": "date", "pattern": "%Y-%m-%d %H:%M"})


class TestNameMatch:
    def test_letters_and_digits_must_all_appear(self) -> None:
        """「杂质A-RRT约0.76」与「杂质C-RRT约1.86」整体很像，逐字比才分得开。"""
        name = ("杂质A-RRT约0.76", "Impurity A (RRT 0.76)")
        assert bind.name_matches(name, "杂质A-RRT约0.76 ｜ Impurity A (RRT 0.76) ｜ ≤3.0%", 0.8)
        assert not bind.name_matches(name, "杂质C-RRT约1.86 ｜ Impurity C (RRT 1.86) ｜ ≤1.0%", 0.8)

    def test_group_label_in_context_makes_merged_names_match(self) -> None:
        assert bind.name_matches(("纯度 DBM-A0", ""), "纯度 ｜ DBM-A0 ｜ 0.1%~1.0%", 0.8)
        assert not bind.name_matches(("纯度 DBM-A0", ""), "纯度 ｜ DBM-B0 ｜ 50.0%~75.0%", 0.8)

    def test_pure_chinese_name_needs_every_character(self) -> None:
        assert bind.name_matches(("水分", ""), "水分 ｜ Water ｜ ≤5.0%", 0.8)
        assert not bind.name_matches(("水分", ""), "干燥失重 ｜ Loss on drying ｜ ≤60.0%", 0.8)

    def test_english_name_rescues_when_chinese_name_is_not_contained(self) -> None:
        assert bind.name_matches(("组分", "Impurity H"), "杂质Impurity H ｜ ≤0.5%", 0.8)
        assert not bind.name_matches(("组分", "Impurity H"), "杂质Impurity I ｜ ≤0.5%", 0.8)

    def test_identical_chinese_names_cannot_be_told_apart(self) -> None:
        """已知局限：几个项目都叫「杂质」时，中文名在任何一行都对得上，要靠人工核对。"""
        assert bind.name_matches(("杂质", "Impurity H"), "杂质Impurity I ｜ ≤0.5%", 0.8)


class TestSlotPlanning:
    def test_plan_slot_modes(self) -> None:
        doc = TemplateDoc(build_template())
        assert bind.plan_slot(doc.by_id["T1.R2.G3.p0"], "0.63%") == ("replace", "0.63%")
        assert bind.plan_slot(doc.by_id["P1"], "26081215") == ("inplace", "26081215")

    def test_empty_sample_on_nonempty_slot_is_an_error(self) -> None:
        """实测里的列错位就是这样被抓到的：值标到了标准列，样例却是空。"""
        doc = TemplateDoc(build_template())
        with pytest.raises(ValueError, match="不是空格"):
            bind.plan_slot(doc.by_id["T1.R2.G2.p0"], "")

    def test_sample_not_in_slot_is_an_error(self) -> None:
        doc = TemplateDoc(build_template())
        with pytest.raises(ValueError, match="不在数据位"):
            bind.plan_slot(doc.by_id["T1.R2.G3.p0"], "9.99%")

    def test_repeated_sample_cannot_be_located(self) -> None:
        doc = TemplateDoc(build_template())
        with pytest.raises(ValueError, match="出现多次"):  # No.:COA-HAF-3205-006 里有三个 0
            bind.plan_slot(doc.by_id["P2"], "0")

    def test_derive_slot_guesses_value_in_body_paragraph(self) -> None:
        doc = TemplateDoc(build_template(filled=False))
        assert bind.derive_slot(doc.by_id["P1"], None) == ("inplace", "XXXXXXXX")
        assert bind.derive_slot(doc.by_id["T1.R2.G3.p0"], None) == ("replace", "")


class TestAssemble:
    def test_correct_annotation_has_no_flags_and_infers_formats(self) -> None:
        proposal = _assemble(_good_payload())
        assert proposal["problems"] == []
        assert proposal["needs_review"] == 0
        assert proposal["residue"] == []
        water = _row(proposal, "item:water")["slots"][0]
        assert water["fmt"] == {"kind": "number", "decimals": 2, "suffix": "%"}
        assert water["mode"] == "replace" and water["sample"] == "0.63%"
        serial = _row(proposal, "batch:serial_no")["slots"][0]
        assert (serial["mode"], serial["sample"], serial["flags"]) == ("inplace", "26081215", [])
        assert _row(proposal, "batch:mfg_date")["slots"][0]["fmt"] == {
            "kind": "date", "pattern": "%Y.%m.%d",
        }
        assert proposal["verdicts"] == {"符合规定": "Conform"}
        # 值两侧带排版空白的格子按整格记（回填时空白原样保留）
        impurity = _row(proposal, "item:impurity_a")["slots"][0]
        assert (impurity["mode"], impurity["sample"]) == ("replace", "\u2002\u20020.23%\u2002\u2002\u2002")

    def test_title_number_assigned_to_batch_no_is_flagged(self) -> None:
        """实测里模型把标题行流水号归给批号：同一字段两处当前值不同。"""
        payload = _with(
            _good_payload(),
            "batch:batch_no",
            [{"id": "T0.R0.G1.p0", "sample": "HAF2607001A"}, {"id": "P1", "sample": "26081215"}],
        )
        proposal = _assemble(_with(payload, "batch:serial_no", []))
        assert _row(proposal, "batch:batch_no")["flags"] == [
            "inconsistent_values", "body_paragraph",
        ]
        assert _row(proposal, "batch:serial_no")["flags"] == ["batch_unbound"]
        assert proposal["needs_review"] == 2

    def test_item_in_spec_column_is_dropped_and_reported(self) -> None:
        proposal = _assemble(
            _with(_good_payload(), "item:water", [{"id": "T1.R2.G2.p0", "sample": ""}])
        )
        assert _row(proposal, "item:water")["slots"] == []
        assert any("不是空格" in problem for problem in proposal["problems"])

    def test_item_outside_result_column_is_flagged(self) -> None:
        proposal = _assemble(
            _with(_good_payload(), "item:water", [{"id": "T1.R4.G0.p0", "sample": ""}])
        )
        assert _row(proposal, "item:water")["flags"] == ["not_in_result_column", "name_mismatch"]

    def test_item_on_wrong_row_is_flagged_by_name(self) -> None:
        payload = _with(_with(_good_payload(), "item:impurity_c", []), "item:impurity_a", [
            {"id": "T1.R4.G3.p0", "sample": "0.05%"},
        ])
        proposal = _assemble(payload)
        assert _row(proposal, "item:impurity_a")["flags"] == ["name_mismatch"]

    def test_batch_field_on_wrong_cell_is_flagged_by_label_and_sample(self) -> None:
        payload = _with(_with(_good_payload(), "batch:mfg_date", []), "batch:packaging", [
            {"id": "T0.R0.G3.p0", "sample": "2026.07.29"},
        ])
        proposal = _assemble(payload)
        assert _row(proposal, "batch:packaging")["flags"] == ["label_mismatch", "sample_looks_date"]
        payload = _with(_with(_good_payload(), "batch:packaging", []), "batch:mfg_date", [
            {"id": "T0.R1.G1.p0", "sample": "5kg/Tin"},
        ])
        proposal = _assemble(payload)
        assert _row(proposal, "batch:mfg_date")["flags"] == ["label_mismatch", "sample_not_date"]

    def test_title_line_serial_is_not_flagged_but_other_batch_fields_are(self) -> None:
        proposal = _assemble(_with(_good_payload(), "batch:batch_no", [{"id": "P2", "sample": "00"}]))
        assert _row(proposal, "batch:batch_no")["flags"] == ["body_paragraph"]

    def test_two_paragraphs_of_one_cell_cannot_share_a_field(self) -> None:
        proposal = _assemble(
            _with(
                _good_payload(),
                "batch:batch_no",
                [{"id": "T0.R0.G0.p0", "sample": "批  号"}, {"id": "T0.R0.G0.p1", "sample": "Batch No."}],
            )
        )
        # 绑到的是标签格自己的两个段落：除了同格多段，标签也对不上（上下文里没有「批号」）
        assert _row(proposal, "batch:batch_no")["flags"] == [
            "multi_paragraph_cell", "label_mismatch",
        ]

    def test_slot_bound_twice_keeps_first_and_reports_second(self) -> None:
        payload = _with(_good_payload(), "item:impurity_c", [{"id": "T1.R2.G3.p0", "sample": "0.63%"}])
        proposal = _assemble(payload)
        assert _row(proposal, "item:impurity_c")["slots"] == []
        assert any("已绑定到 item:water" in problem for problem in proposal["problems"])

    def test_unknown_address_is_ignored_and_reported(self) -> None:
        proposal = _assemble(_with(_good_payload(), "item:water", [{"id": "T9.R9.G9.p0", "sample": ""}]))
        assert _row(proposal, "item:water")["slots"] == []
        assert any("不存在" in problem for problem in proposal["problems"])

    def test_product_name_binding_is_ignored_without_noise(self) -> None:
        """品名/储存条件不回填：模型把它们当值绑上去不算问题。"""
        payload = _good_payload()
        payload["bindings"].append(
            {"field": "batch:product_name", "slots": [{"id": "T0.R0.G0.p0", "sample": "批  号"}]}
        )
        assert _assemble(payload)["problems"] == []

    def test_unmapped_and_out_of_list_fields_are_reported(self) -> None:
        payload = _good_payload()
        payload["unmapped"] = ["item:impurity_c", "item:404"]
        unmapped = _assemble(payload)["ai_unmapped"]
        assert [u["field"] for u in unmapped] == ["item:impurity_c"]

    def test_static_result_cell_must_be_acknowledged(self) -> None:
        """填过值的模板上，结果列没绑定又非空的格子 = 可能残留旧结果。"""
        payload = _with(_good_payload(), "item:appearance", [])
        proposal = _assemble(payload)
        assert [r["sid"] for r in proposal["residue"]] == ["T1.R1.G3.p0"]
        assert "符合规定Conform" in proposal["residue"][0]["text"]
        assert "外观" in proposal["residue"][0]["context"]
        acknowledged = _assemble(payload, static_slots=["T1.R1.G3.p0"])
        assert acknowledged["residue"] == [] and acknowledged["static_slots"] == ["T1.R1.G3.p0"]

    def test_blank_template_binds_empty_cells_with_default_formats(self) -> None:
        """真实模板大多是空白的：样例是空串或占位符，照样能绑，格式走默认值。"""
        blank = _good_payload()
        for binding in blank["bindings"]:
            for slot in binding["slots"]:
                slot["sample"] = "XXXXXXXX" if slot["id"] == "P1" else ""
        # 模板里写死的判定不变
        next(b for b in blank["bindings"] if b["field"] == "item:appearance")["slots"][0][
            "sample"
        ] = "符合规定Conform"
        proposal = _assemble(blank, filled=False)
        assert proposal["problems"] == [] and proposal["residue"] == []
        water = _row(proposal, "item:water")["slots"][0]
        assert (water["mode"], water["sample"], water["fmt"]["kind"], water["fmt"]["decimals"]) == (
            "replace", "", "number", 2,
        )
        assert _row(proposal, "batch:serial_no")["slots"][0]["sample"] == "XXXXXXXX"


class TestDescribeBinding:
    def test_saved_binding_is_described_like_a_proposal(self) -> None:
        doc = TemplateDoc(build_template())
        binding = {
            "fields": [
                {
                    "field": "item:water",
                    "required": False,
                    "slots": [
                        {"sid": "T1.R2.G3.p0", "mode": "replace", "sample": "0.63%",
                         "fmt": {"kind": "number", "decimals": 1, "suffix": "%"}}
                    ],
                },
                {"field": "item:removed", "required": True, "slots": []},
            ],
            "verdicts": {"无色": "Colourless"},
            "static_slots": ["T1.R1.G3.p0"],
        }
        described = bind.describe_binding(doc, _fields(), binding)
        water = _row(described, "item:water")
        assert water["required"] is False
        assert water["slots"][0]["fmt"]["decimals"] == 1
        assert _row(described, "item:impurity_a")["slots"] == []  # 没保存的绑定不出现
        assert described["verdicts"] == {"无色": "Colourless"}
        # 结果列里另外两个填了值的格子没绑定：如实列为残留（表头和已确认的固定文字格不算）
        assert [r["sid"] for r in described["residue"]] == ["T1.R3.G3.p0", "T1.R4.G3.p0"]

    def test_field_whose_config_changed_since_saving_is_flagged(self) -> None:
        """确认之后项目改了单位：重新打开时带标记（要人重新看格式），没改的不带。"""
        doc = TemplateDoc(build_template())
        fields = _fields()
        water = next(f for f in fields if f.key == "item:water")
        binding = {
            "field_set": [f.key for f in fields],
            "fields": [
                {
                    "field": "item:water",
                    "label_cn": "水分",
                    "required": True,
                    "config": bind.field_config(water),
                    "slots": [
                        {"sid": "T1.R2.G3.p0", "mode": "replace", "sample": "0.63%",
                         "fmt": {"kind": "number", "decimals": 2, "suffix": "%"}}
                    ],
                }
            ],
            "static_slots": [],
        }
        unchanged = bind.describe_binding(doc, fields, binding)
        assert _row(unchanged, "item:water")["flags"] == []
        ppm = [replace(f, unit="ppm") if f.key == "item:water" else f for f in fields]
        described = bind.describe_binding(doc, ppm, binding)
        assert _row(described, "item:water")["flags"] == ["config_changed"]
        # 已确认的格式规则原样带出来：改成什么样由人决定，系统不替人改
        assert _row(described, "item:water")["slots"][0]["fmt"]["suffix"] == "%"
        flagged = [r["field"] for r in described["fields"] if "config_changed" in r["flags"]]
        assert flagged == ["item:water"]
        assert described["flag_labels"]["config_changed"]


def _confirmed(fields: list[bind.FieldDef], bound: list[str]) -> dict[str, Any]:
    """模拟 save_template_binding 存下来的标注：确认时的字段清单 + 每条绑定当时的配置。"""
    return {
        "version": bind.BINDING_VERSION,
        "field_set": [f.key for f in fields],
        "fields": [
            {
                "field": f.key,
                "label_cn": f.label_cn,
                "required": True,
                "config": bind.field_config(f),
                "slots": [{"sid": "x", "mode": "replace", "sample": "", "fmt": {}}],
            }
            for f in fields
            if f.key in bound
        ],
        "static_slots": [],
    }


# 确认时绑定了位置的字段；杂质A 没找到位置，是核对时认可的不写入
_BOUND = [
    "batch:batch_no",
    "batch:serial_no",
    "batch:mfg_date",
    "batch:packaging",
    "batch:exp_date",
    "item:appearance",
    "item:water",
    "item:impurity_c",
]


def _template_fields() -> list[bind.FieldDef]:
    """build_fields 给出的形态：批次字段的类型总是算好的（文字/日期），不会是空。"""
    return [
        replace(f, field_type="text") if f.kind == "batch" and f.field_type is None else f
        for f in _fields()
    ]


def _without(fields: list[bind.FieldDef], key: str) -> list[bind.FieldDef]:
    return [f for f in fields if f.key != key]


class TestBindingDrift:
    """标注确认之后字段配置变了：对着当前配置把变化找出来，交给人工重新核对。"""

    def test_unchanged_config_has_no_drift(self) -> None:
        fields = _template_fields()
        assert bind.binding_drift(fields, _confirmed(fields, _BOUND)) is None

    def test_field_removed_from_standard_drops_its_annotation(self) -> None:
        fields = _template_fields()
        drift = bind.binding_drift(_without(fields, "item:water"), _confirmed(fields, _BOUND))
        assert drift is not None
        assert drift["removed"] == [{"field": "item:water", "label_cn": "水分"}]
        assert drift["added"] == [] and drift["changed"] == []
        assert drift["lines"] == ["「水分」已从标准里移除，它的标注不再生效"]

    def test_removed_entry_without_a_saved_name_still_reads_well(self) -> None:
        """早先的标注没记名字：批次字段还能从键上认，项目只剩一串 id。"""
        fields = _fields()
        batch = _confirmed(fields, _BOUND)
        entry = batch["fields"][0]  # batch:batch_no
        entry.pop("label_cn")
        entry["field"] = "batch:retest_date"  # 配置里已经没有这个键
        drift = bind.binding_drift(fields, batch)
        assert drift is not None
        assert drift["removed"] == [{"field": "batch:retest_date", "label_cn": "retest_date"}]

        item = _confirmed(fields, _BOUND)
        next(e for e in item["fields"] if e["field"] == "item:water").pop("label_cn")
        drift = bind.binding_drift(_without(fields, "item:water"), item)
        assert drift is not None
        assert drift["removed"] == [{"field": "item:water", "label_cn": "已移除的检测项目"}]

    def test_field_added_after_confirmation_is_not_reviewed(self) -> None:
        fields = _template_fields()
        retest = _field("batch:retest_date", kind="batch", label_cn="复验期", field_type="date")
        drift = bind.binding_drift([*fields, retest], _confirmed(fields, _BOUND))
        assert drift == {
            "removed": [],
            "added": [{"field": "batch:retest_date", "label_cn": "复验期", "kind": "batch"}],
            "changed": [],
            "lines": ["新增的「复验期」还没有标注位置"],
        }

    def test_lines_put_what_needs_action_first(self) -> None:
        """给人看的条目：要动手的排前面（改格式、挑位置），只是知会的排后面。"""
        fields = _template_fields()
        binding = _confirmed(fields, _BOUND)
        retest = _field("batch:retest_date", kind="batch", label_cn="复验期", field_type="date")
        current = [replace(f, unit="ppm") if f.key == "item:water" else f for f in fields]
        current = [f for f in current if f.key != "item:impurity_c"]
        drift = bind.binding_drift([*current, retest], binding)
        assert drift is not None
        assert drift["lines"] == [
            "「水分」的单位：% → ppm，格式要重新确认",
            "新增的「复验期」还没有标注位置",
            "「杂质C-RRT约1.86」已从标准里移除，它的标注不再生效",
        ]

    def test_too_many_changes_are_summarised(self) -> None:
        """整批替换项目时可能有几十处：逐条列到上限为止，其余并成一句。"""
        fields = _template_fields()
        extra = [
            _field(f"batch:f{index}", kind="batch", label_cn=f"字段{index}", field_type="text")
            for index in range(bind._DRIFT_LINE_LIMIT + 2)
        ]
        drift = bind.binding_drift([*fields, *extra], _confirmed(fields, _BOUND))
        assert drift is not None
        assert len(drift["added"]) == bind._DRIFT_LINE_LIMIT + 2
        assert len(drift["lines"]) == bind._DRIFT_LINE_LIMIT + 1
        assert drift["lines"][-1] == "……等共 10 处变化"

    def test_unbound_field_accepted_at_confirmation_is_not_new(self) -> None:
        """杂质A 确认时就没标注位置（人认可了）：不算新增；之后把它移出标准也没有标注作废。"""
        fields = _template_fields()
        assert "item:impurity_a" not in [e["field"] for e in _confirmed(fields, _BOUND)["fields"]]
        assert bind.binding_drift(fields, _confirmed(fields, _BOUND)) is None
        assert bind.binding_drift(_without(fields, "item:impurity_a"), _confirmed(fields, _BOUND)) is None

    def test_binding_without_a_field_set_cannot_tell_additions(self) -> None:
        """记字段清单之前存的标注：认不出新增，但移除和配置变化照常能查。"""
        fields = _template_fields()
        legacy = _confirmed(fields, _BOUND)
        legacy.pop("field_set")
        retest = _field("batch:retest_date", kind="batch", label_cn="复验期", field_type="date")
        assert bind.binding_drift([*fields, retest], legacy) is None
        assert bind.binding_drift(_without(fields, "item:water"), legacy) is not None

    def test_type_and_unit_changes_are_reported_in_words(self) -> None:
        fields = _template_fields()
        binding = _confirmed(fields, _BOUND)
        changed = [
            replace(f, field_type="date")
            if f.key == "batch:packaging"
            else replace(f, unit="ppm", value_type="text")
            if f.key == "item:water"
            else f
            for f in fields
        ]
        drift = bind.binding_drift(changed, binding)
        assert drift is not None
        assert drift["removed"] == [] and drift["added"] == []
        # 只列变了的那几项，顺序跟着标注走
        assert drift["changed"] == [
            {"field": "batch:packaging", "label_cn": "包装规格", "changes": ["类型：文字 → 日期"]},
            {"field": "item:water", "label_cn": "水分", "changes": ["单位：% → ppm", "值类型：数值 → 文字"]},
        ]

    def test_unit_appearing_after_confirmation_is_a_change(self) -> None:
        fields = _template_fields()
        binding = _confirmed(fields, _BOUND)
        with_unit = [replace(f, unit="%") if f.key == "item:appearance" else f for f in fields]
        drift = bind.binding_drift(with_unit, binding)
        assert drift is not None
        assert drift["changed"] == [
            {"field": "item:appearance", "label_cn": "外观", "changes": ["单位：空 → %"]}
        ]

    def test_reordering_and_renaming_are_not_drift(self) -> None:
        """标注按字段键/项目 id 关联：调顺序、改名字、改标准原文都不影响已确认的标注。"""
        fields = _template_fields()
        renamed = [
            replace(f, label_cn=f"{f.label_cn}（新）", label_en="Renamed", spec_text="≤9.9%")
            for f in reversed(fields)
        ]
        assert bind.binding_drift(renamed, _confirmed(fields, _BOUND)) is None


class TestFieldDefs:
    def test_batch_fields_skip_product_name_and_storage(self) -> None:
        """品名/储存条件不回填；字段是不是日期看键或标签对应的报告固定列。"""
        effective = [
            {"key": "product_name", "label_cn": "品名", "label_en": None, "field_type": "text"},
            {"key": "batch_no", "label_cn": "批号", "label_en": None, "field_type": "text"},
            {"key": "storage_conditions", "label_cn": "储存条件", "label_en": None, "field_type": "text"},
            {"key": "made_on", "label_cn": "生产日期", "label_en": None, "field_type": "text"},
            {"key": "note", "label_cn": "备注", "label_en": None, "field_type": "text"},
        ]
        fields = bind.field_defs(effective, [])
        assert [(f.key, f.field_type) for f in fields] == [
            ("batch:batch_no", "text"),
            ("batch:made_on", "date"),
            ("batch:note", "text"),
        ]


class TestPromptFields:
    def test_items_are_numbered_for_the_model(self) -> None:
        text, ai_keys = bind._prompt_fields(_fields())
        assert "- batch:batch_no：批次信息「批  号 / Batch No.」（文字）" in text
        assert "- item:1：检测项目「外观」，英文 Appearance" in text
        assert "- item:2：检测项目「水分」，英文 Water，标准 ≤5.0%，单位 %" in text
        assert "- item:4：检测项目「杂质C-RRT约1.86」" in text
        assert ai_keys["item:2"].key == "item:water" and ai_keys["batch:batch_no"].key == "batch:batch_no"
