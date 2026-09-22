"""contractor_admission 直读开关单测（Ticket 06）。"""

from __future__ import annotations

import pytest

from app.modules.safety.service.contractor_admission_direct import config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "SAFETY_CONTRACTOR_ADMISSION_DIRECT_ENABLED",
        "SAFETY_CONTRACTOR_ADMISSION_EVENT_SYNC_ENABLED",
        "SAFETY_CONTRACTOR_ADMISSION_WRITEBACK_AI_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)


class TestDefaults:
    def test_all_default_off(self) -> None:
        assert config.direct_enabled() is False
        assert config.event_sync_enabled() is False
        assert config.writeback_ai_enabled() is False
        assert config.legacy_event_sync_active() is True  # 全关 = 改造前行为

    def test_direct_on_stops_legacy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SAFETY_CONTRACTOR_ADMISSION_DIRECT_ENABLED", "true")
        assert config.direct_enabled() is True
        assert config.legacy_event_sync_active() is False

    def test_dual_run_combo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SAFETY_CONTRACTOR_ADMISSION_DIRECT_ENABLED", "true")
        monkeypatch.setenv("SAFETY_CONTRACTOR_ADMISSION_EVENT_SYNC_ENABLED", "true")
        assert config.legacy_event_sync_active() is True  # 双跑

    def test_writeback_ai_does_not_affect_legacy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """WRITEBACK_AI 只罩直读模式回写步；不影响 legacy 链路生效判定。"""
        monkeypatch.setenv("SAFETY_CONTRACTOR_ADMISSION_WRITEBACK_AI_ENABLED", "true")
        assert config.writeback_ai_enabled() is True
        assert config.legacy_event_sync_active() is True
