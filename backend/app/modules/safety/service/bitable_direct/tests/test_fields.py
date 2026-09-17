"""底座字段取值单测（纯函数，无替身、无 IO）。

统一口径（两个旧包的分歧在此收敛）：
1. 文本支持三种输入：富文本数组、裸字符串、formula 包装 {"type":1,"value":[...]}
2. 空值统一返回 None（域包若需要空字符串，自行 ``or ""`` 包装）
3. 毫秒 0 与负数视为缺失（返回 None），不产出 1970
4. 多选同时提供"原样列表"与"拼接文本"两种出口，拼接符由调用方决定
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from app.modules.safety.service.bitable_direct import fields

#  富文本


class TestRichText:
    def test_plain_string(self) -> None:
        assert fields.rich_text("合成") == "合成"

    def test_rich_text_list_is_joined(self) -> None:
        value = [{"type": "text", "text": "合成", "style": {}}, {"type": "text", "text": "车间"}]
        assert fields.rich_text(value) == "合成车间"

    def test_list_with_plain_items(self) -> None:
        assert fields.rich_text(["A", "", "B"]) == "AB"

    def test_formula_dict_wrapper(self) -> None:
        """公式字段返回 {"type":1,"value":[...]}，必须解包（旧隐患实现会得到字典字符串）。"""
        value = {"type": 1, "value": [{"text": "提炼工程四部"}]}
        assert fields.rich_text(value) == "提炼工程四部"

    def test_nested_dict_wrapper_with_plain_value(self) -> None:
        assert fields.rich_text({"type": 1, "value": "纯文本"}) == "纯文本"

    def test_plain_dict_without_value_key(self) -> None:
        """没有 value 键的字典按文本结构处理，不返回字典的 repr。"""
        assert fields.rich_text({"text": "张三"}) == "张三"

    @pytest.mark.parametrize("value", [None, "", 0, False, [], {}])
    def test_empty_inputs_return_empty_string(self, value: Any) -> None:
        assert fields.rich_text(value) == ""

    def test_number_is_stringified(self) -> None:
        assert fields.rich_text(3) == "3"


#  单选 / 多选


class TestSelectValues:
    def test_single_select_string(self) -> None:
        assert fields.select_values("已关闭") == ["已关闭"]

    def test_multi_select_list(self) -> None:
        assert fields.select_values(["集团EHS审计", "政府安全检查"]) == [
            "集团EHS审计",
            "政府安全检查",
        ]

    def test_empty_items_are_dropped(self) -> None:
        assert fields.select_values(["A", "", None, "B"]) == ["A", "B"]

    @pytest.mark.parametrize("value", [None, "", [], 0])
    def test_empty_inputs_return_empty_list(self, value: Any) -> None:
        assert fields.select_values(value) == []


#  人员


class TestPersonInfo:
    def test_legacy_list_format(self) -> None:
        value = [{"id": "ou_1", "name": "张三", "email": "z@example.com"}]
        info = fields.person_info(value)
        assert info["name"] == "张三"
        assert info["id"] == "ou_1"
        assert info["email"] == "z@example.com"

    def test_new_users_format(self) -> None:
        value = {"users": [{"userId": "7307", "name": "李四"}]}
        info = fields.person_info(value)
        assert info["name"] == "李四"
        assert info["id"] == "7307"

    @pytest.mark.parametrize("value", [None, "", [], {"users": []}])
    def test_empty_inputs_return_blank(self, value: Any) -> None:
        info = fields.person_info(value)
        assert info == {"name": "", "id": "", "email": ""}

    def test_name_falls_back_to_id(self) -> None:
        assert fields.person_name([{"id": "ou_9"}]) == "ou_9"


#  时间


class TestMillisToUtc:
    def test_int_millis(self) -> None:
        ms = int(datetime(2026, 9, 11, 0, 30, tzinfo=UTC).timestamp() * 1000)
        assert fields.ms_to_utc(ms) == datetime(2026, 9, 11, 0, 30, tzinfo=UTC)

    def test_numeric_string(self) -> None:
        ms = int(datetime(2026, 9, 11, 0, 30, tzinfo=UTC).timestamp() * 1000)
        assert fields.ms_to_utc(str(ms)) == datetime(2026, 9, 11, 0, 30, tzinfo=UTC)

    def test_result_is_utc_aware(self) -> None:
        ms = int(datetime(2026, 9, 11, 0, 30, tzinfo=UTC).timestamp() * 1000)
        result = fields.ms_to_utc(ms)
        assert result is not None
        assert result.tzinfo is UTC

    @pytest.mark.parametrize("value", [None, "", "abc", 0, -1, -1000, [], {}])
    def test_missing_or_invalid_returns_none(self, value: Any) -> None:
        """毫秒 0 与负数按缺失处理（不产出 1970）。"""
        assert fields.ms_to_utc(value) is None


class TestUtcHelpers:
    def test_to_utc_converts_aware_to_utc_instant(self) -> None:
        aware = datetime(2026, 9, 11, 8, 30, tzinfo=timezone(timedelta(hours=8)))
        assert fields.to_utc(aware) == datetime(2026, 9, 11, 0, 30, tzinfo=UTC)

    def test_to_utc_returns_none_for_none(self) -> None:
        assert fields.to_utc(None) is None

    def test_to_utc_naive_is_interpreted_in_process_local_clock(self) -> None:
        """naive 值按"本地时钟取同一瞬时"归一（与既有 to_utc 约定一致）。"""
        naive = datetime(2026, 9, 11, 8, 30)
        result = fields.to_utc(naive)
        assert result is not None
        assert result.tzinfo is UTC
        assert result == naive.astimezone(UTC)

    def test_utc_to_ms_roundtrip(self) -> None:
        moment = datetime(2026, 9, 11, 0, 30, 15, tzinfo=UTC)
        assert fields.ms_to_utc(fields.utc_to_ms(moment)) == moment

    def test_utc_to_ms_returns_int(self) -> None:
        moment = datetime(2026, 9, 11, 0, 30, tzinfo=UTC)
        assert isinstance(fields.utc_to_ms(moment), int)

    def test_utc_to_ms_treats_naive_as_local(self) -> None:
        naive = datetime(2026, 9, 11, 8, 30)
        assert fields.utc_to_ms(naive) == int(naive.timestamp() * 1000)


#  附件


class TestAttachments:
    def test_filters_items_without_file_token(self) -> None:
        value = [
            {"file_token": "tok1", "name": "a.png"},
            {"name": "no-token.png"},
            "garbage",
        ]
        assert fields.attachment_list(value) == [{"file_token": "tok1", "name": "a.png"}]

    @pytest.mark.parametrize("value", [None, "", [], {}, "str"])
    def test_non_list_returns_empty(self, value: Any) -> None:
        assert fields.attachment_list(value) == []

#  字段级便捷取值（空值统一 None 约定）


class TestFieldGetters:
    def test_text_reads_wrapped_field(self) -> None:
        row = {"施工单位": {"type": 1, "value": [{"text": "某某建设"}]}}
        assert fields.text(row, "施工单位") == "某某建设"

    def test_text_strips_whitespace(self) -> None:
        row = {"名称": [{"text": "  合成  "}]}
        assert fields.text(row, "名称") == "合成"

    @pytest.mark.parametrize("row", [{}, {"名称": None}, {"名称": ""}, {"名称": []}])
    def test_text_returns_none_when_absent_or_empty(self, row: dict[str, Any]) -> None:
        assert fields.text(row, "名称") is None

    def test_select_joins_with_default_separator(self) -> None:
        row = {"检查类别": ["集团EHS审计", "政府安全检查"]}
        assert fields.select(row, "检查类别") == "集团EHS审计, 政府安全检查"

    def test_select_supports_custom_separator(self) -> None:
        row = {"动火作业方式": ["电焊", "氩弧焊"]}
        assert fields.select(row, "动火作业方式", joiner="、") == "电焊、氩弧焊"

    def test_select_returns_none_when_empty(self) -> None:
        assert fields.select({}, "检查类别") is None
        assert fields.select({"检查类别": []}, "检查类别") is None

    def test_multi_returns_raw_list(self) -> None:
        row = {"动火作业方式": ["电焊", "氩弧焊"]}
        assert fields.multi(row, "动火作业方式") == ["电焊", "氩弧焊"]

    def test_multi_returns_empty_list_when_absent(self) -> None:
        assert fields.multi({}, "动火作业方式") == []

    def test_person_returns_name(self) -> None:
        row = {"检查人员": [{"id": "ou_1", "name": "张三"}]}
        assert fields.person(row, "检查人员") == "张三"

    def test_person_returns_none_when_absent(self) -> None:
        assert fields.person({}, "检查人员") is None

    def test_datetime_ms_parses_timestamp(self) -> None:
        ms = int(datetime(2026, 9, 11, 0, 30, tzinfo=UTC).timestamp() * 1000)
        assert fields.datetime_ms({"报警时间": ms}, "报警时间") == datetime(
            2026, 9, 11, 0, 30, tzinfo=UTC
        )

    def test_datetime_ms_returns_none_when_absent(self) -> None:
        assert fields.datetime_ms({}, "报警时间") is None

    def test_attachments_returns_list(self) -> None:
        row = {"缺陷图片": [{"file_token": "tok1"}]}
        assert fields.attachments(row, "缺陷图片") == [{"file_token": "tok1"}]

    def test_attachments_returns_empty_list_when_absent(self) -> None:
        assert fields.attachments({}, "缺陷图片") == []
