"""闸门与开关单测（Ticket 06 验收）。

覆盖：4 个开关默认关闭、旧链路「实际生效」判定语义、事件处理器闸门、
      日报任务双路径切换（含单项开关双跑）、手动同步端点关闭提示。
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.feishu import special_op_bitable_handler as handler
from app.modules.safety.service.special_op_direct import config

DIRECT = "SAFETY_SPECIAL_OP_DIRECT_ENABLED"
EVENT_SYNC = "SAFETY_SPECIAL_OP_EVENT_SYNC_ENABLED"
SYNC_JOB = "SAFETY_SPECIAL_OP_SYNC_JOB_ENABLED"
WRITEBACK = "SAFETY_SPECIAL_OP_WRITEBACK_RISK_ENABLED"
ENVS = (DIRECT, EVENT_SYNC, SYNC_JOB, WRITEBACK)
DAY = date(2026, 9, 14)
CHAT = "oc_x"


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENVS:
        monkeypatch.delenv(name, raising=False)


#  开关本身


def test_switches_default_off_and_legacy_paths_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)

    assert config.direct_enabled() is False
    assert config.event_sync_enabled() is False
    assert config.sync_job_enabled() is False
    assert config.writeback_risk_enabled() is False
    # 默认部署 = 与改造前行为完全一致：旧链路照常运行
    assert config.legacy_event_sync_active() is True
    assert config.legacy_sync_job_active() is True


def test_direct_switch_gates_legacy_paths_and_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv(DIRECT, "true")

    assert config.legacy_event_sync_active() is False
    assert config.legacy_sync_job_active() is False

    # 单项开关可显式恢复旧链路（回滚 / 双跑）
    monkeypatch.setenv(EVENT_SYNC, "true")
    monkeypatch.setenv(SYNC_JOB, "1")
    assert config.legacy_event_sync_active() is True
    assert config.legacy_sync_job_active() is True

    # 一键回滚：关掉直读总开关，旧链路恢复（即使单项开关都是 false）
    monkeypatch.setenv(DIRECT, "false")
    monkeypatch.setenv(EVENT_SYNC, "false")
    monkeypatch.setenv(SYNC_JOB, "false")
    assert config.legacy_event_sync_active() is True
    assert config.legacy_sync_job_active() is True


#  事件处理器闸门


async def test_event_handler_follows_mirror_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    calls: list[tuple[str, str]] = []

    async def fake_upsert(record_id: str) -> None:
        calls.append(("upsert", record_id))

    async def fake_delete(record_id: str) -> None:
        calls.append(("delete", record_id))

    monkeypatch.setattr(handler, "_special_op_app_token", lambda: "app_token")
    monkeypatch.setattr(handler, "_special_op_table_id", lambda: "tbl_x")
    monkeypatch.setattr(handler, "_handle_upsert", fake_upsert)
    monkeypatch.setattr(handler, "_handle_delete", fake_delete)
    event = {
        "file_token": "app_token",
        "table_id": "tbl_x",
        "action_list": [
            {"action": "record_added", "record_id": "rec1"},
            {"action": "record_deleted", "record_id": "rec2"},
        ],
    }
    expected = [("upsert", "rec1"), ("delete", "rec2")]

    # 默认（直读关）：事件镜像照常
    await handler.handle_special_ops_record_changed(dict(event))
    assert calls == expected

    # 直读开：镜像停止，事件不落平台库
    calls.clear()
    monkeypatch.setenv(DIRECT, "true")
    await handler.handle_special_ops_record_changed(dict(event))
    assert calls == []

    # 直读 + 显式打开事件镜像：双跑
    calls.clear()
    monkeypatch.setenv(EVENT_SYNC, "true")
    await handler.handle_special_ops_record_changed(dict(event))
    assert calls == expected


#  日报任务双路径


def _install_scheduler_fakes(
    monkeypatch: pytest.MonkeyPatch, calls: list[Any],
) -> None:
    import app.core.database as db_module
    import app.modules.safety.service.special_op_direct.daily as daily_module
    import app.modules.safety.service.special_operation_daily_report as legacy_module

    class FakeSession:
        def __init__(self) -> None:
            self.commits = 0

        async def commit(self) -> None:
            self.commits += 1

    class FakeSessionCtx:
        def __init__(self, session: FakeSession) -> None:
            self._session = session

        async def __aenter__(self) -> FakeSession:
            return self._session

        async def __aexit__(self, *exc: object) -> bool:
            return False

    class FakeService:
        def __init__(self, session: object) -> None:
            calls.append("service_init")

        async def sync_from_bitable(self) -> int:
            calls.append("sync")
            return 7

        async def check_and_sync_incremental(self) -> dict[str, Any]:
            calls.append("inc")
            return {"status": "fresh"}

        async def generate_and_push(self, **kwargs: Any) -> SimpleNamespace:
            calls.append(("legacy_push", kwargs["mode"]))
            return SimpleNamespace(
                total=1, high_risk=1, medium_risk=0, low_risk=0,
                excluded=0, push_results=[{"success": True}],
            )

    async def fake_direct_run(
        target_date: date, mode: str = "today", **kwargs: Any,
    ) -> SimpleNamespace:
        calls.append(("direct_run", target_date, mode, kwargs.get("target_chats")))
        return SimpleNamespace(
            total=2, high_risk=1, medium_risk=0, low_risk=1,
            excluded=0, push_results=[{"success": True}],
        )

    monkeypatch.setattr(
        db_module, "async_session_factory", lambda: FakeSessionCtx(FakeSession())
    )
    monkeypatch.setattr(
        legacy_module, "SpecialOperationDailyReportService", FakeService
    )
    monkeypatch.setattr(daily_module, "run", fake_direct_run)


async def test_scheduler_switches_between_direct_and_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.safety.scheduler import _run_special_op_daily_report

    calls: list[Any] = []
    _install_scheduler_fakes(monkeypatch, calls)
    _clear_env(monkeypatch)

    # 默认（全关）= 旧路径：08:00 全量对账 + 旧日报
    await _run_special_op_daily_report({"mode": "today"}, DAY, chat_id=CHAT)
    # 旧路径：对账用独立 session，日报再用一个 session -> service 构造两次
    assert calls == [
        "service_init", "sync", "service_init", ("legacy_push", "today"),
    ]

    # 默认（全关）17:00：增量同步 + 旧日报
    calls.clear()
    await _run_special_op_daily_report({"mode": "afternoon"}, DAY, chat_id=CHAT)
    assert calls == [
        "service_init", "inc", "service_init", ("legacy_push", "afternoon"),
    ]

    # 打开直读总开关：直读日报，旧镜像与两个同步任务都停
    calls.clear()
    monkeypatch.setenv(DIRECT, "true")
    await _run_special_op_daily_report({"mode": "today"}, DAY, chat_id=CHAT)
    assert calls == [("direct_run", DAY, "today", [CHAT])]

    # 直读 + 显式打开旧同步：对账保留（双跑），日报仍走直读
    calls.clear()
    monkeypatch.setenv(SYNC_JOB, "true")
    await _run_special_op_daily_report({"mode": "afternoon"}, DAY, chat_id=CHAT)
    assert calls == ["service_init", "inc", ("direct_run", DAY, "afternoon", [CHAT])]

    # 一键回滚：关掉直读 -> 旧路径恢复
    calls.clear()
    monkeypatch.setenv(DIRECT, "false")
    monkeypatch.setenv(SYNC_JOB, "false")
    await _run_special_op_daily_report({"mode": "today"}, DAY, chat_id=CHAT)
    assert calls == [
        "service_init", "sync", "service_init", ("legacy_push", "today"),
    ]


#  手动同步端点


async def test_manual_sync_endpoint_reports_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.safety.api.special_operation_daily_report as api_module

    class FakeService:
        def __init__(self, db: object) -> None:
            self.db = db

        async def sync_from_bitable(self) -> int:
            return 9

    monkeypatch.setattr(
        api_module, "SpecialOperationDailyReportService", FakeService
    )
    _clear_env(monkeypatch)

    # 直读模式：返回「已关闭」提示，不静默失败
    monkeypatch.setenv(DIRECT, "true")
    disabled = await api_module.sync_from_bitable(db=_no_db())
    assert disabled.data == {"synced_count": 0, "disabled": True}
    assert "已关闭" in disabled.message

    # 回滚后：照常同步
    monkeypatch.setenv(DIRECT, "false")
    enabled = await api_module.sync_from_bitable(db=_no_db())
    assert enabled.data == {"synced_count": 9}


def _no_db() -> AsyncSession:
    """占位 session：闸门关闭与假服务的路径不会真正使用它。"""
    return cast(AsyncSession, None)
