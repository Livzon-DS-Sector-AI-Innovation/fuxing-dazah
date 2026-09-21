"""Ticket 02：中控报警直读开关单测（照消防 test_config 口径）。"""

from __future__ import annotations

import pytest

from app.modules.safety.service.central_alarm import config


def test_defaults_all_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAFETY_CENTRAL_ALARM_DIRECT_ENABLED", raising=False)
    monkeypatch.delenv("SAFETY_CENTRAL_ALARM_EVENT_SYNC_ENABLED", raising=False)
    monkeypatch.delenv("SAFETY_CENTRAL_ALARM_SYNC_JOB_ENABLED", raising=False)
    assert config.direct_enabled() is False
    assert config.event_sync_enabled() is False
    assert config.sync_job_enabled() is False


def test_legacy_active_when_direct_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAFETY_CENTRAL_ALARM_DIRECT_ENABLED", raising=False)
    monkeypatch.delenv("SAFETY_CENTRAL_ALARM_EVENT_SYNC_ENABLED", raising=False)
    monkeypatch.delenv("SAFETY_CENTRAL_ALARM_SYNC_JOB_ENABLED", raising=False)
    # 总开关关闭 → 旧链路照常（与改造前行为一致）
    assert config.legacy_event_sync_active() is True
    assert config.legacy_sync_job_active() is True


def test_legacy_inactive_when_direct_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAFETY_CENTRAL_ALARM_DIRECT_ENABLED", "true")
    monkeypatch.delenv("SAFETY_CENTRAL_ALARM_EVENT_SYNC_ENABLED", raising=False)
    monkeypatch.delenv("SAFETY_CENTRAL_ALARM_SYNC_JOB_ENABLED", raising=False)
    assert config.direct_enabled() is True
    assert config.legacy_event_sync_active() is False
    assert config.legacy_sync_job_active() is False


def test_legacy_single_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAFETY_CENTRAL_ALARM_DIRECT_ENABLED", "true")
    monkeypatch.setenv("SAFETY_CENTRAL_ALARM_EVENT_SYNC_ENABLED", "true")
    assert config.legacy_event_sync_active() is True  # 单项显式恢复
