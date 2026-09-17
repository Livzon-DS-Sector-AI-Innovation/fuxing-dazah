"""Ticket 05：消防 AI 结果回写单测。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.modules.safety.service.fire_alarm import contract, writeback
from app.modules.safety.service.fire_alarm.reader import FireAlarmView


class FakeWriter:
    def __init__(self, result: bool | Exception = True) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def update_record(
        self,
        record_id: str,
        fields: dict[str, Any],
        table_id: str | None = None,
    ) -> bool:
        self.calls.append({"record_id": record_id, "fields": fields})
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeSleep:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def _view(record_id: str, **kw: Any) -> FireAlarmView:
    return FireAlarmView(
        id=record_id,
        feishu_record_id=record_id,
        source="bitable",
        synced_at=datetime(2026, 9, 17, 3, 0, tzinfo=UTC),
        alarm_time=datetime(2026, 9, 17, 2, 0, tzinfo=UTC),
        alarm_type="火灾报警",
        department="动力车间",
        alarm_nature="误报",
        ai_dimension=kw.get("dimension", "equipment"),
        ai_reason_analysis=kw.get("reason", "传感器老化导致误报"),
        ai_rectification_direction=kw.get("direction", "更换传感器并定期校验"),
        ai_analyzed_at=kw.get("analyzed_at", datetime(2026, 9, 17, 3, 0, tzinfo=UTC)),
    )


async def test_writeback_only_four_ai_columns() -> None:
    writer = FakeWriter()
    result = await writeback.writeback_ai_results(
        [_view("rec001")], writer=writer, sleep=FakeSleep()
    )

    assert result.written == 1
    assert writer.calls == [{
        "record_id": "rec001",
        "fields": {
            contract.AI_DIMENSION_FIELD: "设备设施",
            contract.AI_REASON_ANALYSIS_FIELD: "传感器老化导致误报",
            contract.AI_RECTIFICATION_DIRECTION_FIELD: "更换传感器并定期校验",
            contract.AI_ANALYZED_AT_FIELD: int(
                datetime(2026, 9, 17, 3, 0, tzinfo=UTC).timestamp() * 1000
            ),
        },
    }]
    assert set(writer.calls[0]["fields"]) <= set(contract.AI_FIELD_NAMES)


async def test_writeback_skips_empty_values_and_missing_record_id() -> None:
    writer = FakeWriter()
    empty = _view("rec-empty", dimension=None, reason=None, direction=None, analyzed_at=None)
    missing = _view("")
    result = await writeback.writeback_ai_results(
        [empty, missing], writer=writer, sleep=FakeSleep()
    )

    assert writer.calls == []
    assert result.attempted == 0
    assert result.skipped == 2


async def test_writeback_partial_failure_does_not_raise() -> None:
    writer = FakeWriter(result=False)
    result = await writeback.writeback_ai_results(
        [_view("rec001"), _view("rec002")], writer=writer, sleep=FakeSleep()
    )

    assert result.written == 0
    assert result.failed == ["rec001", "rec002"]
    assert result.ok is False


async def test_writeback_uses_serial_interval() -> None:
    sleeper = FakeSleep()
    await writeback.writeback_ai_results(
        [_view("rec001"), _view("rec002"), _view("rec003")],
        writer=FakeWriter(),
        sleep=sleeper,
    )
    assert sleeper.delays == [0.5, 0.5]
