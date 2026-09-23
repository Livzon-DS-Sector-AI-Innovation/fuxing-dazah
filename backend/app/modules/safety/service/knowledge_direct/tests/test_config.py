"""knowledge 直读开关单测（Ticket 03）。"""

from __future__ import annotations

import pytest

from app.modules.safety.service.knowledge_direct import config as direct_config

ENV_DIRECT = "SAFETY_KNOWLEDGE_DIRECT_ENABLED"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_DIRECT, raising=False)


def test_default_off() -> None:
    assert direct_config.direct_enabled() is False


def test_env_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_DIRECT, "true")
    assert direct_config.direct_enabled() is True


def test_env_truthy_values_on(monkeypatch: pytest.MonkeyPatch) -> None:
    for val in ("1", "yes", "on"):
        monkeypatch.setenv(ENV_DIRECT, val)
        assert direct_config.direct_enabled() is True


def test_env_unrecognized_value_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无法识别的值按 default=False 处理（gates.flag 口径）。"""
    monkeypatch.setenv(ENV_DIRECT, "maybe")
    assert direct_config.direct_enabled() is False
