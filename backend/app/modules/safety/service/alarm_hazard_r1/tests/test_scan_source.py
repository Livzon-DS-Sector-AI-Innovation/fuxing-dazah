"""FireAlarmScanSource —— 17:15 cron 门控 + 滚动 7 天窗口 + 记录粒度 Trigger。

cron 语义对齐底座 CronTickSource（due_fire_times 幂等网格/停机回溯窗/
首见 rebase 零回溯）；窗口拉取走既有 fetch_window_records（报警时间倒序
+提前终止）；closure_class 在翻译层进 payload._derived（规则只判结构化值）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.modules.safety.service.alarm_hazard_r1.scan_source import (
    FireAlarmScanSource,
)
from app.platform.superagent.models import AgentSource

TZ = ZoneInfo("Asia/Shanghai")
_SCAN_MODULE = "app.modules.safety.service.alarm_hazard_r1.scan_source"


def _source_row(config: dict | None = None) -> AgentSource:
    return AgentSource(
        kind="cron_scan", name="safety.fire_alarm.r1.test",
        config=config or {
            "schedule": {"strategy": "cron", "expression": "15 17 * * *",
                          "timezone": "Asia/Shanghai"},
            "window_days": 7,
            "relevant_fields": ["报警性质", "报警原因分类", "处理情况"],
            "evaluate": True,
            "thread_prefix": "fire_alarm",
            "max_catchup_seconds": 90000,  # 25h：跨日两轮扫描可回溯（默认 24h）
        },
        enabled=True,
    )


def _record(rid: str, **field_overrides: Any) -> dict:
    fields = {
        "报警性质": "泄漏报警",
        "报警原因分类": "氨水引发",
        "处理情况": "已通知仪表",
        "报警楼栋": "提三",
        "报警部位": [{"type": "text", "text": "1楼罐区"}],
    }
    fields.update(field_overrides)
    return {"record_id": rid, "fields": fields, "last_modified_time": 1793630412844}


def _patch_window(monkeypatch: pytest.MonkeyPatch, records, fetched=None):
    """patch 窗口拉取（异步假 fetcher；fetched 列表记录每次调用的天数）。"""
    async def _fetch(days: int):
        if fetched is not None:
            fetched.append(days)
        return list(records)

    monkeypatch.setattr(f"{_SCAN_MODULE}.fetch_fire_alarm_window", _fetch)


async def test_first_seen_rebases_without_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """首见：登记基准零回溯（防启用瞬间全表洪泛），不发请求。"""
    fetched: list[int] = []
    _patch_window(monkeypatch, [], fetched)
    result = await FireAlarmScanSource().poll(None, _source_row(), cursors={})
    assert result.drafts == []
    assert result.rebase is True
    assert fetched == []


async def test_not_due_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """未到 17:15：零 drafts 零请求（SourcePollGenerator 每 30s 轮询零成本）。"""
    fetched: list[int] = []
    _patch_window(monkeypatch, [], fetched)
    result = await FireAlarmScanSource().poll(
        None, _source_row(),
        cursors={"last_tick": {"value": datetime(2026, 11, 3, 10, 0, tzinfo=TZ).isoformat()}},
        now=datetime(2026, 11, 3, 12, 0, tzinfo=TZ),
    )
    assert result.drafts == [] and result.rebase is False and not result.cursor_updates
    assert fetched == []


async def test_due_produces_record_grain_drafts(monkeypatch: pytest.MonkeyPatch) -> None:
    """跨过 17:15 触发点：拉窗一次，产记录粒度 drafts，读位推进到触发点。"""
    records = [
        _record("recA", 处理情况="已通知仪表"),
        _record("recB", 报警性质="误报", 报警原因分类="蒸汽引发", 处理情况="22:50恢复系统"),
    ]
    fetched: list[int] = []
    _patch_window(monkeypatch, records, fetched)
    result = await FireAlarmScanSource().poll(
        None, _source_row(),
        cursors={"last_tick": {"value": datetime(2026, 11, 3, 10, 0, tzinfo=TZ).isoformat()}},
        now=datetime(2026, 11, 3, 18, 0, tzinfo=TZ),
    )
    assert fetched == [7]
    assert len(result.drafts) == 2
    a, b = result.drafts
    # external_id = fire_alarm:<record_id>:<指纹>；thread = bitable:fire_alarm:<rid>
    assert a.external_id.startswith("fire_alarm:recA:")
    assert a.thread_key == "bitable:fire_alarm:recA"
    assert a.actor == {"id": "recA", "type": "bitable_record"}
    assert a.human is False
    # closure_class 翻译进 _derived（规则引擎只判结构化值）
    assert a.payload["_derived"] == {"closure_class": "pending_handover"}
    assert b.payload["_derived"] == {"closure_class": "closed"}
    assert a.payload["channel"] == {"kind": "bitable", "record_id": "recA"}
    assert a.payload["record_id"] == "recA"
    # 读位推进到最后触发点（网格稳定不漂移）
    assert result.cursor_updates["last_tick"] == (
        datetime(2026, 11, 3, 17, 15, tzinfo=TZ).isoformat()
    )


async def test_stale_cursor_rebases(monkeypatch: pytest.MonkeyPatch) -> None:
    """停机超回溯窗（默认 24h）：rebase 不回溯（防重启洪泛）。"""
    fetched: list[int] = []
    _patch_window(monkeypatch, [], fetched)
    result = await FireAlarmScanSource().poll(
        None, _source_row(),
        cursors={"last_tick": {"value": datetime(2026, 11, 1, 10, 0, tzinfo=TZ).isoformat()}},
        now=datetime(2026, 11, 3, 18, 0, tzinfo=TZ),
    )
    assert result.rebase is True and result.drafts == []
    assert fetched == []
