"""核心判定与 COA 占位符格式化纯函数测试（此前零覆盖，所有填报/COA 链路都依赖它们）。"""

import pytest

from app.modules.quality.report_generator import (
    format_value,
    parse_placeholder,
    resolve_placeholders,
)
from app.modules.quality.service import TestTaskService

_J = TestTaskService._judge_value
_I = TestTaskService._infer_judge_mode


# ── _judge_value：数值自动判定 ──


def test_judge_le_inclusive_boundary():
    assert _J("≤", None, 3.0, 3.0) is True
    assert _J("≤", None, 3.0, 3.01) is False


def test_judge_lt_exclusive_boundary():
    assert _J("<", None, 3.0, 3.0) is False
    assert _J("<", None, 3.0, 2.99) is True


def test_judge_ge_and_gt():
    assert _J("≥", 91.0, None, 91.0) is True
    assert _J("≥", 91.0, None, 90.9) is False
    assert _J(">", 91.0, None, 91.0) is False
    assert _J(">", 91.0, None, 91.1) is True


def test_judge_range_inclusive():
    assert _J("范围", 1.0, 5.0, 1.0) is True
    assert _J("范围", 1.0, 5.0, 5.0) is True
    assert _J("范围", 1.0, 5.0, 5.1) is False
    assert _J("范围", 1.0, 5.0, 0.9) is False


def test_judge_zero_value_is_judged():
    # 0 是合法测量值，必须参与判定（此前前端有 || 把 0 当缺失的 bug）
    assert _J("≤", None, 3.0, 0.0) is True
    assert _J("≥", 1.0, None, 0.0) is False


@pytest.mark.parametrize("op,lo,hi", [
    ("≤", None, None),   # 缺上限
    ("<", None, None),
    ("≥", None, None),   # 缺下限
    (">", None, None),
    ("范围", None, 5.0),  # 范围缺一边
    ("范围", 1.0, None),
    ("≈", None, None),   # 未知运算符
    (None, 1.0, 5.0),    # 无运算符（文字型人工判定）
])
def test_judge_returns_none_when_limit_insufficient(op, lo, hi):
    assert _J(op, lo, hi, 2.0) is None


def test_infer_judge_mode():
    assert _I("≤", None, 3.0) == "auto"
    assert _I("≥", 91.0, None) == "auto"
    assert _I("范围", 1.0, 5.0) == "auto"
    assert _I(None, None, None) == "manual"  # 纯文字标准保留人工判定
    assert _I("≤", None, None) == "manual"   # 有运算符但无限度也算人工


# ── parse_placeholder / format_value ──


def test_parse_placeholder_no_format():
    spec = parse_placeholder("批号")
    assert spec.name == "批号" and spec.has_format is False
    assert format_value("HAF2608001B", spec) == "HAF2608001B"


def test_parse_placeholder_dec_with_unit():
    spec = parse_placeholder("水分 | dec(1, '%')")
    assert (spec.decimals, spec.suffix) == (1, "%")
    assert spec.threshold is None
    assert format_value(0.5, spec) == "0.5%"


def test_parse_placeholder_threshold_switching():
    spec = parse_placeholder("杂质A | dec(2, '%', 0.1, 3)")
    assert (spec.decimals, spec.suffix, spec.threshold, spec.second_decimals) == (2, "%", 0.1, 3)
    # 低于阈值用 3 位小数（如 0.047%），否则 2 位
    assert format_value(0.047, spec) == "0.047%"
    assert format_value(0.63, spec) == "0.63%"


def test_parse_placeholder_chinese_quotes():
    spec = parse_placeholder("总杂质 | dec(2, '％')")
    assert spec.suffix == "％"


def test_format_value_missing_or_non_numeric():
    spec = parse_placeholder("水分 | dec(1, '%')")
    assert format_value(None, spec) == ""
    assert format_value("", spec) == ""
    # 非数值原样输出（如「符合规定」）
    assert format_value("符合规定", spec) == "符合规定"


# ── resolve_placeholders：占位符名 ↔ 数据键兜底映射 ──


def test_resolve_exact_hit_untouched():
    assert resolve_placeholders({"水分": 0.5}, ["水分"]) == {"水分": 0.5}


def test_resolve_normalized_match():
    # 占位符「ph」→ 数据键「pH」（归一化小写相等）
    assert resolve_placeholders({"pH": 6.5}, ["ph"])["ph"] == 6.5


def test_resolve_prefix_match_takes_longest():
    data = {"单去氯万古霉素": 0.9, "万古霉素": 0.8}
    resolved = resolve_placeholders(data, ["单去氯"])
    assert resolved["单去氯"] == 0.9


def test_resolve_reverse_prefix():
    # 数据键是占位符前缀：「吸光度」→「吸光度370nm」
    resolved = resolve_placeholders({"吸光度": 0.12}, ["吸光度370nm"])
    assert resolved["吸光度370nm"] == 0.12


def test_resolve_skips_judgement_keys_as_source():
    # 判定后缀键不作为映射来源：占位符「水分_判定」不能被「水分」的值覆盖
    data = {"水分": 0.5, "水分_判定": "合格"}
    resolved = resolve_placeholders(data, ["水分_判定"])
    assert resolved["水分_判定"] == "合格"  # 保持原值，未被 0.5 覆盖
