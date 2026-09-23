"""推送对话触发工具测试（V3.0 UAT，2026-09-23）。

接缝：匹配纯函数直测 + 工具端到端（stub push_store + 假件发送，沿
test_push_center / test_confirm_integration 模式）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent.tools import push as push_tool
from app.modules.warehouse.push_center import engine

CN_TZ = ZoneInfo("Asia/Shanghai")
AT_NOW = datetime(2026, 9, 23, 11, 0, tzinfo=CN_TZ)


@dataclass
class StubPushRow:
    task_name: str
    enabled: bool = True
    schedule: dict[str, Any] | None = None
    targets: str | None = None
    note: str | None = None
    is_deleted: bool = False


# ═══════════════════════════════════════════════════════════════
# 匹配纯函数
# ═══════════════════════════════════════════════════════════════


class TestMatchPushTask:
    def test_verbal_prefixes_stripped(self) -> None:
        assert push_tool.match_push_task("推送晨报")[0] == "morning_report"
        assert push_tool.match_push_task("触发低库存预警")[0] == "low_stock_alert"
        assert push_tool.match_push_task("立即推送一下周库存报表吧")[0] == "weekly_stock_report"

    def test_alias_and_label_and_taskname(self) -> None:
        assert push_tool.match_push_task("四态")[0] == "invoice_four_state"
        assert push_tool.match_push_task("超6月与不合格清单")[0] == "stale_lists"
        assert push_tool.match_push_task("morning_report")[0] == "morning_report"
        assert push_tool.match_push_task("用量对比")[0] == "material_usage_compare"
        assert push_tool.match_push_task("年报")[0] == "annual_report"

    def test_ambiguous_returns_none_with_candidates(self) -> None:
        task, candidates = push_tool.match_push_task("清单")
        assert task is None
        assert "stale_lists" in candidates and "finished_disposition_lists" in candidates

    def test_unknown_returns_none(self) -> None:
        task, candidates = push_tool.match_push_task("不存在的推送")
        assert task is None and candidates == []

    def test_event_task_not_matchable(self) -> None:
        # 事件型任务（快递通知等）不参与对话触发
        task, _ = push_tool.match_push_task("快递发货通知")
        assert task is None

    def test_normalize_strips_repeated(self) -> None:
        assert push_tool.normalize_trigger_text("麻烦帮我立即推送一下晨报吧") == "晨报"


# ═══════════════════════════════════════════════════════════════
# 工具端到端（stub store + 假发送）
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def send_capture(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def _fake_send(target: str, card: dict[str, Any], dry_run: bool | None) -> str | None:
        sent.append({"target": target, "title": card["header"]["title"]["content"]})
        return f"om_{len(sent)}"

    from app.modules.warehouse.feishu import notification

    monkeypatch.setattr(notification, "send_card_to_target", _fake_send)
    return sent


def _install_store(
    monkeypatch: pytest.MonkeyPatch, rows: dict[str, StubPushRow]
) -> None:
    from app.modules.warehouse.push_center.store import PushConfigStore

    test_store = PushConfigStore(row_loader=lambda name: rows.get(name))
    monkeypatch.setattr(engine, "push_store", test_store)


async def _run_tool(db: AsyncSession, task: str) -> dict[str, Any]:
    """经注入会话跑工具（绕开 _production_db）。"""

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _patched():
        yield db

    monkeypatch_holder = pytest.MonkeyPatch()
    monkeypatch_holder.setattr(push_tool, "_db_session", _patched)
    try:
        return await push_tool.trigger_push_task(task)
    finally:
        monkeypatch_holder.undo()


class TestTriggerPushTaskTool:
    async def test_success_executes_and_sends(
        self,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        send_capture: list[dict[str, Any]],
    ) -> None:
        """晨报：morning_report 聚合空库也出卡（零数卡），送达 oc_test。"""
        _install_store(
            monkeypatch,
            {"morning_report": StubPushRow(task_name="morning_report", targets="oc_test")},
        )
        result = await _run_tool(db_session, "推送晨报")
        assert result["status"] == "executed"
        assert result["task_name"] == "morning_report"
        assert result["message"] == "推送已执行并送达目标"
        assert send_capture and send_capture[0]["target"] == "oc_test"
        # 推送日志 trigger=manual
        from sqlalchemy import select

        from app.modules.warehouse.models import WarehousePushLog

        logs = (
            await db_session.execute(
                select(WarehousePushLog).where(
                    WarehousePushLog.task_name == "morning_report"
                )
            )
        ).scalars().all()
        assert any(log.trigger == "manual" for log in logs)

    async def test_unknown_task_error_lists_available(
        self, db_session: AsyncSession
    ) -> None:
        result = await _run_tool(db_session, "推送不存在的东西")
        assert "error" in result
        assert "未匹配到推送任务" in result["error"]
        assert "晨报推送" in result["hint"]

    async def test_ambiguous_task_error(
        self, db_session: AsyncSession
    ) -> None:
        result = await _run_tool(db_session, "清单")
        assert "匹配到多个任务" in result["error"]

    async def test_disabled_task_skipped(
        self,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _install_store(
            monkeypatch,
            {"morning_report": StubPushRow(task_name="morning_report", enabled=False)},
        )
        result = await _run_tool(db_session, "推送晨报")
        assert result["status"] == "skipped_disabled"
        assert "停用" in result["message"]

    async def test_no_target_skipped(
        self,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _install_store(
            monkeypatch,
            {"morning_report": StubPushRow(task_name="morning_report", targets=None)},
        )
        result = await _run_tool(db_session, "推送晨报")
        assert result["status"] == "skipped_no_target"

    async def test_registered_in_tool_registry(self) -> None:
        from app.modules.warehouse.agent.tools.query import TOOL_FUNCS

        assert "trigger_push_task" in TOOL_FUNCS
