"""special_op_direct.query 单测（Ticket 07 验收）。

覆盖：筛选条件下推 Bitable（扁平 AND + 分支并集）、无日期窗口退化为单查询、
      风险等级读列/现场判定（不回写）、关键词与部门子串在应用侧、
      分页与倒序、多选项枚举不下推、接口报错向上抛。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.modules.safety.feishu.bitable_client import BitableQueryError
from app.modules.safety.service.special_op_direct import contract, query
from app.modules.safety.service.special_op_direct.tests.factories import (
    HIGH_FIELDS,
    LOW_FIELDS,
    MEDIUM_FIELDS,
    FakeReader,
    ms,
    record,
)

DAY_START = datetime(2026, 9, 11, 0, 30, tzinfo=UTC)
DAY = "2026-09-11"
RISK_FIELD = contract.RISK_FIELD_NAME


def _conditions(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [c for call in calls for c in (call["filter_info"] or {}).get("conditions", [])]


def _bjt_midnight_ms(iso_date: str) -> int:
    from datetime import date as _date
    from datetime import timezone

    d = _date.fromisoformat(iso_date)
    return int(
        datetime(d.year, d.month, d.day, tzinfo=timezone(timedelta(hours=8))).timestamp() * 1000
    )


def _pairs(calls: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [(c["field_name"], c["operator"]) for c in _conditions(calls)]


# 下推：扁平 AND


async def test_single_flat_query_pushes_down_enums_and_date_window() -> None:
    reader = FakeReader(records=[])
    from datetime import date

    await query.query_records(
        date_from=date.fromisoformat(DAY),
        date_to=date.fromisoformat(DAY),
        operation_type="confined_space",
        operation_level="grade1",
        report_type="unplanned",
        client=reader,
    )

    assert len(reader.calls) == 1
    conditions = reader.calls[0]["filter_info"]["conditions"]
    assert [(c["field_name"], c["operator"]) for c in conditions] == [
        ("作业时间_开始时间", "isGreater"),
        ("作业时间_开始时间", "isLess"),
        ("作业类型", "is"),
        ("作业分级", "is"),
        ("报备类型", "is"),
    ]
    assert conditions[0]["value"] == ["ExactDate", str(int(_bjt_midnight_ms(DAY)))]
    assert conditions[1]["value"] == ["ExactDate", str(int(_bjt_midnight_ms(DAY) + 86400000))]
    by_field = {c["field_name"]: c for c in conditions[2:]}
    assert by_field["作业类型"]["value"] == ["受限空间"]
    assert by_field["作业分级"]["value"] == ["一级（Ⅰ级）"]
    assert by_field["报备类型"]["value"] == ["计划外作业"]
    assert reader.calls[0]["strict"] is True


async def test_multi_option_enum_is_not_pushed_down_but_filtered_side() -> None:
    reader = FakeReader(records=[
        record("rec-hot", **HIGH_FIELDS),   # 动火作业 -> hot_work
        record("rec-low", **LOW_FIELDS),    # 临时用电
    ])

    res = await query.query_records(operation_type="hot_work", client=reader)

    assert [c["field_name"] for c in _conditions(reader.calls)] == []
    assert reader.calls[0]["filter_info"] is None  # 无条件 -> 不加 filter
    assert res["total"] == 1
    assert res["items"][0]["operation_type"] == "hot_work"


# 下推：分支并集


async def test_department_and_risk_use_branch_union() -> None:
    reader = FakeReader(records=[])

    await query.query_records(
        date_from=datetime(2026, 9, 11).date(),
        date_to=datetime(2026, 9, 11).date(),
        department="提炼工程五部",
        daily_risk_level="high",
        client=reader,
    )

    # 部门 2 分支 x 风险 2 分支 = 4 条 flat-AND 查询（每条 = 日期 + 1 部门分支 + 1 风险分支）
    assert len(reader.calls) == 4
    branch_pairs = [
        pair for pair in _pairs(reader.calls) if pair[0] != "作业时间_开始时间"
    ]
    assert sorted(branch_pairs) == sorted([
        ("发起人部门", "contains"), ("发起人部门", "contains"),
        ("申请部门", "is"), ("申请部门", "is"),
        (RISK_FIELD, "is"), (RISK_FIELD, "is"),
        (RISK_FIELD, "isEmpty"), (RISK_FIELD, "isEmpty"),
    ])
    risk_values = [
        c["value"] for c in _conditions(reader.calls)
        if c["field_name"] == RISK_FIELD and c["operator"] == "is"
    ]
    assert risk_values == [["高风险"], ["高风险"]]


async def test_no_date_window_uses_single_query_and_filters_side() -> None:
    reader = FakeReader(records=[
        record("rec-a", **HIGH_FIELDS),
        record("rec-low", **LOW_FIELDS),
    ])

    res = await query.query_records(
        department="生产", daily_risk_level="high", client=reader
    )

    assert len(reader.calls) == 1  # 无日期窗口 -> 不做分支下推
    assert reader.calls[0]["filter_info"] is None
    assert res["total"] == 1
    assert res["items"][0]["daily_risk_level"] == "high"


# 风险等级：读列 vs 现场判定


async def test_risk_level_reads_column_when_present_else_computes() -> None:
    stored = record("rec-stored", **HIGH_FIELDS)
    stored["fields"][RISK_FIELD] = "中风险"
    computed = record("rec-computed", **HIGH_FIELDS)  # 罐区动火 -> high
    reader = FakeReader(records=[stored, computed])

    res = await query.query_records(client=reader)

    by_level = {i["daily_risk_level"]: i for i in res["items"]}
    assert sorted(by_level) == ["high", "medium"]
    assert by_level["medium"]["daily_risk_reason"] is None  # 读列，无理由
    assert by_level["high"]["daily_risk_reason"]  # 现场判定带理由
    # 只读：替身 reader 只有 list_all_records（结构上无法回写）
    assert not hasattr(reader, "update_record")


# 应用侧过滤


async def test_keyword_and_department_are_matched_side() -> None:
    rec_a = record("rec-a", **HIGH_FIELDS)  # 内容 管道焊接 / 地点 罐区
    rec_b = record("rec-b", **LOW_FIELDS)   # 内容 更换照明灯具 / 地点 车间
    rec_b["fields"]["申请编号"] = {"link": "https://x.feishu.cn/PR-2026-001"}
    reader = FakeReader(records=[rec_a, rec_b])

    assert (await query.query_records(keyword="照明", client=reader))["total"] == 1
    assert (await query.query_records(keyword="车间", client=reader))["total"] == 1
    assert (await query.query_records(keyword="PR-2026", client=reader))["total"] == 1
    assert (await query.query_records(keyword="不存在的词", client=reader))["total"] == 0
    assert (await query.query_records(department="生产", client=reader))["total"] == 2
    assert (await query.query_records(department="五部", client=reader))["total"] == 0


# 分页与排序


async def test_paging_and_desc_ordering() -> None:
    reader = FakeReader(records=[
        record("rec-early", **MEDIUM_FIELDS,
               **{"作业时间_开始时间": ms(datetime(2026, 9, 11, 0, 30, tzinfo=UTC))}),
        record("rec-mid", **MEDIUM_FIELDS,
               **{"作业时间_开始时间": ms(datetime(2026, 9, 11, 2, 0, tzinfo=UTC))}),
        record("rec-late", **MEDIUM_FIELDS,
               **{"作业时间_开始时间": ms(datetime(2026, 9, 11, 4, 0, tzinfo=UTC))}),
    ])

    page1 = await query.query_records(page=1, page_size=2, client=reader)
    assert page1["total"] == 3
    assert page1["page"] == 1 and page1["page_size"] == 2
    starts = [i["planned_start_time"] for i in page1["items"]]
    assert starts == sorted(starts, reverse=True)

    page2 = await query.query_records(page=2, page_size=2, client=reader)
    assert page2["total"] == 3
    assert len(page2["items"]) == 1

    capped = await query.query_records(page=0, page_size=500, client=reader)
    assert capped["page"] == 1
    assert capped["page_size"] == query.MAX_PAGE_SIZE


async def test_item_fields_match_legacy_tool() -> None:
    reader = FakeReader(records=[record("rec-a", **HIGH_FIELDS)])

    item = (await query.query_records(client=reader))["items"][0]

    assert sorted(item) == sorted([
        "report_no", "department", "initiator_department", "operation_type",
        "operation_level", "daily_risk_level", "daily_risk_reason", "report_type",
        "work_description", "location", "planned_start_time", "planned_end_time",
        "work_duration_hours", "personnel_type", "approval_no", "approver_name",
        "is_excluded", "exclusion_reason",
    ])


# 报错


async def test_api_error_propagates() -> None:
    reader = FakeReader(error=BitableQueryError(1254001, "table not found"))

    with pytest.raises(BitableQueryError):
        await query.query_records(client=reader)
