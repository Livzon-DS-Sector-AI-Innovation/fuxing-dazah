"""key_risk_op 直读开关单测（Ticket 02）。"""

from __future__ import annotations

import pytest

from app.modules.safety.service.key_risk_op_direct import config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "SAFETY_KEY_RISK_OP_DIRECT_ENABLED",
        "SAFETY_KEY_RISK_OP_EVENT_SYNC_ENABLED",
        "SAFETY_KEY_RISK_OP_DIRECT_CACHE_TTL_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)


class TestDefaults:
    def test_all_default_off(self) -> None:
        assert config.direct_enabled() is False
        assert config.event_sync_enabled() is False
        assert config.legacy_event_sync_active() is True  # 全关 = 改造前行为
        assert config.cache_ttl_seconds() == 60

    def test_direct_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SAFETY_KEY_RISK_OP_DIRECT_ENABLED", "true")
        assert config.direct_enabled() is True
        assert config.legacy_event_sync_active() is False

    def test_cache_ttl_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SAFETY_KEY_RISK_OP_DIRECT_CACHE_TTL_SECONDS", "0")
        assert config.cache_ttl_seconds() == 0
        monkeypatch.setenv("SAFETY_KEY_RISK_OP_DIRECT_CACHE_TTL_SECONDS", "300")
        assert config.cache_ttl_seconds() == 300

    def test_legacy_event_sync_combos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SAFETY_KEY_RISK_OP_DIRECT_ENABLED", "true")
        monkeypatch.setenv("SAFETY_KEY_RISK_OP_EVENT_SYNC_ENABLED", "true")
        assert config.legacy_event_sync_active() is True  # 双跑
