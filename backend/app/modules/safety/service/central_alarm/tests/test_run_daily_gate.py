"""审查 m3 补测：run_daily_central_alarm_analysis 的同步兜底闸门三态。

- direct=false（默认）：执行 sync_from_bitable 兜底（现状）
- direct=true：跳过兜底（直读编排自行拉数据）
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.modules.safety.service.central_alarm import service as ca_service


def _patch(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """替身化 sync/generate/commit，记录调用。"""
    calls: dict[str, Any] = {"sync": 0, "generate": 0, "commit": 0}

    class _FakeService:
        def __init__(self, session: Any) -> None:
            pass

        async def sync_from_bitable(self) -> tuple[int, int]:
            calls["sync"] += 1
            return 0, 0

        async def generate_daily_report(self, **kwargs: Any) -> Any:
            calls["generate"] += 1

            class _R:
                push_results: list[dict[str, Any]] = []

            return _R()

    class _FakeSessionFactory:
        def __call__(self) -> Any:
            return self

        async def __aenter__(self) -> Any:
            return _FakeSession()

        async def __aexit__(self, *args: Any) -> None:
            return None

    class _FakeSession:
        async def commit(self) -> None:
            calls["commit"] += 1

    monkeypatch.setattr(ca_service, "CentralAlarmService", _FakeService)
    import app.core.database as db_mod

    monkeypatch.setattr(db_mod, "async_session_factory", _FakeSessionFactory())
    return calls


def _run(coro: Any) -> Any:
    return asyncio.new_event_loop().run_until_complete(coro)


def test_run_daily_sync_fallback_when_direct_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SAFETY_CENTRAL_ALARM_DIRECT_ENABLED", raising=False)
    calls = _patch(monkeypatch)
    _run(ca_service.run_daily_central_alarm_analysis())
    assert calls["sync"] == 1
    assert calls["generate"] == 1
    assert calls["commit"] == 1  # 生成后 commit（镜像路径写 AI 字段）


def test_run_daily_skips_sync_when_direct_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAFETY_CENTRAL_ALARM_DIRECT_ENABLED", "true")
    calls = _patch(monkeypatch)
    _run(ca_service.run_daily_central_alarm_analysis())
    assert calls["sync"] == 0  # 直读模式：跳过镜像同步兜底
    assert calls["generate"] == 1
    assert calls["commit"] == 0  # 直读路径零 DB 写
