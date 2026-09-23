"""hazard_id 直读开关单测——默认关 / 打开开 / 非法值回退关 / TTL 默认与覆盖。"""

from __future__ import annotations

import pytest

from app.modules.safety.service.hazard_id_direct import config

ENV_DIRECT = "SAFETY_HAZARD_ID_DIRECT_ENABLED"
ENV_TTL = "SAFETY_HAZARD_ID_DIRECT_CACHE_TTL_SECONDS"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_DIRECT, raising=False)
    monkeypatch.delenv(ENV_TTL, raising=False)


def test_default_off() -> None:
    assert config.direct_enabled() is False


def test_switch_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_DIRECT, "true")
    assert config.direct_enabled() is True


def test_garbage_value_falls_back_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_DIRECT, "1x")
    assert config.direct_enabled() is False


def test_ttl_default_60() -> None:
    assert config.cache_ttl_seconds() == 60


def test_ttl_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_TTL, "30")
    assert config.cache_ttl_seconds() == 30


def test_ttl_minimum_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_TTL, "0")
    assert config.cache_ttl_seconds() == 1
