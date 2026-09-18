"""Ticket 04/06：FireAlarmService 直读路径、闸门与写回集成单测。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.service.bitable_direct import writer as bd_writer
from app.modules.safety.service.fire_alarm import service as service_module
from app.modules.safety.service.fire_alarm import writeback as fire_writeback
from app.modules.safety.service.fire_alarm.reader import FireAlarmView

TARGET_DATE = date(2026, 9, 17)
START = datetime(2026, 9, 16, 17, 0, tzinfo=UTC)


def _view(record_id: str) -> FireAlarmView:
    return FireAlarmView(
        id=record_id,
        feishu_record_id=record_id,
        source="bitable",
        synced_at=datetime(2026, 9, 17, 3, 0, tzinfo=UTC),
        alarm_time=datetime(2026, 9, 17, 2, 0, tzinfo=UTC),
        alarm_type="火灾报警",
        department="动力车间",
        department_leader_name="张三",
        building="1号装置",
        location="压缩机房",
        alarm_nature="误报",
        cause_description="传感器老化误触发",
    )


class FakeReader:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.records = [_view("rec001"), _view("rec002")]

    async def get_records_by_date(self, target_date: date) -> list[FireAlarmView]:
        self.calls.append("date")
        return list(self.records)

    async def get_records_by_rolling_window(
        self, target_date: date
    ) -> tuple[list[FireAlarmView], datetime, datetime]:
        self.calls.append("rolling")
        return list(self.records), START, START.replace(hour=9)

    async def get_records_by_week(
        self, week_start: date, week_end: date
    ) -> list[FireAlarmView]:
        self.calls.append("week")
        return list(self.records)


class FakeAnalyst:
    async def analyze_per_records(
        self, records: list[Any], *, channel: str = "system"
    ) -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {}
        for record in records:
            record.ai_dimension = "equipment"
            record.ai_reason_analysis = "传感器老化"
            record.ai_rectification_direction = "更换传感器"
            record.ai_analyzed_at = datetime(2026, 9, 17, 3, 0, tzinfo=UTC)
            out[str(record.id)] = {"dimension": "设备设施"}
        return out

    async def analyze_daily_summary(self, agg: Any, summaries: list[str], **kw: Any) -> None:
        return None

    async def analyze_weekly_summary(self, agg: Any, **kw: Any) -> None:
        return None


class ExplodingSession:
    def add(self, obj: Any) -> None:
        raise AssertionError("direct mode must not write session")

    async def flush(self) -> None:
        raise AssertionError("direct mode must not flush")

    async def commit(self) -> None:
        raise AssertionError("direct mode must not commit")

    async def scalars(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("direct mode must not query session")


async def test_direct_daily_report_uses_reader_and_pushes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAFETY_FIRE_ALARM_DIRECT_ENABLED", "true")
    monkeypatch.setenv("SAFETY_DAILY_DIGEST_ENABLED", "false")
    monkeypatch.setattr(
        service_module, "_resolve_mention_ids", lambda names: _no_mentions()
    )

    async def fake_send_group_card(**kwargs: Any) -> str:
        return "om_test"

    monkeypatch.setattr(service_module, "send_group_card", fake_send_group_card)

    fake_reader = FakeReader()
    svc = service_module.FireAlarmService(
        cast(AsyncSession, ExplodingSession()), reader=fake_reader
    )
    svc.analyst = cast(Any, FakeAnalyst())

    result = await svc.generate_daily_report(
        target_date=TARGET_DATE, push=True, channel="web", chat_id="oc_test"
    )

    assert fake_reader.calls == ["date"]
    assert result.total == 2
    assert result.markdown_report
    assert result.push_results == [{
        "chat_id": "oc_test", "success": True, "message_id": "om_test",
    }]


async def _no_mentions() -> dict[str, str]:
    return {}


async def test_direct_sync_job_is_gated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAFETY_FIRE_ALARM_DIRECT_ENABLED", "true")
    svc = service_module.FireAlarmService(
        cast(AsyncSession, ExplodingSession()), reader=FakeReader()
    )

    assert await svc.sync_from_bitable() == (0, 0)


async def test_direct_generation_calls_writeback_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAFETY_FIRE_ALARM_DIRECT_ENABLED", "true")
    monkeypatch.setenv("SAFETY_FIRE_ALARM_WRITEBACK_AI_ENABLED", "true")
    monkeypatch.setenv("SAFETY_DAILY_DIGEST_ENABLED", "false")
    monkeypatch.setattr(service_module, "_resolve_mention_ids", lambda names: _no_mentions())

    captured: list[list[Any]] = []

    async def fake_writeback(records: list[Any], **kwargs: Any) -> Any:
        captured.append(list(records))
        return bd_writer.WritebackResult(written=len(records))

    monkeypatch.setattr(
        fire_writeback, "writeback_ai_results", fake_writeback
    )

    svc = service_module.FireAlarmService(
        cast(AsyncSession, ExplodingSession()), reader=FakeReader()
    )
    svc.analyst = cast(Any, FakeAnalyst())

    await svc.generate_daily_report(
        target_date=TARGET_DATE, push=False, channel="web",
    )

    assert len(captured) == 1
    assert [r.id for r in captured[0]] == ["rec001", "rec002"]


class _IncrementalFakeAnalyst(FakeAnalyst):
    """增量替身：只分析 ai_analyzed_at 为空的记录。"""

    async def analyze_per_records(
        self, records: list[Any], *, channel: str = "system",
    ) -> dict[str, dict[str, str]]:
        pending = [r for r in records if r.ai_analyzed_at is None]
        return await super().analyze_per_records(pending, channel=channel)


async def test_direct_writeback_only_newly_analyzed_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """群日报 + 私发任务先后跑：第二轮不把已分析记录再写一遍。"""
    monkeypatch.setenv("SAFETY_FIRE_ALARM_DIRECT_ENABLED", "true")
    monkeypatch.setenv("SAFETY_FIRE_ALARM_WRITEBACK_AI_ENABLED", "true")
    monkeypatch.setenv("SAFETY_DAILY_DIGEST_ENABLED", "false")
    monkeypatch.setattr(
        service_module, "_resolve_mention_ids", lambda names: _no_mentions()
    )

    already = _view("rec001")
    already.ai_dimension = "process"
    already.ai_reason_analysis = "传感器老化"
    already.ai_rectification_direction = "更换传感器"
    already.ai_analyzed_at = datetime(2026, 9, 16, 3, 0, tzinfo=UTC)
    fresh = _view("rec002")

    reader = FakeReader()
    reader.records = [already, fresh]

    captured: list[list[Any]] = []

    async def fake_writeback(records: list[Any], **kwargs: Any) -> Any:
        captured.append(list(records))
        return bd_writer.WritebackResult(written=len(records))

    monkeypatch.setattr(fire_writeback, "writeback_ai_results", fake_writeback)

    svc = service_module.FireAlarmService(
        cast(AsyncSession, ExplodingSession()), reader=reader
    )
    svc.analyst = cast(Any, _IncrementalFakeAnalyst())

    # 第一轮（群日报）：只回写本轮新分析的 rec002。
    await svc.generate_daily_report(
        target_date=TARGET_DATE, push=False, channel="web",
    )
    assert len(captured) == 1
    assert [r.id for r in captured[0]] == ["rec002"]

    # 第二轮（私发）：两条都已分析，不应再产生任何回写。
    await svc.generate_daily_report(
        target_date=TARGET_DATE, push=False, channel="web",
    )
    assert len(captured) == 1
