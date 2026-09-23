"""msds 直读开关单测（Ticket 03）——默认关 / 打开开 / 非法值回退关。"""

from __future__ import annotations

import pytest

from app.modules.safety.service.msds_direct import config

ENV_DIRECT = "SAFETY_MSDS_DIRECT_ENABLED"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_DIRECT, raising=False)


def test_default_off() -> None:
    assert config.direct_enabled() is False


def test_switch_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_DIRECT, "true")
    assert config.direct_enabled() is True


def test_garbage_value_falls_back_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_DIRECT, "1x")
    assert config.direct_enabled() is False
