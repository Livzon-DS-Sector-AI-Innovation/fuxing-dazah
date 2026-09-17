"""Ticket 06：消防直读开关与闸门单测。"""

from __future__ import annotations

import pytest

from app.modules.safety.service.fire_alarm import config

ENVS = (
    "SAFETY_FIRE_ALARM_DIRECT_ENABLED",
    "SAFETY_FIRE_ALARM_EVENT_SYNC_ENABLED",
    "SAFETY_FIRE_ALARM_SYNC_JOB_ENABLED",
    "SAFETY_FIRE_ALARM_WRITEBACK_AI_ENABLED",
)


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENVS:
        monkeypatch.delenv(name, raising=False)


def test_switches_default_off_and_legacy_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear(monkeypatch)
    assert config.direct_enabled() is False
    assert config.event_sync_enabled() is False
    assert config.sync_job_enabled() is False
    assert config.writeback_ai_enabled() is False
    assert config.legacy_event_sync_active() is True
    assert config.legacy_sync_job_active() is True


def test_direct_switch_stops_legacy_and_allows_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("SAFETY_FIRE_ALARM_DIRECT_ENABLED", "true")
    assert config.legacy_event_sync_active() is False
    assert config.legacy_sync_job_active() is False

    monkeypatch.setenv("SAFETY_FIRE_ALARM_EVENT_SYNC_ENABLED", "1")
    monkeypatch.setenv("SAFETY_FIRE_ALARM_SYNC_JOB_ENABLED", "yes")
    assert config.legacy_event_sync_active() is True
    assert config.legacy_sync_job_active() is True

    monkeypatch.setenv("SAFETY_FIRE_ALARM_DIRECT_ENABLED", "false")
    monkeypatch.setenv("SAFETY_FIRE_ALARM_EVENT_SYNC_ENABLED", "false")
    monkeypatch.setenv("SAFETY_FIRE_ALARM_SYNC_JOB_ENABLED", "false")
    assert config.legacy_event_sync_active() is True
    assert config.legacy_sync_job_active() is True


def test_writeback_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("SAFETY_FIRE_ALARM_WRITEBACK_AI_ENABLED", "true")
    assert config.writeback_ai_enabled() is True
