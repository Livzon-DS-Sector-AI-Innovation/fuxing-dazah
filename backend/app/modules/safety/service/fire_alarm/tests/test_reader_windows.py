"""Ticket 03：消防报警直读读取器窗口与裁剪单测。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest

from app.modules.safety.feishu.bitable_client import BitableQueryError
from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.bitable_direct.errors import BitableConfigError
from app.modules.safety.service.fire_alarm import reader

BJT = timezone(timedelta(hours=8))
TARGET_DATE = date(2026, 9, 11)
WEEK_START = date(2026, 9, 7)
WEEK_END = date(2026, 9, 13)


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _record(record_id: str, moment: datetime | None) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if moment is not None:
        fields["报警时间"] = _ms(moment)
    return {"record_id": record_id, "fields": fields}


class FakePageReader:
    """按天查询替身：记录每次请求，返回受控记录集合。"""

    def __init__(self, records: list[dict[str, Any]], error: Exception | None = None) -> None:
        self.records = records
        self.error = error
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
        self.calls.append({
            "table_id": table_id,
            "filter_info": filter_info,
            "field_names": field_names,
            "sort": sort,
            "automatic_fields": automatic_fields,
            "page_size": page_size,
            "strict": strict,
        })
        if self.error is not None:
            raise self.error
        return list(self.records)


def _assert_day_filter(call: dict[str, Any]) -> None:
    filter_info = call["filter_info"]
    assert filter_info["conjunction"] == "and"
    conditions = filter_info["conditions"]
    assert [c["field_name"] for c in conditions] == ["报警时间", "报警时间"]
    assert [c["operator"] for c in conditions] == ["isGreater", "isLess"]
    assert all(c["value"][0] == "ExactDate" for c in conditions)


async def test_day_window_keeps_only_records_inside_bjt_day() -> None:
    start = datetime(2026, 9, 11, 0, 0, tzinfo=BJT)
    records = [
        _record("rec-before", start - timedelta(seconds=1)),
        _record("rec-start", start),
        _record("rec-inside", start + timedelta(hours=12)),
        _record("rec-end", start + timedelta(days=1)),
        _record("rec-none", None),
    ]
    fake = FakePageReader(records)
    dr = reader.FireAlarmBitableReader(fake, page_size=500)

    views = await dr.get_records_by_date(TARGET_DATE)

    assert [v.id for v in views] == ["rec-start", "rec-inside"]
    assert len(fake.calls) == 1
    _assert_day_filter(fake.calls[0])
    assert fake.calls[0]["field_names"] is not None
    assert "AI维度" in fake.calls[0]["field_names"]
    assert fake.calls[0]["strict"] is True


async def test_rolling_window_uses_two_days_and_trims_exact_boundaries() -> None:
    start = datetime(2026, 9, 10, 17, 0, tzinfo=BJT)
    end = datetime(2026, 9, 11, 17, 0, tzinfo=BJT)
    records = [
        _record("rec-before", start - timedelta(seconds=1)),
        _record("rec-start", start),
        _record("rec-inside", start + timedelta(hours=20)),
        _record("rec-end", end),
        _record("rec-after", end + timedelta(seconds=1)),
    ]
    fake = FakePageReader(records)
    dr = reader.FireAlarmBitableReader(fake, page_size=500)

    views, utc_start, utc_end = await dr.get_records_by_rolling_window(TARGET_DATE)

    assert [v.id for v in views] == ["rec-start", "rec-inside"]
    assert utc_start == start.astimezone(UTC)
    assert utc_end == end.astimezone(UTC)
    assert len(fake.calls) == 2
    for call in fake.calls:
        _assert_day_filter(call)


async def test_week_window_uses_seven_days_and_trims_exact_boundaries() -> None:
    start = datetime(2026, 9, 7, 0, 0, tzinfo=BJT)
    end = datetime(2026, 9, 14, 0, 0, tzinfo=BJT)
    records = [
        _record("rec-before", start - timedelta(seconds=1)),
        _record("rec-start", start),
        _record("rec-inside", start + timedelta(days=3)),
        _record("rec-end", end),
    ]
    fake = FakePageReader(records)
    dr = reader.FireAlarmBitableReader(fake, page_size=500)

    views = await dr.get_records_by_week(WEEK_START, WEEK_END)

    assert [v.id for v in views] == ["rec-start", "rec-inside"]
    assert len(fake.calls) == 7
    for call in fake.calls:
        _assert_day_filter(call)


async def test_empty_window_returns_empty_without_error() -> None:
    fake = FakePageReader([])
    dr = reader.FireAlarmBitableReader(fake)

    assert await dr.get_records_by_date(TARGET_DATE) == []


async def test_api_error_propagates() -> None:
    fake = FakePageReader([], error=BitableQueryError(1254001, "table not found"))
    dr = reader.FireAlarmBitableReader(fake)

    with pytest.raises(BitableQueryError):
        await dr.get_records_by_date(TARGET_DATE)


def test_open_reader_raises_when_connection_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_resolve(*args: Any, **kwargs: Any) -> Any:
        raise BitableConfigError("fire_alarm/alarm missing")

    monkeypatch.setattr(bd_reader, "resolve_client", fake_resolve)

    with pytest.raises(BitableConfigError):
        reader.open_reader()
