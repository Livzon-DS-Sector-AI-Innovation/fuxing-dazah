"""R8 指纹双测 —— 改判定相关字段→新 Trigger；改无关字段→无新 Trigger（红线⑤）。

经 FireAlarmScanSource 两轮扫描（同 record_id 不同字段值）验证 external_id
指纹行为：relevant_fields=报警性质/报警原因分类/处理情况（§9.2 口径）。
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


def _source_row() -> AgentSource:
    return AgentSource(
        kind="cron_scan", name="safety.fire_alarm.r1.test",
        config={
            "schedule": {"strategy": "cron", "expression": "15 17 * * *",
                          "timezone": "Asia/Shanghai"},
            "window_days": 7,
            "relevant_fields": ["报警性质", "报警原因分类", "处理情况"],
            "evaluate": True,
            "thread_prefix": "fire_alarm",
            "max_catchup_seconds": 90000,
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


def _patch_window(monkeypatch: pytest.MonkeyPatch, records) -> None:
    async def _fetch(days: int):
        return list(records)

    monkeypatch.setattr(
        "app.modules.safety.service.alarm_hazard_r1.scan_source.fetch_fire_alarm_window",
        _fetch,
    )


# ═══════════════════════════════════════════════════════════════
# R8 指纹双测（红线⑤）
# ═══════════════════════════════════════════════════════════════


async def _scan_twice(monkeypatch, before, after) -> tuple[str, str]:
    """第一天扫 before、第二天扫 after（同 record_id），返回两轮首条 external_id。"""
    _patch_window(monkeypatch, before)
    r1 = await FireAlarmScanSource().poll(
        None, _source_row(),
        cursors={"last_tick": {"value": datetime(2026, 11, 3, 10, 0, tzinfo=TZ).isoformat()}},
        now=datetime(2026, 11, 3, 18, 0, tzinfo=TZ),
    )
    _patch_window(monkeypatch, after)
    r2 = await FireAlarmScanSource().poll(
        None, _source_row(),
        cursors={"last_tick": {"value": r1.cursor_updates["last_tick"]}},
        now=datetime(2026, 11, 4, 18, 0, tzinfo=TZ),
    )
    return r1.drafts[0].external_id, r2.drafts[0].external_id


async def test_fingerprint_changes_on_relevant_field(monkeypatch: pytest.MonkeyPatch) -> None:
    """改 性质/原因分类/处理情况 → 新 external_id（新 Trigger 重研判）。"""
    for field, value in (
        ("报警性质", "误报"),
        ("报警原因分类", "现场着火"),
        ("处理情况", "22:50恢复系统"),
    ):
        first, second = await _scan_twice(
            monkeypatch, [_record("recA")], [_record("recA", **{field: value})],
        )
        assert first != second, field


async def test_fingerprint_stable_on_irrelevant_field(monkeypatch: pytest.MonkeyPatch) -> None:
    """改 报警部位/楼栋/处置人员/照片 → 同 external_id（无新 Trigger）。"""
    for field, value in (
        ("报警部位", [{"type": "text", "text": "2楼泵房"}]),
        ("报警楼栋", "提一"),
        ("处置人员", [{"id": "ou_x"}]),
        ("报警记录照片", [{"file_token": "fn"}]),
    ):
        first, second = await _scan_twice(
            monkeypatch, [_record("recA")], [_record("recA", **{field: value})],
        )
        assert first == second, field
