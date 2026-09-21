"""Ticket 03：日报直读编排单测（注入替身 reader / analyst，零真机、零 DB 写）。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import pytest

from app.modules.safety.service.central_alarm import reader as ca_reader
from app.modules.safety.service.central_alarm.reader import CentralAlarmView
from app.modules.safety.service.central_alarm.service import CentralAlarmService

_BJ = timedelta(hours=8)


class FakeReader:
    """替身：预置窗口数据，记录调用。"""

    def __init__(self, views: list[CentralAlarmView]) -> None:
        self._views = views
        self.calls: list[str] = []

    async def fetch_window_records(
        self, *, start_utc: datetime, end_utc: datetime, strict: bool = False,
    ) -> list[CentralAlarmView]:
        self.calls.append(f"window:{start_utc.isoformat()}~{end_utc.isoformat()}")
        return [v for v in self._views if v.alarm_date and start_utc <= v.alarm_date < end_utc]

    async def get_records_by_date(
        self, target_date: date, *, strict: bool = False,
    ) -> list[CentralAlarmView]:
        self.calls.append(f"date:{target_date.isoformat()}")
        start, end = ca_reader.day_window(target_date)
        return await self.fetch_window_records(start_utc=start, end_utc=end)

    async def get_records_by_rolling_window(
        self, target_date: date, *, strict: bool = False,
    ) -> tuple[list[CentralAlarmView], datetime, datetime]:
        self.calls.append(f"rolling:{target_date.isoformat()}")
        start, end = ca_reader.rolling_window(target_date)
        views = await self.fetch_window_records(start_utc=start, end_utc=end)
        return views, start, end

    async def get_records_by_week(
        self, week_start: date, week_end: date, *, strict: bool = False,
    ) -> list[CentralAlarmView]:
        self.calls.append(f"week:{week_start.isoformat()}")
        start, end = ca_reader.week_window(week_start, week_end)
        return await self.fetch_window_records(start_utc=start, end_utc=end)


class FakeAnalyst:
    """替身：不调 AI，直接返回固定分析。"""

    def __init__(self) -> None:
        self.history_index: Any = None
        self.analyzed: list[str] = []

    async def analyze_per_records(
        self, records: Any, *, channel: str = "system",
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for r in records:
            self.analyzed.append(r.id)
            r.ai_alarm_type = "高高压"
            r.ai_pattern = "repeated"
            r.ai_dimension = "equipment"
            r.ai_reason_analysis = f"分析-{r.id}"
            r.ai_rectification_direction = "整改"
            r.ai_analyzed_at = datetime.now(UTC)
            out[r.id] = {}
        return out

    async def analyze_daily_summary(
        self, agg: Any, per: list[Any], *, channel: str,
    ) -> dict[str, Any]:
        return {"summary": "汇总", "key_issues": [], "rectification_suggestions": []}


def _view(record_id: str, *, bj_dt: datetime, desc: str) -> CentralAlarmView:
    return CentralAlarmView(
        id=record_id,
        feishu_record_id=record_id,
        alarm_date=bj_dt - _BJ,
        workshop="车间一",
        line="达托",
        post="DCS 内操",
        alarm_description=desc,
    )


# 高高压力报警（命中 _filter_high_high_alarms）
def _hh(record_id: str, bj_dt: datetime) -> CentralAlarmView:
    return _view(record_id, bj_dt=bj_dt, desc="V0407 储罐 高高压报警")


def _service(
    monkeypatch: pytest.MonkeyPatch, reader: FakeReader,
) -> tuple[CentralAlarmService, FakeAnalyst]:
    monkeypatch.setenv("SAFETY_CENTRAL_ALARM_DIRECT_ENABLED", "true")
    svc = CentralAlarmService.__new__(CentralAlarmService)
    svc.session = cast(Any, None)  # 直读路径不触 DB；误用会立刻暴露
    svc._reader = reader  # noqa: SLF001
    analyst = FakeAnalyst()
    svc.analyst = cast(Any, analyst)  # noqa: SLF001
    return svc, analyst


async def test_direct_report_uses_reader_and_no_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 当日北京时间 02:00 报警（滚动窗口内）
    target = date(2026, 9, 20)
    bj_dt = datetime(2026, 9, 20, 2, tzinfo=UTC)
    reader = FakeReader([_hh("r1", bj_dt), _hh("r2", bj_dt)])
    svc, analyst = _service(monkeypatch, reader)

    result = await svc.generate_daily_report(target, push=False, channel="test")

    assert result.total == 2
    assert result.analyzed == 2
    assert "高高压" in result.markdown_report
    # 逐条 AI 分析结果落在内存视图对象上（records_analyzed 侧证）
    assert set(result.records_analyzed) == {"r1", "r2"}
    assert "rolling:2026-09-20" in reader.calls
    assert any(c.startswith("window:") for c in reader.calls)  # 历史窗口也拉了
    assert analyst.history_index is not None  # AI 上下文走内存索引
    assert set(analyst.analyzed) == {"r1", "r2"}


async def test_direct_report_ai_failure_degrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = date(2026, 9, 20)
    reader = FakeReader([_hh("r1", datetime(2026, 9, 20, 2, tzinfo=UTC))])
    svc, analyst = _service(monkeypatch, reader)

    async def _boom(records: Any, *, channel: str = "system") -> dict[str, Any]:
        raise RuntimeError("AI down")

    analyst.analyze_per_records = _boom  # type: ignore[method-assign]
    result = await svc.generate_daily_report(target, push=False, channel="test")

    assert result.total == 1
    assert result.analyzed == 0  # AI 失败 → 退化纯数据版
    assert "V0407" in result.markdown_report


async def test_direct_filters_non_high_high(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = date(2026, 9, 20)
    reader = FakeReader([
        _hh("r1", datetime(2026, 9, 20, 2, tzinfo=UTC)),
        _view("normal", bj_dt=datetime(2026, 9, 20, 2, tzinfo=UTC),
              desc="常规温度波动"),  # 不命中高高规则
    ])
    svc, analyst = _service(monkeypatch, reader)
    result = await svc.generate_daily_report(target, push=False, channel="test")
    assert result.total == 1
    assert analyst.analyzed == ["r1"]


async def test_natural_day_mode_uses_date_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = date(2026, 9, 20)
    reader = FakeReader([_hh("r1", datetime(2026, 9, 20, 2, tzinfo=UTC))])
    svc, _analyst = _service(monkeypatch, reader)
    await svc.generate_daily_report(target, push=False, channel="test", rolling=False)
    assert "date:2026-09-20" in reader.calls


async def test_mirror_path_untouched_when_direct_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SAFETY_CENTRAL_ALARM_DIRECT_ENABLED", raising=False)
    called: list[str] = []

    class _Spy(CentralAlarmService):
        async def _get_records_by_rolling_window(
            self, target_date: date,
        ) -> tuple[list[Any], datetime, datetime]:
            called.append("orm-rolling")
            now = datetime.now(UTC)
            return [], now, now  # 空窗口 → 跳过 AI/flush，不触 DB

    svc = _Spy.__new__(_Spy)
    svc.session = cast(Any, None)
    svc._reader = None  # noqa: SLF001
    svc.analyst = cast(Any, FakeAnalyst())  # noqa: SLF001

    result = await svc.generate_daily_report(date(2026, 9, 20), push=False, channel="test")
    assert called == ["orm-rolling"]  # 直读关闭 → ORM 镜像取数
    assert result.total == 0
    # 直读 reader 未被触碰
    assert svc._reader is None  # noqa: SLF001
