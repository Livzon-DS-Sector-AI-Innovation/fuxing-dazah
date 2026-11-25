"""HR 模块后台服务声明（hr/lifecycle.py）的接线回归。

注册点已从 main.py 下沉到各模块 lifecycle（平台 ModuleExtension 契约）。这里钉死 HR 向宿主
声明的内容：定时任务不漏注册、不重复注册（SchedulerRegistry 遇重名直接抛错，服务会启动即崩），
以及试用期时长配置预热确实随框架启动执行、读库失败不外抛。

飞书回调注册函数全部打桩，预热用例也不登记任何真实定时任务——本文件只验证声明，
不触碰平台回调注册表，更不让员工同步这类会外连的任务在测试里跑起来。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.hr import lifecycle
from app.platform.module_lifecycle import (
    ModuleExtension,
    ModuleHost,
    run_module_lifecycles,
)
from app.platform.scheduler import SchedulerRegistry

_CALLBACK_REGISTRARS: tuple[tuple[str, str], ...] = (
    ("app.modules.hr.title_review.bitable_handler", "register_feishu_callbacks"),
    ("app.modules.hr.employee_info_collection_service", "register_feishu_callbacks"),
    ("app.modules.hr.probation_service", "register_feishu_callbacks"),
    ("app.modules.hr.interview_score_service", "register_feishu_callbacks"),
)


def _settings(*, title_review_sync: bool) -> SimpleNamespace:
    return SimpleNamespace(HR_TITLE_REVIEW_SYNC_ENABLED=title_review_sync)


@pytest.fixture
def stubbed_callbacks(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """把四个飞书回调注册函数换成计数桩，返回被调用的模块名。"""
    called: list[str] = []
    for module, attr in _CALLBACK_REGISTRARS:
        monkeypatch.setattr(
            f"{module}.{attr}", lambda module=module: called.append(module)
        )
    return called


# ─── register：任务清单 ───


def test_register_declares_every_hr_task_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
    stubbed_callbacks: list[str],  # noqa: ARG001 — 夹具只为打桩
) -> None:
    """转正提醒只经聚合函数登记一次；员工同步、合同到期提醒、职称同步一个不漏。"""
    monkeypatch.setattr(
        lifecycle, "get_settings", lambda: _settings(title_review_sync=True)
    )
    host = ModuleHost(scheduler=SchedulerRegistry())

    lifecycle.HR_EXTENSION.register(host)

    assert sorted(host.scheduler.tasks) == [
        "hr.contract.approval_sync",
        "hr.contract.reminder",
        "hr.contract.renewal_announcement",
        "hr.employee_sync.reconcile",
        "hr.probation.reminder",
        "hr.title_review.reconcile",
    ]
    assert sorted(stubbed_callbacks) == sorted(
        module for module, _ in _CALLBACK_REGISTRARS
    )


def test_title_review_sync_task_follows_switch(
    monkeypatch: pytest.MonkeyPatch,
    stubbed_callbacks: list[str],  # noqa: ARG001 — 夹具只为打桩
) -> None:
    monkeypatch.setattr(
        lifecycle, "get_settings", lambda: _settings(title_review_sync=False)
    )
    host = ModuleHost(scheduler=SchedulerRegistry())

    lifecycle.HR_EXTENSION.register(host)

    assert "hr.title_review.reconcile" not in host.scheduler.tasks


# ─── 试用期时长配置预热 ───


class _SessionContext:
    """async_session_factory 的替身：记录开过的会话数。"""

    def __init__(self) -> None:
        self.opened = 0

    def __call__(self) -> _SessionContext:
        return self

    async def __aenter__(self) -> object:
        self.opened += 1
        return object()

    async def __aexit__(self, *exc_info: object) -> None:
        return None


class _RecordingLogger:
    """lifecycle.logger 的替身：记下 warning 调用，不依赖全局 logging 配置。"""

    def __init__(self) -> None:
        self.warnings: list[tuple[str, dict[str, object]]] = []

    def warning(self, msg: str, *args: object, **kwargs: object) -> None:
        self.warnings.append((msg, kwargs))


class _WarmupOnlyExtension(ModuleExtension):
    """只声明预热任务，不登记任何真实定时任务。"""

    code = "hr-warmup-test"

    def register(self, host: ModuleHost) -> None:
        host.add_background_loop(
            "hr:probation_config_warmup", lifecycle._warm_probation_config
        )


async def test_probation_config_warmup_runs_at_framework_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """预热随框架启动执行一次：退出上下文时框架会等后台任务收尾，之后即可断言。"""
    reload = AsyncMock()
    monkeypatch.setattr(
        "app.modules.hr.probation_config.reload_probation_config", reload
    )
    factory = _SessionContext()
    monkeypatch.setattr("app.core.database.async_session_factory", factory)

    async with run_module_lifecycles((_WarmupOnlyExtension(),)):
        pass

    assert factory.opened == 1
    reload.assert_awaited_once()


async def test_probation_config_warmup_failure_does_not_break_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """读库失败只告警不外抛：缓存初值即默认时长，转正发起与每日提醒时会再刷新。"""
    monkeypatch.setattr(
        "app.modules.hr.probation_config.reload_probation_config",
        AsyncMock(side_effect=RuntimeError("db down")),
    )
    monkeypatch.setattr("app.core.database.async_session_factory", _SessionContext())
    logger = _RecordingLogger()
    monkeypatch.setattr(lifecycle, "logger", logger)

    async with run_module_lifecycles((_WarmupOnlyExtension(),)):
        pass

    assert [msg for msg, _ in logger.warnings] == [
        "试用期时长配置预热失败，暂用默认时长"
    ]
    assert logger.warnings[0][1].get("exc_info") is True
