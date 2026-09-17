"""底座过滤条件构造 / 下推能力矩阵 / 北京时间窗口 单测（纯函数，无 IO、无替身）。

口径：把 hazard_direct 与 special_op_direct 在真机上实测出的 Bitable 约束
（见 .scratch/special-op-direct/HANDOFF.md 的 C2 节）写成可执行断言；
收敛旧包时任何一条被改动都必须先解释。

覆盖票据 03 的验收项：
- flat AND / 顶层 OR 形态与嵌套拒绝
- 能力矩阵：单选不支持 contains、文本支持 contains、日期只按天
- 窗口 -> 北京时间自然日集合（1 天 / 2 天 / 7 天）
- 应用侧毫秒裁剪（半开区间）与按天查询合并配方
- 北京时间固定 UTC+8，不受进程本地时区影响
"""

from __future__ import annotations

import ast
import os
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from app.modules.safety.service.bitable_direct import filters

UTC_MINUS_5 = timezone(timedelta(hours=-5))


def bjt(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=filters.BJT)


def ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _module_source() -> str:
    return Path(str(filters.__file__)).read_text(encoding="utf-8")


def _called_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


class TestCapabilityMatrix:
    @pytest.mark.parametrize("operator", ["is", "isNot", "isEmpty", "isNotEmpty"])
    def test_select_supports_only_equality_operators(self, operator: str) -> None:
        assert filters.supports("select", operator) is True

    @pytest.mark.parametrize(
        "operator", ["contains", "doesNotContain", "isGreater", "isLess"]
    )
    def test_select_rejects_contains_and_ranges(self, operator: str) -> None:
        assert filters.supports("select", operator) is False

    def test_select_contains_is_rejected_by_matrix(self) -> None:
        """实测：单选字段 contains = InvalidFilter（special-op HANDOFF C2）。"""
        with pytest.raises(ValueError, match="不支持算子"):
            filters.ensure_supported("select", "contains")

    def test_text_supports_contains(self) -> None:
        assert filters.supports("text", "contains") is True
        assert filters.supports("text", "doesNotContain") is True

    def test_checked_condition_allows_text_contains(self) -> None:
        cond = filters.checked_condition("text", "发起人部门", "contains", ["工程部"])
        assert cond["operator"] == "contains"

    @pytest.mark.parametrize(
        "operator", ["isGreaterEqual", "isLessEqual", "contains"]
    )
    def test_datetime_rejects_equal_range_and_contains(self, operator: str) -> None:
        assert filters.supports("datetime", operator) is False

    @pytest.mark.parametrize("operator", ["isGreater", "isLess"])
    def test_datetime_supports_range_boundaries(self, operator: str) -> None:
        assert filters.supports("datetime", operator) is True

    def test_date_range_operators_are_greater_less_only(self) -> None:
        assert filters.DATE_RANGE_OPERATORS == frozenset({"isGreater", "isLess"})

    def test_attachment_only_supports_empty_checks(self) -> None:
        assert filters.operators_for("attachment") == frozenset(
            {"isEmpty", "isNotEmpty"}
        )

    def test_unknown_field_type_has_no_operators(self) -> None:
        """number / checkbox 不在底座取值范围内，能力矩阵不臆造。"""
        assert filters.operators_for("number") == frozenset()
        assert filters.supports("number", "is") is False

    def test_field_type_lookup_is_case_insensitive(self) -> None:
        assert filters.operators_for(" SELECT ") == filters.operators_for("select")

    def test_every_matrix_operator_is_known(self) -> None:
        for field_type in filters.FIELD_TYPES:
            ops = filters.operators_for(field_type)
            assert ops
            assert ops <= filters.COMPARISON_OPERATORS

    def test_unknown_operator_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="未知算子"):
            filters.checked_condition("text", "描述", "isLike", ["x"])


class TestConditionBuilders:
    def test_condition_shape(self) -> None:
        assert filters.condition("整改状态", "is", ["未关闭"]) == {
            "field_name": "整改状态",
            "operator": "is",
            "value": ["未关闭"],
        }

    def test_condition_empty_value_defaults_to_empty_list(self) -> None:
        assert filters.condition("隐患描述（AI）", "isEmpty")["value"] == []

    def test_condition_accepts_tuple_value(self) -> None:
        cond = filters.condition("检查日期", "is", ("ExactDate", "1"))
        assert cond["value"] == ["ExactDate", "1"]

    @pytest.mark.parametrize(
        ("field_name", "operator"), [("", "is"), ("x", "")]
    )
    def test_condition_rejects_blank_field_or_operator(
        self, field_name: str, operator: str
    ) -> None:
        with pytest.raises(ValueError):
            filters.condition(field_name, operator)

    def test_checked_condition_returns_leaf(self) -> None:
        assert filters.checked_condition(
            "select", "整改状态", "is", ["已关闭"]
        ) == {
            "field_name": "整改状态",
            "operator": "is",
            "value": ["已关闭"],
        }

    def test_checked_condition_rejects_matrix_violation(self) -> None:
        with pytest.raises(ValueError, match="不支持算子"):
            filters.checked_condition("select", "整改状态", "contains", ["关闭"])

    def test_and_group_shape(self) -> None:
        cond = filters.condition("整改状态", "isNot", ["已关闭"])
        assert filters.and_group([cond]) == {
            "conjunction": "and",
            "conditions": [cond],
        }

    def test_or_group_shape(self) -> None:
        a = filters.condition("整改状态", "is", ["未关闭"])
        b = filters.condition("整改状态", "is", ["整改中"])
        assert filters.or_group([a, b]) == {
            "conjunction": "or",
            "conditions": [a, b],
        }

    def test_and_group_accepts_generator(self) -> None:
        cond = filters.condition("整改状态", "is", ["未关闭"])
        group = filters.and_group(c for c in [cond])
        assert group["conditions"] == [cond]

    @pytest.mark.parametrize("builder", ["and_group", "or_group"])
    def test_group_rejects_empty_conditions(self, builder: str) -> None:
        func = getattr(filters, builder)
        with pytest.raises(ValueError, match="空 conditions"):
            func([])

    def test_and_group_rejects_nested_or_group(self) -> None:
        a = filters.condition("整改状态", "is", ["未关闭"])
        b = filters.condition("整改状态", "is", ["整改中"])
        nested = filters.or_group([a, b])
        with pytest.raises(ValueError, match="嵌套条件组"):
            filters.and_group([nested, a])

    def test_or_group_rejects_nested_and_group(self) -> None:
        a = filters.condition("整改状态", "is", ["未关闭"])
        b = filters.condition("整改状态", "is", ["整改中"])
        nested = filters.and_group([a, b])
        with pytest.raises(ValueError, match="嵌套条件组"):
            filters.or_group([nested, a])

    def test_and_group_rejects_non_condition_item(self) -> None:
        with pytest.raises(ValueError, match="不是合法的 leaf 条件"):
            filters.and_group([{"field_name": "x"}])

    def test_flat_group_empty_returns_none(self) -> None:
        assert filters.flat_group([]) is None

    def test_flat_group_and_shape(self) -> None:
        cond = filters.condition("整改状态", "is", ["未关闭"])
        assert filters.flat_group([cond]) == {
            "conjunction": "and",
            "conditions": [cond],
        }

    def test_flat_group_or_shape(self) -> None:
        a = filters.condition("整改状态", "is", ["未关闭"])
        b = filters.condition("整改状态", "is", ["整改中"])
        assert filters.flat_group([a, b], "or") == {
            "conjunction": "or",
            "conditions": [a, b],
        }

    def test_flat_group_rejects_unknown_conjunction(self) -> None:
        cond = filters.condition("整改状态", "is", ["未关闭"])
        with pytest.raises(ValueError, match="conjunction"):
            filters.flat_group([cond], "xor")

    def test_flat_group_propagates_nesting_rejection(self) -> None:
        nested = filters.and_group([filters.condition("整改状态", "is", ["未关闭"])])
        with pytest.raises(ValueError, match="嵌套条件组"):
            filters.flat_group([nested])


class TestOrDateConstraint:
    """实测约束：顶层 OR 可用，但不能与日期条件组合（组合只能靠嵌套，而嵌套非法）。"""

    def test_or_group_rejects_date_range_condition(self) -> None:
        cond = filters.date_condition("检查日期", bjt(2026, 9, 17))
        assert cond is not None
        with pytest.raises(ValueError, match="日期条件"):
            filters.or_group([cond])

    def test_or_group_rejects_exact_date_is_condition(self) -> None:
        cond = filters.condition(
            "检查日期", "is", filters.exact_date_value(bjt(2026, 9, 17))
        )
        with pytest.raises(ValueError, match="日期条件"):
            filters.or_group([cond])

    def test_is_date_condition_detects_marker_and_range(self) -> None:
        marker = filters.condition("检查日期", "is", ["ExactDate", "1"])
        assert filters.is_date_condition(marker) is True
        range_cond = filters.condition("检查日期", "isGreater", ["ExactDate", "1"])
        assert filters.is_date_condition(range_cond) is True
        assert filters.is_date_condition(
            filters.condition("整改状态", "is", ["已关闭"])
        ) is False

    def test_and_group_still_allows_flat_date_plus_select(self) -> None:
        date_cond = filters.date_condition("检查日期", bjt(2026, 9, 17))
        assert date_cond is not None
        status = filters.condition("整改状态", "is", ["已关闭"])
        group = filters.and_group([date_cond, status])
        assert group["conjunction"] == "and"
        assert len(group["conditions"]) == 2


class TestDayFilters:
    def test_day_window_is_bjt_midnight_to_next_midnight(self) -> None:
        start, end = filters.day_window(date(2026, 9, 17))
        # 北京时间 09-17 00:00 == UTC 09-16 16:00
        assert start == datetime(2026, 9, 16, 16, 0, tzinfo=UTC)
        assert end == datetime(2026, 9, 17, 16, 0, tzinfo=UTC)
        assert end - start == timedelta(days=1)

    def test_bjt_day_start_uses_fixed_offset(self) -> None:
        assert filters.bjt_day_start(date(2026, 1, 1)).utcoffset() == timedelta(
            hours=8
        )

    def test_date_range_window_is_half_open(self) -> None:
        start, end = filters.date_range_window(date(2026, 9, 17), date(2026, 9, 18))
        assert start == datetime(2026, 9, 16, 16, 0, tzinfo=UTC)
        assert end == datetime(2026, 9, 18, 16, 0, tzinfo=UTC)

    def test_date_range_window_none_passthrough(self) -> None:
        assert filters.date_range_window(None, None) == (None, None)
        start, end = filters.date_range_window(date(2026, 9, 17), None)
        assert start is not None
        assert start.tzinfo is not None
        assert end is None

    def test_exact_date_value_shape(self) -> None:
        assert filters.exact_date_value(bjt(2026, 9, 17)) == [
            "ExactDate",
            str(ms(bjt(2026, 9, 17))),
        ]

    def test_day_conditions_are_bjt_day_bounds(self) -> None:
        conds = filters.day_conditions("报警时间", date(2026, 9, 17))
        assert [c["operator"] for c in conds] == ["isGreater", "isLess"]
        assert conds[0]["value"] == ["ExactDate", str(ms(bjt(2026, 9, 17)))]
        assert conds[1]["value"] == ["ExactDate", str(ms(bjt(2026, 9, 18)))]

    def test_day_filter_is_flat_and_with_two_conditions(self) -> None:
        flt = filters.day_filter("报警时间", date(2026, 9, 17))
        assert flt["conjunction"] == "and"
        assert len(flt["conditions"]) == 2

    def test_date_condition_lower_uses_is_greater(self) -> None:
        cond = filters.date_condition(
            "检查日期", datetime(2026, 9, 1, tzinfo=UTC), lower=True
        )
        assert cond is not None
        assert cond["operator"] == "isGreater"

    def test_date_condition_upper_uses_is_less(self) -> None:
        cond = filters.date_condition(
            "检查日期", datetime(2026, 9, 1, tzinfo=UTC), lower=False
        )
        assert cond is not None
        assert cond["operator"] == "isLess"

    def test_date_condition_parses_naive_iso_as_utc(self) -> None:
        """兼容 hazard 既有 _date_cond：无时区 ISO 字符串按 UTC 解释。"""
        cond = filters.date_condition("检查日期", "2026-09-17T00:00:00")
        assert cond is not None
        assert cond["value"] == [
            "ExactDate",
            str(ms(datetime(2026, 9, 17, tzinfo=UTC))),
        ]

    def test_date_condition_keeps_aware_iso_offset(self) -> None:
        cond = filters.date_condition("检查日期", "2026-09-17T00:00:00+08:00")
        assert cond is not None
        assert cond["value"] == ["ExactDate", str(ms(bjt(2026, 9, 17)))]

    def test_date_condition_naive_datetime_is_utc(self) -> None:
        cond = filters.date_condition("检查日期", datetime(2026, 9, 17, 0, 0))
        assert cond is not None
        assert cond["value"] == [
            "ExactDate",
            str(ms(datetime(2026, 9, 17, tzinfo=UTC))),
        ]

    def test_date_condition_bjt_uses_bjt_instant(self) -> None:
        cond = filters.date_condition("检查日期", bjt(2026, 9, 17))
        assert cond is not None
        assert cond["value"] == [
            "ExactDate",
            str(ms(datetime(2026, 9, 16, 16, 0, tzinfo=UTC))),
        ]

    def test_date_condition_returns_none_for_bad_input(self) -> None:
        assert filters.date_condition("检查日期", "not-a-date") is None


class TestWindowDays:
    def test_natural_day_window_is_one_day(self) -> None:
        assert filters.window_days(bjt(2026, 9, 17), bjt(2026, 9, 18)) == [
            date(2026, 9, 17)
        ]

    def test_rolling_24h_window_is_two_days(self) -> None:
        days = filters.window_days(bjt(2026, 9, 16, 17), bjt(2026, 9, 17, 17))
        assert days == [date(2026, 9, 16), date(2026, 9, 17)]

    def test_natural_week_window_is_seven_days(self) -> None:
        days = filters.window_days(bjt(2026, 9, 14), bjt(2026, 9, 21))
        assert days == [date(2026, 9, 14) + timedelta(days=i) for i in range(7)]

    def test_end_at_midnight_excludes_that_day(self) -> None:
        days = filters.window_days(bjt(2026, 9, 17), bjt(2026, 9, 18))
        assert date(2026, 9, 18) not in days

    def test_window_starting_partway_through_a_day(self) -> None:
        days = filters.window_days(bjt(2026, 9, 17, 23, 59), bjt(2026, 9, 18, 0, 1))
        assert days == [date(2026, 9, 17), date(2026, 9, 18)]

    def test_sub_day_window_within_same_day_is_one_day(self) -> None:
        days = filters.window_days(bjt(2026, 9, 17, 8), bjt(2026, 9, 17, 12))
        assert days == [date(2026, 9, 17)]

    def test_cross_month(self) -> None:
        days = filters.window_days(bjt(2026, 9, 30, 17), bjt(2026, 10, 1, 17))
        assert days == [date(2026, 9, 30), date(2026, 10, 1)]

    def test_cross_year(self) -> None:
        days = filters.window_days(bjt(2026, 12, 31, 17), bjt(2027, 1, 1, 17))
        assert days == [date(2026, 12, 31), date(2027, 1, 1)]

    def test_multi_day_count(self) -> None:
        days = filters.window_days(bjt(2026, 9, 1, 9), bjt(2026, 9, 11, 9))
        assert len(days) == 11
        assert days[0] == date(2026, 9, 1)
        assert days[-1] == date(2026, 9, 11)

    def test_empty_window_returns_empty(self) -> None:
        assert filters.window_days(bjt(2026, 9, 17, 12), bjt(2026, 9, 17, 12)) == []

    def test_reversed_window_returns_empty(self) -> None:
        assert filters.window_days(bjt(2026, 9, 18), bjt(2026, 9, 17)) == []

    def test_naive_boundary_rejected(self) -> None:
        with pytest.raises(ValueError, match="aware"):
            filters.window_days(datetime(2026, 9, 17), bjt(2026, 9, 18))

    def test_same_instant_in_utc_gives_same_days(self) -> None:
        start = bjt(2026, 9, 16, 17).astimezone(UTC)
        end = bjt(2026, 9, 17, 17).astimezone(UTC)
        assert filters.window_days(start, end) == [
            date(2026, 9, 16),
            date(2026, 9, 17),
        ]

    def test_day_queries_plan_shape(self) -> None:
        plan = filters.day_queries(
            "报警时间", bjt(2026, 9, 16, 17), bjt(2026, 9, 17, 17)
        )
        assert [day for day, _ in plan] == [date(2026, 9, 16), date(2026, 9, 17)]
        for _, flt in plan:
            assert flt["conjunction"] == "and"
            assert [c["operator"] for c in flt["conditions"]] == [
                "isGreater",
                "isLess",
            ]

    def test_day_queries_empty_window(self) -> None:
        assert filters.day_queries("报警时间", bjt(2026, 9, 17), bjt(2026, 9, 17)) == []


class TestTrim:
    def test_in_window_start_inclusive(self) -> None:
        start = bjt(2026, 9, 17)
        end = bjt(2026, 9, 18)
        assert filters.in_window(ms(start), start, end) is True

    def test_in_window_end_exclusive(self) -> None:
        start = bjt(2026, 9, 17)
        end = bjt(2026, 9, 18)
        assert filters.in_window(ms(end) - 1, start, end) is True
        assert filters.in_window(ms(end), start, end) is False

    @pytest.mark.parametrize("value", [None, 0, -1])
    def test_in_window_missing_values(self, value: int | None) -> None:
        assert filters.in_window(value, bjt(2026, 9, 17), bjt(2026, 9, 18)) is False

    def test_in_window_accepts_aware_datetime(self) -> None:
        start = bjt(2026, 9, 17, 17)
        end = bjt(2026, 9, 18, 17)
        assert filters.in_window(bjt(2026, 9, 17, 17), start, end) is True
        assert filters.in_window(bjt(2026, 9, 18, 17), start, end) is False

    def test_in_window_naive_datetime_rejected(self) -> None:
        with pytest.raises(ValueError, match="aware"):
            filters.in_window(
                datetime(2026, 9, 17), bjt(2026, 9, 17), bjt(2026, 9, 18)
            )

    def test_trim_records_keeps_half_open_boundaries(self) -> None:
        start = bjt(2026, 9, 17)
        end = bjt(2026, 9, 18)
        records: list[dict[str, Any]] = [
            {"id": "before", "t": ms(start) - 1},
            {"id": "start", "t": ms(start)},
            {"id": "inside", "t": ms(start) + 1},
            {"id": "end", "t": ms(end)},
        ]
        kept = filters.trim_records(records, lambda r: r["t"], start=start, end=end)
        assert [r["id"] for r in kept] == ["start", "inside"]

    def test_trim_records_skips_missing_time(self) -> None:
        records: list[dict[str, Any]] = [
            {"id": "none", "t": None},
            {"id": "zero", "t": 0},
            {"id": "negative", "t": -1},
        ]
        kept = filters.trim_records(
            records, lambda r: r["t"], start=bjt(2026, 9, 17), end=bjt(2026, 9, 18)
        )
        assert kept == []

    def test_trim_records_accepts_datetime_getter(self) -> None:
        start = bjt(2026, 9, 17)
        end = bjt(2026, 9, 18)
        records: list[dict[str, Any]] = [
            {"id": "ok", "t": bjt(2026, 9, 17, 12)},
            {"id": "late", "t": end},
        ]
        kept = filters.trim_records(records, lambda r: r["t"], start=start, end=end)
        assert [r["id"] for r in kept] == ["ok"]

    def test_trim_records_preserves_order(self) -> None:
        start = bjt(2026, 9, 17)
        end = bjt(2026, 9, 18)
        records: list[dict[str, Any]] = [
            {"id": name, "t": ms(bjt(2026, 9, 17, 12))} for name in ("c", "a", "b")
        ]
        kept = filters.trim_records(records, lambda r: r["t"], start=start, end=end)
        assert [r["id"] for r in kept] == ["c", "a", "b"]


class TestUnionByRecordId:
    def test_union_dedupes_by_record_id(self) -> None:
        a: dict[str, Any] = {"record_id": "rec1", "v": 1}
        b: dict[str, Any] = {"record_id": "rec2", "v": 2}
        assert filters.union_by_record_id([[a], [b, a]]) == [a, b]

    def test_union_same_id_keeps_last_value(self) -> None:
        first: dict[str, Any] = {"record_id": "rec1", "v": 1}
        second: dict[str, Any] = {"record_id": "rec1", "v": 2}
        assert filters.union_by_record_id([[first], [second]]) == [second]

    def test_union_keeps_records_without_id_at_end(self) -> None:
        with_id: dict[str, Any] = {"record_id": "rec1", "v": 1}
        no_id: dict[str, Any] = {"v": 2}
        assert filters.union_by_record_id([[no_id], [with_id]]) == [with_id, no_id]

    def test_union_empty_input(self) -> None:
        assert filters.union_by_record_id([]) == []


class TestRollingWindowRecipe:
    """把 fire-alarm 的滚动 24 小时做法（票据 03 显式约束）跑成可执行断言。"""

    START = bjt(2026, 9, 16, 17)
    END = bjt(2026, 9, 17, 17)

    @staticmethod
    def _record(record_id: str, when: datetime) -> dict[str, Any]:
        return {
            "record_id": record_id,
            "fields": {"报警时间": int(when.timestamp() * 1000)},
        }

    def test_plan_queries_each_day_then_trim_keeps_window(self) -> None:
        day1 = [
            self._record("before", bjt(2026, 9, 16, 16, 59, 59)),
            self._record("start", self.START),
            self._record("after", bjt(2026, 9, 16, 23, 0)),
        ]
        day2 = [
            self._record("mid", bjt(2026, 9, 17, 9, 0)),
            self._record("end", self.END),
            self._record("late", bjt(2026, 9, 17, 17, 0, 1)),
        ]
        merged = filters.union_by_record_id([day1, day2])
        kept = filters.trim_records(
            merged,
            lambda r: r["fields"]["报警时间"],
            start=self.START,
            end=self.END,
        )
        assert [r["record_id"] for r in kept] == ["start", "after", "mid"]

    def test_same_record_returned_by_both_days_is_deduped(self) -> None:
        rec = self._record("dup", bjt(2026, 9, 17, 1, 0))
        assert filters.union_by_record_id([[rec], [rec]]) == [rec]


class TestBeijingTimeIsFixed:
    def test_bjt_offset_is_exactly_eight_hours(self) -> None:
        assert filters.BJT.utcoffset(None) == timedelta(hours=8)

    def test_same_instant_in_three_zones_gives_same_days(self) -> None:
        start_utc = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)
        end_utc = datetime(2026, 9, 17, 9, 0, tzinfo=UTC)
        start_bjt = bjt(2026, 9, 16, 17)
        end_bjt = bjt(2026, 9, 17, 17)
        start_ny = start_utc.astimezone(UTC_MINUS_5)
        end_ny = end_utc.astimezone(UTC_MINUS_5)
        expected = [date(2026, 9, 16), date(2026, 9, 17)]
        assert filters.window_days(start_utc, end_utc) == expected
        assert filters.window_days(start_bjt, end_bjt) == expected
        assert filters.window_days(start_ny, end_ny) == expected

    def test_boundary_check_is_instant_based(self) -> None:
        start = bjt(2026, 9, 17, 0)
        end = bjt(2026, 9, 18, 0)
        boundary_ms = ms(start)
        same_instant = datetime.fromtimestamp(
            boundary_ms / 1000, tz=UTC
        ).astimezone(UTC_MINUS_5)
        assert filters.in_window(boundary_ms, start, end) is True
        assert filters.in_window(same_instant, start, end) is True

    def test_process_tz_env_does_not_change_results(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tzset: Callable[[], None] | None = getattr(time, "tzset", None)
        if tzset is None:
            pytest.skip("time.tzset 仅 Unix 可用；跨时区断言由同瞬时用例覆盖")
        original = os.environ.get("TZ")
        monkeypatch.setenv("TZ", "America/New_York")
        tzset()
        try:
            assert filters.window_days(
                bjt(2026, 9, 16, 17), bjt(2026, 9, 17, 17)
            ) == [date(2026, 9, 16), date(2026, 9, 17)]
            assert filters.day_window(date(2026, 9, 17))[0] == datetime(
                2026, 9, 16, 16, 0, tzinfo=UTC
            )
        finally:
            if original is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = original
            tzset()


class TestNoLocalClockInSource:
    def test_filters_source_does_not_read_local_clock(self) -> None:
        """北京时间语义必须来自固定 BJT 偏移，禁止 datetime.now()/date.today() 等本地时钟。

        本断言是「不受进程本地时区影响」的可执行形式：AST 扫描 filters.py，
        任何本地时钟读取（含无参 astimezone()、无 tz 的 fromtimestamp()）都会失败。
        """
        tree = ast.parse(_module_source())
        offenders: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _called_name(node)
            if name in {"now", "today", "localtime", "mktime"}:
                offenders.append(name)
            elif name == "astimezone" and not node.args and not node.keywords:
                offenders.append("astimezone()")
            elif name == "fromtimestamp" and len(node.args) < 2 and not node.keywords:
                offenders.append("fromtimestamp()")
        assert offenders == []
