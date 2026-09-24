"""ehs_change 直读开关单测（Ticket 01）。"""

from __future__ import annotations

import pytest

from app.modules.safety.service.ehs_change_direct import config

ENV_DIRECT = "SAFETY_EHS_CHANGE_DIRECT_ENABLED"
ENV_TTL = "SAFETY_EHS_CHANGE_DIRECT_CACHE_TTL_SECONDS"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_DIRECT, raising=False)
    monkeypatch.delenv(ENV_TTL, raising=False)


class TestDirectEnabled:
    def test_default_off(self) -> None:
        assert config.direct_enabled() is False

    @pytest.mark.parametrize("val", ["1", "true", "yes", "on", "TRUE"])
    def test_on_values(self, monkeypatch: pytest.MonkeyPatch, val: str) -> None:
        monkeypatch.setenv(ENV_DIRECT, val)
        assert config.direct_enabled() is True

    @pytest.mark.parametrize("val", ["0", "false", "", "garbage"])
    def test_off_values(self, monkeypatch: pytest.MonkeyPatch, val: str) -> None:
        monkeypatch.setenv(ENV_DIRECT, val)
        assert config.direct_enabled() is False


class TestCacheTtl:
    def test_default_60(self) -> None:
        assert config.cache_ttl_seconds() == 60

    def test_custom(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_TTL, "30")
        assert config.cache_ttl_seconds() == 30

    def test_invalid_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_TTL, "abc")
        assert config.cache_ttl_seconds() == 60

    def test_minimum_floor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_TTL, "0")
        assert config.cache_ttl_seconds() == 1
