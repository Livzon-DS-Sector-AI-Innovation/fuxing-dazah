"""周期报告（周报/月报）调度入口与注册单测——ticket 03 RED。

- run_weekly/run_monthly：镜像模式 sync 兜底 + channel=system + 推送失败上抛
- SCHEDULED_JOBS / REPORT_TYPE_JOBS / EFFECTIVE_TARGET_ENV 注册契约
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.modules.safety.service.central_alarm import service as ca_service


def _patch(monkeypatch: pytest.MonkeyPatch, *, push_ok: bool = True) -> dict[str, Any]:
    """替身化 sync/generate/commit，记录调用与 kind。"""
    calls: dict[str, Any] = {"sync": 0, "kinds": [], "commit": 0}

    class _R:
        push_results: list[dict[str, Any]] = (
            [{"chat_id": "oc_x", "success": True}] if push_ok
            else [{"chat_id": "oc_x", "success": False, "error": "boom"}]
        )

    class _FakeService:
        def __init__(self, session: Any) -> None:
            pass

        async def sync_from_bitable(self) -> tuple[int, int]:
            calls["sync"] += 1
            return 0, 0

        async def generate_period_report(self, kind: str, *a: Any, **kw: Any) -> Any:
            calls["kinds"].append(kind)
            calls["push"] = kw.get("push")
            calls["channel"] = kw.get("channel")
            return _R()

    class _FakeSession:
        async def commit(self) -> None:
            calls["commit"] += 1

    class _FakeSessionFactory:
        def __call__(self) -> Any:
            return self

        async def __aenter__(self) -> Any:
            return _FakeSession()

        async def __aexit__(self, *args: Any) -> None:
            return None

    monkeypatch.setattr(ca_service, "CentralAlarmService", _FakeService)
    import app.core.database as db_mod

    monkeypatch.setattr(db_mod, "async_session_factory", _FakeSessionFactory())
    return calls


def _run(coro: Any) -> Any:
    return asyncio.new_event_loop().run_until_complete(coro)


def test_run_weekly_mirror_sync_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SAFETY_CENTRAL_ALARM_DIRECT_ENABLED", raising=False)
    calls = _patch(monkeypatch)
    _run(ca_service.run_weekly_central_alarm_analysis())
    assert calls["sync"] == 1
    assert calls["kinds"] == ["weekly"]
    assert calls["push"] is True and calls["channel"] == "system"
    assert calls["commit"] == 1


def test_run_monthly_direct_skips_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAFETY_CENTRAL_ALARM_DIRECT_ENABLED", "true")
    calls = _patch(monkeypatch)
    _run(ca_service.run_monthly_central_alarm_analysis())
    assert calls["sync"] == 0
    assert calls["kinds"] == ["monthly"]
    assert calls["commit"] == 0


def test_run_weekly_push_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAFETY_CENTRAL_ALARM_DIRECT_ENABLED", "true")
    _patch(monkeypatch, push_ok=False)
    with pytest.raises(RuntimeError, match="周报推送失败"):
        _run(ca_service.run_weekly_central_alarm_analysis())


def test_run_monthly_push_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAFETY_CENTRAL_ALARM_DIRECT_ENABLED", "true")
    _patch(monkeypatch, push_ok=False)
    with pytest.raises(RuntimeError, match="月报推送失败"):
        _run(ca_service.run_monthly_central_alarm_analysis())


# ── 注册契约 ──


def test_scheduled_jobs_registered() -> None:
    from app.modules.safety.scheduler import SCHEDULED_JOBS

    jobs = {j["name"]: j for j in SCHEDULED_JOBS}
    weekly = jobs.get("中控报警周报")
    assert weekly is not None, "SCHEDULED_JOBS 缺「中控报警周报」"
    assert (weekly["hour"], weekly["minute"], weekly["dow"]) == (8, 40, 0)
    assert weekly.get("dom") is None            # 每周任务不带 dom
    assert weekly.get("enabled", True) is True  # 默认开
    assert (weekly["retry_until_hour"], weekly["retry_until_minute"]) == (23, 30)

    monthly = jobs.get("中控报警月报")
    assert monthly is not None, "SCHEDULED_JOBS 缺「中控报警月报」"
    assert (monthly["hour"], monthly["minute"], monthly["dom"]) == (8, 50, 1)
    assert monthly.get("dow") is None
    assert monthly.get("enabled", True) is True
    assert (monthly["retry_until_hour"], monthly["retry_until_minute"]) == (23, 30)


def test_report_type_and_env_target_registered() -> None:
    from app.modules.safety.service.scheduler_config import (
        EFFECTIVE_TARGET_ENV,
        REPORT_TYPE_JOBS,
    )

    assert "中控报警周报" in REPORT_TYPE_JOBS
    assert "中控报警月报" in REPORT_TYPE_JOBS
    assert EFFECTIVE_TARGET_ENV["中控报警周报"] == "SAFETY_CENTRAL_ALARM_ANALYSIS_CHAT_ID"
    assert EFFECTIVE_TARGET_ENV["中控报警月报"] == "SAFETY_CENTRAL_ALARM_ANALYSIS_CHAT_ID"


def test_run_weekly_extra_group_failure_not_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """加发群失败（best_effort）不上抛：只有总卡主通道失败才走补发重试。"""
    monkeypatch.setenv("SAFETY_CENTRAL_ALARM_DIRECT_ENABLED", "true")

    class _R:
        push_results: list[dict[str, Any]] = [
            {"chat_id": "oc_digest", "success": True},
            {"chat_id": "oc_extra", "success": False, "best_effort": True},
        ]

    class _FakeService:
        def __init__(self, session: Any) -> None:
            pass

        async def generate_period_report(self, kind: str, *a: Any, **kw: Any) -> Any:
            return _R()

    class _FakeSessionFactory:
        def __call__(self) -> Any:
            return self

        async def __aenter__(self) -> Any:
            return object()

        async def __aexit__(self, *args: Any) -> None:
            return None

    monkeypatch.setattr(ca_service, "CentralAlarmService", _FakeService)
    import app.core.database as db_mod

    monkeypatch.setattr(db_mod, "async_session_factory", _FakeSessionFactory())
    result = _run(ca_service.run_weekly_central_alarm_analysis())
    assert result is not None  # 未抛异常即通过
