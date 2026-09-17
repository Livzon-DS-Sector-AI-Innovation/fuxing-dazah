"""Ticket 02：消防 AI 列契约单测。"""

from __future__ import annotations

from app.modules.safety.service.fire_alarm import contract


def test_field_names_and_types() -> None:
    assert contract.AI_FIELD_NAMES == (
        "AI维度",
        "AI原因分析",
        "AI整改方向",
        "AI分析时间",
    )
    assert contract.AI_DIMENSION_FIELD == "AI维度"
    assert contract.FIELD_TYPE_SINGLE_SELECT == 3
    assert contract.FIELD_TYPE_TEXT == 1
    assert contract.FIELD_TYPE_DATE == 5


def test_dimension_mapping_is_bidirectional() -> None:
    for option, code in contract.AI_DIMENSION_OPTION_TO_CODE.items():
        assert contract.option_to_dimension(option) == code
        assert contract.dimension_to_option(code) == option
    assert contract.option_to_dimension("未知") is None
    assert contract.dimension_to_option("unknown") is None
    assert contract.option_to_dimension(None) is None
    assert contract.dimension_to_option(None) is None
    assert contract.option_to_dimension("") is None
    assert contract.dimension_to_option("") is None


def test_field_specs_match_column_contract() -> None:
    specs = contract.build_field_specs()
    assert [spec.name for spec in specs] == list(contract.AI_FIELD_NAMES)

    assert specs[0].field_type == contract.FIELD_TYPE_SINGLE_SELECT
    assert specs[0].property_ == {
        "options": [
            {"name": "工艺"},
            {"name": "人员操作"},
            {"name": "设备设施"},
            {"name": "其他"},
        ]
    }
    assert specs[1].field_type == contract.FIELD_TYPE_TEXT
    assert specs[2].field_type == contract.FIELD_TYPE_TEXT
    assert specs[3].field_type == contract.FIELD_TYPE_DATE
    assert contract.AI_FIELD_SPECS == specs
