"""Ticket 03 / 09：消防报警直读读取器窗口与裁剪单测。

票据 09 起取数方式改为「按报警时间倒序分页 + 见到早于窗口起点的记录即提前终止」，
不再按北京时间自然日逐次查询；因此替身从 domain 级 list_all_records 下沉为
page 级 search_records，窗口正确性由「倒序 + 应用侧裁剪」共同保证。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest

from app.modules.safety.feishu.bitable_client import (
    BitableQueryError as ClientQueryError,
)
from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.bitable_direct.errors import (
    BitableConfigError,
    BitableQueryError,
)
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
    """假 page 级 client：一次性返回受控记录（必须按报警时间倒序，与真实 API 一致）。"""

    def __init__(
        self, records: list[dict[str, Any]], error: Exception | None = None
    ) -> None:
        self.records = list(records)
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def search_records(
        self,
        table_id: str | None = None,
        *,
        filter_info: dict[str, Any] | None = None,
        field_names: list[str] | None = None,
        sort: list[dict[str, Any]] | None = None,
        automatic_fields: bool = False,
        page_size: int = 200,
        page_token: str | None = None,
        strict: bool = True,
    ) -> dict[str, Any]:
        self.calls.append({
            "table_id": table_id,
            "filter_info": filter_info,
            "field_names": field_names,
            "sort": sort,
            "automatic_fields": automatic_fields,
            "page_size": page_size,
            "page_token": page_token,
            "strict": strict,
        })
        if self.error is not None:
            raise self.error
        if page_token is not None:  # 第二页起为空，保证终止
            return {"items": [], "has_more": False, "page_token": None, "total": 0}
        return {
            "items": list(self.records),
            "has_more": False,
            "page_token": None,
            "total": len(self.records),
        }


def _assert_window_query(call: dict[str, Any]) -> None:
    """窗口查询判据：按报警时间倒序、不携带日期过滤条件（提前终止的前提）。"""
    assert call["sort"] == [{"field_name": "报警时间", "desc": True}]
    assert call["filter_info"] is None
    assert call["strict"] is True


async def test_day_window_keeps_only_records_inside_bjt_day() -> None:
    start = datetime(2026, 9, 11, 0, 0, tzinfo=BJT)
    records = [  # 倒序
        _record("rec-end", start + timedelta(days=1)),
        _record("rec-inside", start + timedelta(hours=12)),
        _record("rec-start", start),
        _record("rec-before", start - timedelta(seconds=1)),
        _record("rec-none", None),
    ]
    fake = FakePageReader(records)
    dr = reader.FireAlarmBitableReader(fake, page_size=500)

    views = await dr.get_records_by_date(TARGET_DATE)

    assert [v.id for v in views] == ["rec-inside", "rec-start"]
    assert len(fake.calls) == 1
    _assert_window_query(fake.calls[0])
    assert fake.calls[0]["field_names"] is not None
    assert "AI维度" in fake.calls[0]["field_names"]


async def test_rolling_window_trims_exact_boundaries() -> None:
    start = datetime(2026, 9, 10, 17, 0, tzinfo=BJT)
    end = datetime(2026, 9, 11, 17, 0, tzinfo=BJT)
    records = [
        _record("rec-after", end + timedelta(seconds=1)),
        _record("rec-end", end),
        _record("rec-inside", start + timedelta(hours=20)),
        _record("rec-start", start),
        _record("rec-before", start - timedelta(seconds=1)),
    ]
    fake = FakePageReader(records)
    dr = reader.FireAlarmBitableReader(fake, page_size=500)

    views, utc_start, utc_end = await dr.get_records_by_rolling_window(TARGET_DATE)

    assert [v.id for v in views] == ["rec-inside", "rec-start"]
    assert utc_start == start.astimezone(UTC)
    assert utc_end == end.astimezone(UTC)
    assert len(fake.calls) == 1  # 票据 09：滚动窗口从 2 次按天查询降为 1 次
    _assert_window_query(fake.calls[0])


async def test_week_window_trims_exact_boundaries() -> None:
    start = datetime(2026, 9, 7, 0, 0, tzinfo=BJT)
    end = datetime(2026, 9, 14, 0, 0, tzinfo=BJT)
    records = [
        _record("rec-end", end),
        _record("rec-inside", start + timedelta(days=3)),
        _record("rec-start", start),
        _record("rec-before", start - timedelta(seconds=1)),
    ]
    fake = FakePageReader(records)
    dr = reader.FireAlarmBitableReader(fake, page_size=500)

    views = await dr.get_records_by_week(WEEK_START, WEEK_END)

    assert [v.id for v in views] == ["rec-inside", "rec-start"]
    assert len(fake.calls) == 1  # 票据 09：周窗口从 7 次按天查询降为 1 次
    _assert_window_query(fake.calls[0])


async def test_empty_window_returns_empty_without_error() -> None:
    fake = FakePageReader([])
    dr = reader.FireAlarmBitableReader(fake)

    assert await dr.get_records_by_date(TARGET_DATE) == []


async def test_records_without_time_are_dropped() -> None:
    fake = FakePageReader([_record("rec-none", None)])
    dr = reader.FireAlarmBitableReader(fake)

    assert await dr.get_records_by_date(TARGET_DATE) == []


async def test_client_error_is_wrapped_into_base_error() -> None:
    # 客户端异常（code+msg 两参数）由底座统一翻译成底座 BitableQueryError
    fake = FakePageReader(
        [], error=ClientQueryError(1254001, "table not found")
    )
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
