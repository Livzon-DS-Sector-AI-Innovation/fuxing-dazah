"""风险等级回写单测（Ticket 05 验收）。

覆盖：只写「日报风险等级（AI）」一列、值与单选选项严格对应、串行 + 0.5 秒间隔、
      未知等级跳过、单条失败/抛错不阻塞推送、开关默认关闭。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.safety.service.special_op_direct import bitable_repo, contract, daily
from app.modules.safety.service.special_op_direct.tests.factories import (
    DAY,
    HIGH_FIELDS,
    LOW_FIELDS,
    MEDIUM_FIELDS,
    FakeAnalyst,
    FakePusher,
    FakeReader,
    record,
)

WRITEBACK_ENV = "SAFETY_SPECIAL_OP_WRITEBACK_RISK_ENABLED"


class FakeWriter:
    """替身回写器：记录每次写请求；可整体失败（False）或抛错。"""

    def __init__(self, result: bool | Exception = True) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def update_record(
        self, record_id: str, fields: dict[str, Any], table_id: str | None = None,
    ) -> bool:
        self.calls.append({"record_id": record_id, "fields": fields})
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeSleep:
    """替身 sleep：记录间隔，不真等。"""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def _views() -> list[bitable_repo.SpecialOpView]:
    items = [
        record("rec-high", **HIGH_FIELDS),
        record("rec-medium", **MEDIUM_FIELDS),
        record("rec-low", **LOW_FIELDS),
    ]
    return [bitable_repo.assess_view(bitable_repo.to_view(i)) for i in items]


def test_contract_maps_level_to_single_select_option() -> None:
    assert contract.RISK_FIELD_NAME == "日报风险等级（AI）"
    assert contract.RISK_FIELD_OPTIONS == ("高风险", "中风险", "低风险")
    assert contract.option_for_risk_level("high") == "高风险"
    assert contract.option_for_risk_level("medium") == "中风险"
    assert contract.option_for_risk_level("low") == "低风险"
    assert contract.option_for_risk_level(None) is None
    assert contract.option_for_risk_level("unknown") is None


async def test_writeback_writes_only_risk_column_for_each_record() -> None:
    writer = FakeWriter()

    result = await bitable_repo.writeback_risk_levels(
        _views(), writer=writer, sleep=FakeSleep()
    )

    assert [c["record_id"] for c in writer.calls] == ["rec-high", "rec-medium", "rec-low"]
    assert [c["fields"] for c in writer.calls] == [
        {contract.RISK_FIELD_NAME: "高风险"},
        {contract.RISK_FIELD_NAME: "中风险"},
        {contract.RISK_FIELD_NAME: "低风险"},
    ]
    assert all(list(c["fields"]) == [contract.RISK_FIELD_NAME] for c in writer.calls)
    assert (result.attempted, result.written, result.skipped, result.failed) == (3, 3, 0, [])
    assert result.ok is True


async def test_writeback_is_serial_with_interval() -> None:
    sleeper = FakeSleep()

    await bitable_repo.writeback_risk_levels(_views(), writer=FakeWriter(), sleep=sleeper)

    assert sleeper.delays == [0.5, 0.5]
    assert bitable_repo.WRITEBACK_INTERVAL_SECONDS == 0.5


async def test_writeback_skips_unknown_level_and_missing_record_id() -> None:
    views = _views()
    views[0].daily_risk_level = None
    views[1].daily_risk_level = "unknown"
    views[2].feishu_record_id = ""
    writer = FakeWriter()

    result = await bitable_repo.writeback_risk_levels(
        views, writer=writer, sleep=FakeSleep()
    )

    assert writer.calls == []
    assert (result.attempted, result.written, result.skipped) == (0, 0, 3)


async def test_writeback_records_failure_without_raising() -> None:
    failed_writer = FakeWriter(result=False)
    result = await bitable_repo.writeback_risk_levels(
        _views(), writer=failed_writer, sleep=FakeSleep()
    )

    assert result.failed == ["rec-high", "rec-medium", "rec-low"]
    assert result.written == 0
    assert result.ok is False

    raising_writer = FakeWriter(result=RuntimeError("bitable 500"))
    result2 = await bitable_repo.writeback_risk_levels(
        _views(), writer=raising_writer, sleep=FakeSleep()
    )

    assert result2.failed == ["rec-high", "rec-medium", "rec-low"]
    assert result2.written == 0


async def test_run_writeback_follows_switch_and_does_not_block_push(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(WRITEBACK_ENV, raising=False)
    off_writer = FakeWriter()
    pusher = FakePusher()

    await daily.run(
        DAY, "today", reader=FakeReader(records=[record("rec-low", **LOW_FIELDS)]),
        pusher=pusher, analyst=FakeAnalyst(), writer=off_writer,
    )

    assert off_writer.calls == []
    assert len(pusher.calls) == 1

    monkeypatch.setenv(WRITEBACK_ENV, "true")
    on_writer = FakeWriter(result=RuntimeError("bitable 500"))

    result = await daily.run(
        DAY, "today", reader=FakeReader(records=[record("rec-low", **LOW_FIELDS)]),
        pusher=pusher, analyst=FakeAnalyst(), writer=on_writer,
    )

    assert [c["fields"] for c in on_writer.calls] == [
        {contract.RISK_FIELD_NAME: "低风险"}
    ]
    assert len(pusher.calls) == 2
    assert result.push_results[-1]["success"] is True
