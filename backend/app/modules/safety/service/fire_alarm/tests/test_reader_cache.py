"""消防报警窗口 TTL 缓存包装单测（CachedFireAlarmReader，注入替身零真机依赖）。

背景：无缓存时总览驾驶舱每次刷新都实打 Bitable 实测 ~5s（2026-10-14）。
覆盖：同窗口命中只拉一次 / strict 绕过且不回填 / TTL=0 直通 /
滚动窗口 UTC 元组形状透传 / TTL 默认值。
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.modules.safety.service.fire_alarm import config, reader


class _StubInner:
    """替身：记录 get_records_by_range 调用并返回预置视图。"""

    def __init__(self, views: list[reader.FireAlarmView] | None = None) -> None:
        self.calls: list[tuple[datetime, datetime]] = []
        self._views = views if views is not None else []

    async def get_records_by_range(
        self, start: datetime, end: datetime,
    ) -> list[reader.FireAlarmView]:
        self.calls.append((start, end))
        return list(self._views)

    async def count_all(self) -> int:
        return 0


def _view(vid: str) -> reader.FireAlarmView:
    return reader.FireAlarmView(id=vid)


async def test_same_window_hits_cache_once() -> None:
    inner = _StubInner([_view("r1")])
    cached = reader.CachedFireAlarmReader(inner, ttl_seconds=300)
    first = await cached.get_records_by_date(date(2026, 9, 11))
    second = await cached.get_records_by_date(date(2026, 9, 11))
    assert [v.id for v in first] == ["r1"]
    assert [v.id for v in second] == ["r1"]
    assert len(inner.calls) == 1  # TTL 窗口内只拉一次


async def test_strict_bypasses_and_does_not_backfill() -> None:
    inner = _StubInner([_view("r1")])
    cached = reader.CachedFireAlarmReader(inner, ttl_seconds=300)
    week = (date(2026, 9, 7), date(2026, 9, 13))
    await cached.get_records_by_week(*week, strict=True)
    await cached.get_records_by_week(*week, strict=True)
    assert len(inner.calls) == 2  # strict（日报/月报编排）每次现拉
    await cached.get_records_by_week(*week)
    assert len(inner.calls) == 3  # strict 结果不回填，查询面首次仍现拉
    await cached.get_records_by_week(*week)
    assert len(inner.calls) == 3  # 查询面第二次命中缓存


async def test_ttl_zero_disables_cache() -> None:
    inner = _StubInner([_view("r1")])
    cached = reader.CachedFireAlarmReader(inner, ttl_seconds=0)
    start = datetime(2026, 9, 10, 16, tzinfo=UTC)
    end = datetime(2026, 9, 11, 16, tzinfo=UTC)
    for _ in range(3):
        await cached.get_records_by_range(start, end)
    assert len(inner.calls) == 3


async def test_rolling_window_returns_utc_bounds() -> None:
    cached = reader.CachedFireAlarmReader(_StubInner([_view("r1")]), ttl_seconds=300)
    views, start_utc, end_utc = await cached.get_records_by_rolling_window(
        date(2026, 9, 11)
    )
    assert [v.id for v in views] == ["r1"]
    # 前日/当日北京时间 17:00 = UTC 09:00
    assert start_utc == datetime(2026, 9, 10, 9, tzinfo=UTC)
    assert end_utc == datetime(2026, 9, 11, 9, tzinfo=UTC)


def test_protocol_conformance() -> None:
    assert isinstance(
        reader.CachedFireAlarmReader(_StubInner(), ttl_seconds=300),
        reader.FireAlarmRecordsReader,
    )


def test_cache_ttl_default_300(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAFETY_FIRE_ALARM_DIRECT_CACHE_TTL_SECONDS", raising=False)
    assert config.cache_ttl_seconds() == 300
