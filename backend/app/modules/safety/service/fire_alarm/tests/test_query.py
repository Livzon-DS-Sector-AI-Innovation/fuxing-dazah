"""Ticket 07：消防 Agent 直读查询单测。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.modules.safety.service.fire_alarm import query

DAY = date(2026, 9, 17)


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _record(
    record_id: str,
    *,
    moment: datetime | None = None,
    department: str = "动力车间",
    alarm_type: str = "火灾报警",
    alarm_nature: str = "误报",
    dimension: str = "设备设施",
    location: str = "压缩机房",
    cause: str = "传感器老化",
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "报警部门负责人.部门": [department],
        "报警类型": alarm_type,
        "报警性质": alarm_nature,
        "报警部位": location,
        "具体报警原因": cause,
        "AI维度": dimension,
    }
    if moment is not None:
        fields["报警时间"] = _ms(moment)
    return {"record_id": record_id, "fields": fields}


class FakeQueryReader:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = records
        self.calls: list[dict[str, Any]] = []

    async def list_all_records(
        self,
        table_id: str | None = None,
        *,
        filter_info: dict[str, Any] | None = None,
        field_names: list[str] | None = None,
        sort: list[dict[str, Any]] | None = None,
        automatic_fields: bool = False,
        page_size: int = 200,
        strict: bool = False,
    ) -> list[dict[str, Any]]:
        self.calls.append({"filter_info": filter_info, "field_names": field_names})
        return list(self.records)


def _conditions(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        cond
        for call in calls
        for cond in (call["filter_info"] or {}).get("conditions", [])
    ]


async def test_query_pushes_filters_and_applies_keyword_pagination() -> None:
    start = datetime(2026, 9, 17, 0, 0, tzinfo=UTC)
    reader = FakeQueryReader([
        _record("rec-a", moment=start + timedelta(hours=2), dimension="设备设施"),
        _record("rec-b", moment=start + timedelta(hours=3), location="车间", cause="照明"),
        _record("rec-c", moment=start + timedelta(hours=4), alarm_type="故障报警"),
    ])

    result = await query.query_fire_alarms_direct(
        date_from=DAY,
        date_to=DAY,
        department="动力车间",
        alarm_type="火灾报警",
        alarm_nature="误报",
        ai_dimension="equipment",
        keyword="压缩",
        page=1,
        page_size=1,
        client=reader,
    )

    assert result["success"] is True
    assert result["total"] == 1
    assert result["items"][0]["id"] == "rec-a"
    assert result["window"] == {"date_from": "2026-09-17", "date_to": "2026-09-17"}
    assert len(reader.calls) == 1
    fields = {c["field_name"] for c in _conditions(reader.calls)}
    # 部门不下推（多选字段不支持 contains），因此条件里不含部门字段
    assert fields == {"报警时间", "报警类型", "报警性质", "AI维度"}
    assert "AI维度" in reader.calls[0]["field_names"]


async def test_query_default_window_is_recent_30_days() -> None:
    reader = FakeQueryReader([])
    result = await query.query_fire_alarms_direct(client=reader)

    today = (datetime.now(UTC) + timedelta(hours=8)).date()
    assert result["window"]["date_from"] == (
        today - timedelta(days=query.DEFAULT_QUERY_DAYS - 1)
    ).isoformat()
    assert result["window"]["date_to"] == today.isoformat()
    assert len(reader.calls) == query.DEFAULT_QUERY_DAYS


async def test_query_range_over_limit_returns_error() -> None:
    reader = FakeQueryReader([])
    result = await query.query_fire_alarms_direct(
        date_from=date(2026, 9, 1),
        date_to=date(2026, 10, 2),
        client=reader,
    )

    assert result["success"] is False
    assert "超过上限" in result["error"]
    assert reader.calls == []


async def test_department_is_not_pushed_down_and_matches_substring() -> None:
    """回归（票据 08 真机实测）：部门是多选字段，不支持 contains 下推。

    下推会得到 code=1254018 InvalidFilter；改用 is 精确匹配又会漏掉「五部」
    这类部分部门名。因此部门只在应用侧做子串匹配。
    """
    start = datetime(2026, 9, 17, 0, 0, tzinfo=UTC)
    reader = FakeQueryReader([
        _record("rec-a", moment=start + timedelta(hours=2), department="提炼工程五部"),
        _record("rec-b", moment=start + timedelta(hours=3), department="动力车间"),
    ])

    result = await query.query_fire_alarms_direct(
        date_from=DAY, date_to=DAY, department="五部", client=reader,
    )

    assert result["success"] is True
    assert result["total"] == 1
    assert result["items"][0]["id"] == "rec-a"
    pushed = {cond["field_name"] for cond in _conditions(reader.calls)}
    assert "报警部门负责人.部门" not in pushed
    assert pushed == {"报警时间"}

async def test_query_empty_window_returns_empty() -> None:
    result = await query.query_fire_alarms_direct(
        date_from=DAY, date_to=DAY, client=FakeQueryReader([])
    )
    assert result["success"] is True
    assert result["total"] == 0
    assert result["items"] == []
