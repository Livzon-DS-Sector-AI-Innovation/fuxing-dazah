"""周期报告 service 编排单测（注入替身 reader/analyst，零真机、零 DB 写）——ticket 01 RED。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import pytest

from app.modules.safety.service.central_alarm.reader import CentralAlarmView
from app.modules.safety.service.central_alarm.service import CentralAlarmService

_BJ = timedelta(hours=8)


class FakeReader:
    """替身：预置窗口数据，记录每次窗口调用。"""

    def __init__(self, views: list[CentralAlarmView]) -> None:
        self._views = views
        self.calls: list[str] = []

    async def fetch_window_records(
        self, *, start_utc: datetime, end_utc: datetime, strict: bool = False,
    ) -> list[CentralAlarmView]:
        self.calls.append(f"window:{start_utc.isoformat()}~{end_utc.isoformat()}")
        return [v for v in self._views if v.alarm_date and start_utc <= v.alarm_date < end_utc]


class FakeAnalyst:
    """替身：不调 AI，直接回填分析；记录逐条入参。"""

    def __init__(self) -> None:
        self.history_index: Any = None
        self.analyzed: list[str] = []
        self.max_records_seen: int | None = None

    async def analyze_per_records(
        self, records: Any, *, channel: str = "system",
        max_records: int = 50,
    ) -> dict[str, Any]:
        self.max_records_seen = max_records
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
        return {"summary": "日报汇总", "key_issues": [], "rectification_suggestions": []}

    async def analyze_period_summary(
        self, agg: Any, *, channel: str = "system",
    ) -> dict[str, Any]:
        return {
            "summary": "周期汇总",
            "key_issues": ["问题一"],
            "improvement_suggestions": ["建议一：校准 V0407 变送器"],
        }


def _view(record_id: str, *, bj_dt: datetime, desc: str,
          workshop: str = "车间一") -> CentralAlarmView:
    return CentralAlarmView(
        id=record_id,
        feishu_record_id=record_id,
        alarm_date=bj_dt - _BJ,
        workshop=workshop,
        line="达托",
        post="DCS 内操",
        alarm_description=desc,
    )


def _hh(record_id: str, bj_dt: datetime) -> CentralAlarmView:
    return _view(record_id, bj_dt=bj_dt, desc="V0407 储罐 高高压报警")


def _service(
    monkeypatch: pytest.MonkeyPatch, reader: FakeReader,
) -> tuple[CentralAlarmService, FakeAnalyst]:
    monkeypatch.setenv("SAFETY_CENTRAL_ALARM_DIRECT_ENABLED", "true")
    # 加发群默认 off：既有用例只验证总卡主通道；加发用例单独打开
    monkeypatch.setenv("SAFETY_CENTRAL_ALARM_PERIOD_EXTRA_CHAT_ID", "off")
    svc = CentralAlarmService.__new__(CentralAlarmService)
    svc.session = cast(Any, None)  # 直读路径不触 DB；误用会立刻暴露
    svc._reader = reader  # noqa: SLF001
    analyst = FakeAnalyst()
    svc.analyst = cast(Any, analyst)  # noqa: SLF001
    return svc, analyst


def _digest_stub(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """打桩 upsert_daily_digest，记录调用。"""
    import app.modules.safety.feishu.daily_digest as dd

    calls: list[dict[str, Any]] = []

    async def _stub(report_date: date, key: str, cell: Any, **kw: Any) -> bool:
        calls.append({"date": report_date, "key": key, "cell": cell})
        return True

    monkeypatch.setattr(dd, "upsert_daily_digest", _stub)
    return calls


# 上一完整自然周（周一 2026-11-09 触发 → 11-02~11-08）的 UTC 边界
_WEEK_START_UTC = datetime(2026, 11, 2, 0, tzinfo=UTC) - _BJ
_WEEK_END_UTC = datetime(2026, 11, 9, 0, tzinfo=UTC) - _BJ
_PREV_WEEK_START_UTC = datetime(2026, 10, 26, 0, tzinfo=UTC) - _BJ
_PREV_WEEK_END_UTC = datetime(2026, 11, 2, 0, tzinfo=UTC) - _BJ


async def test_weekly_report_window_and_push(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = date(2026, 11, 9)  # 周一
    reader = FakeReader([
        _hh("r1", datetime(2026, 11, 3, 10, tzinfo=UTC)),   # 本周
        _hh("r2", datetime(2026, 11, 7, 22, tzinfo=UTC)),   # 本周
        _hh("p1", datetime(2026, 10, 27, 10, tzinfo=UTC)),  # 上周（环比）
    ])
    svc, analyst = _service(monkeypatch, reader)
    digest_calls = _digest_stub(monkeypatch)

    result = await svc.generate_period_report(
        "weekly", ref, push=True, channel="test",
    )

    # 窗口断言：周期窗口 + 环比窗口（宽窗口拉取含 14 天历史）
    windows = [c for c in reader.calls if c.startswith("window:")]
    assert any(
        f"window:{_WEEK_START_UTC.isoformat()}~{_WEEK_END_UTC.isoformat()}" == c
        or (_WEEK_START_UTC.isoformat() in c and _WEEK_END_UTC.isoformat() in c)
        for c in windows
    ), f"周期窗口未按上一自然周拉取: {windows}"
    assert any(
        _PREV_WEEK_START_UTC.isoformat() in c and _PREV_WEEK_END_UTC.isoformat() in c
        for c in windows
    ), f"环比窗口未拉取上一周: {windows}"

    assert result.report_kind == "weekly"
    assert result.period_start == date(2026, 11, 2)
    assert result.period_end == date(2026, 11, 8)
    assert result.total == 2                    # 上周的 p1 只进环比不进本期
    assert result.analyzed == 2
    # 高高筛选 + 分析回填后 Top10/误报指标进入报告
    assert "高频报警点" in result.markdown_report
    assert "建议一" in result.markdown_report
    # 推送只投安全速递总卡（central_alarm_weekly 格子），无独立群卡
    assert len(digest_calls) == 1
    assert digest_calls[0]["key"] == "central_alarm_weekly"
    assert digest_calls[0]["cell"].detail == result.markdown_report
    # 逐条补漏走周期上限（>50）
    assert analyst.max_records_seen is not None and analyst.max_records_seen > 50


async def test_weekly_report_filters_non_high_high(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = date(2026, 11, 9)
    reader = FakeReader([
        _hh("r1", datetime(2026, 11, 3, 10, tzinfo=UTC)),
        _view("normal", bj_dt=datetime(2026, 11, 3, 11, tzinfo=UTC), desc="常规温度波动"),
    ])
    svc, analyst = _service(monkeypatch, reader)
    result = await svc.generate_period_report("weekly", ref, push=False, channel="test")
    assert result.total == 1
    assert analyst.analyzed == ["r1"]


async def test_period_report_push_false_skips_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = date(2026, 11, 9)
    reader = FakeReader([_hh("r1", datetime(2026, 11, 3, 10, tzinfo=UTC))])
    svc, _ = _service(monkeypatch, reader)
    digest_calls = _digest_stub(monkeypatch)
    result = await svc.generate_period_report("weekly", ref, push=False, channel="test")
    assert result.total == 1
    assert digest_calls == []
    assert result.push_results == []


async def test_period_report_ai_failure_degrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = date(2026, 11, 9)
    reader = FakeReader([_hh("r1", datetime(2026, 11, 3, 10, tzinfo=UTC))])
    svc, analyst = _service(monkeypatch, reader)
    _digest_stub(monkeypatch)

    async def _per_boom(records: Any, *, channel: str = "system",
                        max_records: int = 50) -> dict[str, Any]:
        raise RuntimeError("AI down")

    async def _sum_boom(agg: Any, *, channel: str = "system") -> dict[str, Any]:
        raise RuntimeError("AI down")

    analyst.analyze_per_records = _per_boom  # type: ignore[method-assign]
    analyst.analyze_period_summary = _sum_boom  # type: ignore[method-assign]

    result = await svc.generate_period_report("weekly", ref, push=False, channel="test")
    assert result.total == 1
    assert result.analyzed == 0
    assert "报警总数" in result.markdown_report   # 纯数据降级版
    assert "改进建议" not in result.markdown_report


async def test_monthly_report_window_and_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = date(2026, 11, 10)  # 11 月触发 → 报 10 月
    reader = FakeReader([
        _hh("r1", datetime(2026, 10, 5, 10, tzinfo=UTC)),
        _hh("r2", datetime(2026, 10, 31, 23, tzinfo=UTC)),   # 月末边界（BJ 23:00 仍在 10/31）
        _hh("p1", datetime(2026, 9, 15, 10, tzinfo=UTC)),    # 上月（环比）
    ])
    svc, _ = _service(monkeypatch, reader)
    digest_calls = _digest_stub(monkeypatch)

    result = await svc.generate_period_report("monthly", ref, push=True, channel="test")

    assert result.report_kind == "monthly"
    assert result.period_start == date(2026, 10, 1)
    assert result.period_end == date(2026, 10, 31)
    assert result.total == 2
    assert "31" in result.markdown_report  # 日均分母=31 天（2/31≈0.1）
    assert digest_calls[0]["key"] == "central_alarm_monthly"


async def test_prev_fetch_failure_degrades_to_no_prev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """环比窗口拉取失败 → 报告照常出（无环比），不整体失败。"""
    ref = date(2026, 11, 9)
    reader = FakeReader([_hh("r1", datetime(2026, 11, 3, 10, tzinfo=UTC))])
    svc, _ = _service(monkeypatch, reader)
    _digest_stub(monkeypatch)

    real_fetch = reader.fetch_window_records

    async def _flaky_fetch(
        *, start_utc: datetime, end_utc: datetime, strict: bool = False,
        **kw: Any,
    ) -> list[CentralAlarmView]:
        if start_utc == _PREV_WEEK_START_UTC:  # 环比窗口拉取失败
            raise RuntimeError("prev window down")
        return await real_fetch(
            start_utc=start_utc, end_utc=end_utc, strict=strict,
        )

    reader.fetch_window_records = _flaky_fetch  # type: ignore[method-assign]

    result = await svc.generate_period_report("weekly", ref, push=False, channel="test")
    assert result.total == 1
    assert "环比" in result.markdown_report  # 环比块渲染为「—」


# ── 加发群（二期安全群）追加投递 ──


def _extra_card_stub(
    monkeypatch: pytest.MonkeyPatch, *, msg_id: str | None = "om_ok",
) -> list[dict[str, Any]]:
    """打桩 send_digest_cell_card，记录调用。"""
    import app.modules.safety.feishu.daily_digest as dd

    calls: list[dict[str, Any]] = []

    async def _stub(cell: Any, *, chat_id: str | None = None,
                    title: str | None = None, **kw: Any) -> str | None:
        calls.append({"chat_id": chat_id, "title": title, "cell": cell})
        return msg_id

    monkeypatch.setattr(dd, "send_digest_cell_card", _stub)
    return calls


async def test_extra_group_receives_same_cell_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """加发群开启：同款速递格子卡追加投递二期安全群（主通道总卡不受影响）。"""
    ref = date(2026, 11, 9)
    reader = FakeReader([_hh("r1", datetime(2026, 11, 3, 10, tzinfo=UTC))])
    svc, _ = _service(monkeypatch, reader)
    monkeypatch.setenv("SAFETY_CENTRAL_ALARM_PERIOD_EXTRA_CHAT_ID", "oc_extra_group")
    digest_calls = _digest_stub(monkeypatch)
    extra_calls = _extra_card_stub(monkeypatch)

    result = await svc.generate_period_report("weekly", ref, push=True, channel="test")

    assert len(digest_calls) == 1                       # 主通道：总卡一次
    assert len(extra_calls) == 1                        # 加发：同款格子卡一次
    assert extra_calls[0]["chat_id"] == "oc_extra_group"
    assert "周报" in (extra_calls[0]["title"] or "")
    # 加发卡与总卡格子同款同内容
    assert extra_calls[0]["cell"] is digest_calls[0]["cell"]
    # push_results 同时记录两通道
    assert [p["success"] for p in result.push_results] == [True, True]


async def test_extra_group_failure_is_best_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """加发失败不阻塞报告、不标任务失败（尽力而为；主通道成败以总卡为准）。"""
    ref = date(2026, 11, 9)
    reader = FakeReader([_hh("r1", datetime(2026, 11, 3, 10, tzinfo=UTC))])
    svc, _ = _service(monkeypatch, reader)
    monkeypatch.setenv("SAFETY_CENTRAL_ALARM_PERIOD_EXTRA_CHAT_ID", "oc_extra_group")
    _digest_stub(monkeypatch)
    _extra_card_stub(monkeypatch, msg_id=None)  # 加发失败（返回 None）

    result = await svc.generate_period_report("weekly", ref, push=True, channel="test")

    assert result.total == 1                            # 报告正常生成
    digest_ok = [p for p in result.push_results if p.get("chat_id") != "oc_extra_group"]
    assert all(p["success"] for p in digest_ok)         # 总卡成功
    extra = [p for p in result.push_results if p.get("chat_id") == "oc_extra_group"]
    assert len(extra) == 1 and extra[0]["success"] is False
    assert extra[0].get("best_effort") is True          # 尽力而为标记


async def test_extra_group_disabled_by_default_in_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """off 停用加发：只投总卡，零加发调用。"""
    ref = date(2026, 11, 9)
    reader = FakeReader([_hh("r1", datetime(2026, 11, 3, 10, tzinfo=UTC))])
    svc, _ = _service(monkeypatch, reader)  # helper 已置 off
    digest_calls = _digest_stub(monkeypatch)
    extra_calls = _extra_card_stub(monkeypatch)

    result = await svc.generate_period_report("weekly", ref, push=True, channel="test")

    assert len(digest_calls) == 1
    assert extra_calls == []
    assert len(result.push_results) == 1
