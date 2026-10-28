"""Agent 执行面三期（agent-action-p3）运维触发两件测试。

覆盖 spec（.scratch/agent-action-p3/spec.md）T5：
sync_domain_data（fire/central/key_risk/special_op 四域手动同步）/
run_workticket_review（手动跑作业票审核，push 固定 False）。
仅 safety_admin。确认流三路径照二期打桩模式（本批代表②）。

测试接缝：工具函数边界直接调用；各域 service 方法与直读闸门函数打桩。
"""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.business_agent import tool_selector
from app.modules.safety.business_agent.core.permissions import (
    ROLE_DEPT_LEADER,
    ROLE_INSPECTOR,
    ROLE_SAFETY_ADMIN,
    ROLE_VIEWER,
    check,
)
from app.modules.safety.business_agent.tools import registry
from app.modules.safety.business_agent.tools.ops_action_tools import (
    run_workticket_review,
    sync_domain_data,
)


def _run(coro: Any) -> Any:
    import asyncio

    return asyncio.run(coro)


def _ctx(db: Any = None, role: str = "safety_admin") -> SimpleNamespace:
    return SimpleNamespace(
        deps=SimpleNamespace(
            db=db or SimpleNamespace(), person=None, role=role,
            session_id="s1", channel="test",
        )
    )


def _stub(monkeypatch: pytest.MonkeyPatch, cls_path: str, method: str, ret: Any) -> list:
    """打桩 <cls_path>.<method> 类方法；返回调用记录列表。"""
    import importlib

    mod_path, cls_name = cls_path.rsplit(".", 1)
    cls = getattr(importlib.import_module(mod_path), cls_name)
    calls: list[dict] = []

    async def fake(self, *args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        if isinstance(ret, Exception):
            raise ret
        return ret

    monkeypatch.setattr(cls, method, fake)
    return calls


def _gate(monkeypatch: pytest.MonkeyPatch, mod: str, func: str, value: bool) -> None:
    import importlib

    monkeypatch.setattr(importlib.import_module(mod), func, lambda: value)


# ═══ 接线 ═══


class TestOpsActionWiring:
    def test_tool_kind_write(self) -> None:
        assert registry.TOOL_KIND["sync_domain_data"] is True
        assert registry.TOOL_KIND["run_workticket_review"] is True

    def test_group_mounted(self) -> None:
        group = tool_selector.TOOL_GROUPS["ops"]
        assert "sync_domain_data" in group
        assert "run_workticket_review" in group

    @pytest.mark.parametrize(
        "message",
        [
            "手动同步一下消防报警",
            "把中控数据补同步一下",
            "跑一次作业票审核",
        ],
    )
    def test_route_hits_ops(self, message: str) -> None:
        decision = tool_selector.route_message(message)
        sync_tools = set(tool_selector.TOOL_GROUPS["ops"]) | set(
            tool_selector.TOOL_GROUPS["work_ticket"]
        )
        assert sync_tools & set(decision.tool_names), (
            f"{message} 未命中运维挂载: {decision}"
        )

    def test_permissions_admin_only(self) -> None:
        for tool in ("sync_domain_data", "run_workticket_review"):
            assert check(ROLE_SAFETY_ADMIN, tool)
            assert not check(ROLE_DEPT_LEADER, tool)
            assert not check(ROLE_INSPECTOR, tool)
            assert not check(ROLE_VIEWER, tool)


# ═══ sync_domain_data ═══


class TestSyncDomainData:
    def test_fire_sync_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _gate(
            monkeypatch,
            "app.modules.safety.service.fire_alarm.config",
            "legacy_sync_job_active", True,
        )
        calls = _stub(
            monkeypatch,
            "app.modules.safety.service.fire_alarm.service.FireAlarmService",
            "sync_from_bitable", (5, 2),
        )
        out = _run(sync_domain_data(_ctx(), domain="fire"))
        assert out["success"] is True
        assert out["skipped"] is False
        assert out["stats"] == {"synced_count": 5, "soft_deleted_count": 2}
        assert len(calls) == 1

    def test_fire_gate_closed_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _gate(
            monkeypatch,
            "app.modules.safety.service.fire_alarm.config",
            "legacy_sync_job_active", False,
        )
        calls = _stub(
            monkeypatch,
            "app.modules.safety.service.fire_alarm.service.FireAlarmService",
            "sync_from_bitable", (0, 0),
        )
        out = _run(sync_domain_data(_ctx(), domain="fire"))
        assert out["success"] is True  # 不是错误：如实告知无需同步
        assert out["skipped"] is True
        assert calls == []  # 闸门关时不触 service

    def test_central_direct_mode_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _gate(
            monkeypatch,
            "app.modules.safety.service.central_alarm.config",
            "direct_enabled", True,
        )
        calls = _stub(
            monkeypatch,
            "app.modules.safety.service.central_alarm.service.CentralAlarmService",
            "sync_from_bitable", (0, 0),
        )
        out = _run(sync_domain_data(_ctx(), domain="central"))
        assert out["skipped"] is True
        assert calls == []

    def test_key_risk_sync_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = _stub(
            monkeypatch,
            "app.modules.safety.service.key_risk_operation_report.KeyRiskOperationReportService",
            "sync_from_bitable",
            {"created": 3, "updated": 1, "deleted": 0, "skipped_deleted": 2},
        )
        out = _run(sync_domain_data(_ctx(), domain="key_risk"))
        assert out["success"] is True
        assert out["stats"]["created"] == 3
        assert len(calls) == 1

    def test_key_risk_direct_mode_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(
            monkeypatch,
            "app.modules.safety.service.key_risk_operation_report.KeyRiskOperationReportService",
            "sync_from_bitable",
            {"skipped": True, "reason": "direct_mode"},
        )
        out = _run(sync_domain_data(_ctx(), domain="key_risk"))
        assert out["success"] is True
        assert out["skipped"] is True
        assert "直读" in out["message"]

    def test_special_op_sync_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _gate(
            monkeypatch,
            "app.modules.safety.service.special_op_direct.config",
            "legacy_sync_job_active", True,
        )
        _stub(
            monkeypatch,
            "app.modules.safety.service.special_operation_daily_report.SpecialOperationDailyReportService",
            "sync_from_bitable", 41,
        )
        out = _run(sync_domain_data(_ctx(), domain="special_op"))
        assert out["success"] is True
        assert out["stats"] == {"synced_count": 41}

    def test_special_op_gate_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _gate(
            monkeypatch,
            "app.modules.safety.service.special_op_direct.config",
            "legacy_sync_job_active", False,
        )
        out = _run(sync_domain_data(_ctx(), domain="special_op"))
        assert out["skipped"] is True
        assert "直读" in out["message"] or "镜像" in out["message"]

    def test_invalid_domain(self) -> None:
        out = _run(sync_domain_data(_ctx(), domain="hr"))
        assert out["success"] is False
        assert "fire" in out["message"] and "key_risk" in out["message"]

    def test_service_error_not_raised(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _gate(
            monkeypatch,
            "app.modules.safety.service.fire_alarm.config",
            "legacy_sync_job_active", True,
        )
        _stub(
            monkeypatch,
            "app.modules.safety.service.fire_alarm.service.FireAlarmService",
            "sync_from_bitable", RuntimeError("Bitable 超时"),
        )
        out = _run(sync_domain_data(_ctx(), domain="fire"))
        assert out["success"] is False
        assert "Bitable 超时" in out["message"]


# ═══ run_workticket_review ═══


class TestRunWorkticketReview:
    def _stub_review(self, monkeypatch: pytest.MonkeyPatch, ret: Any = None) -> list:
        """整类打桩：构造器本机无平台凭据会抛错，必须连构造一起桩掉。"""
        import app.modules.safety.workticket_review.service as svc_mod

        default_ret = {
            "date": "2026-10-27", "total": 12, "reviewed": 12,
            "violation_count": 3, "compliant_count": 8,
            "data_insufficient": 1, "markdown_report": "# 很长的报告",
            "push_result": None, "message_id": None,
        }
        the_ret = default_ret if ret is None else ret
        calls: list[dict] = []

        class _FakeService:
            def __init__(self, db, chat_id=None, **kwargs):
                calls.append({"ctor": {"chat_id": chat_id}})

            async def run_review(self, review_date, push=True):
                calls.append({"review_date": review_date, "push": push})
                if isinstance(the_ret, Exception):
                    raise the_ret
                return the_ret

        monkeypatch.setattr(svc_mod, "WorkTicketReviewService", _FakeService)
        return calls

    def test_default_date_today(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = self._stub_review(monkeypatch)
        out = _run(run_workticket_review(_ctx()))
        assert out["success"] is True
        assert calls[1]["review_date"] == date.today()
        assert calls[1]["push"] is False

    def test_explicit_date(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = self._stub_review(monkeypatch)
        out = _run(run_workticket_review(_ctx(), date="2026-10-27"))
        assert out["success"] is True
        assert calls[1]["review_date"] == date(2026, 10, 27)
        assert out["total"] == 12 and out["violation_count"] == 3

    def test_markdown_not_in_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._stub_review(monkeypatch)
        out = _run(run_workticket_review(_ctx(), date="2026-10-27"))
        assert "markdown_report" not in out

    def test_invalid_date(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._stub_review(monkeypatch)
        out = _run(run_workticket_review(_ctx(), date="10月27日"))
        assert out["success"] is False
        assert "日期" in out["message"]

    def test_service_error_not_raised(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._stub_review(monkeypatch, ret=RuntimeError("平台接口不可用"))
        out = _run(run_workticket_review(_ctx()))
        assert out["success"] is False
        assert "平台接口不可用" in out["message"]


# ═══ 确认流三路径（本批代表②）═══


class TestSyncConfirmationFlow:
    def _history_raw(self) -> list[dict]:
        from pydantic_ai.messages import (
            ModelMessagesTypeAdapter,
            ModelRequest,
            UserPromptPart,
        )

        base = json.loads(
            ModelMessagesTypeAdapter.dump_json(
                [ModelRequest(parts=[UserPromptPart(content="手动同步一下消防报警")])]
            )
        )
        from app.modules.safety.business_agent import executor
        from app.modules.safety.business_agent.schemas import PendingActionData

        pending = PendingActionData(
            tool_name="sync_domain_data",
            arguments={"domain": "fire"},
            summary="手动同步消防报警镜像 sync_domain_data(fire)",
        )
        return executor._append_delegated_tool_call(base, pending)

    def _install_stubs(self, monkeypatch: pytest.MonkeyPatch) -> dict:
        from app.modules.safety.business_agent import executor

        captured: dict = {}

        class _FakeDb:
            async def execute(self, stmt: Any) -> Any:
                return SimpleNamespace(scalar_one=lambda: 0)

            async def flush(self) -> None:
                return None

            def add(self, obj: Any) -> None:
                return None

        async def fake_agent_run(user_message, deps, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                output="已同步", all_messages=lambda: [],
                new_messages=lambda: [],
            )

        async def fake_events(deps, result):
            return None

        async def fake_audit(*args, **kwargs):
            return None

        monkeypatch.setattr(executor, "_agent_run", fake_agent_run)
        monkeypatch.setattr(executor, "_record_tool_events", fake_events)
        monkeypatch.setattr(executor, "_audit_agent_resume", fake_audit)
        return captured

    def _resume(self, monkeypatch: pytest.MonkeyPatch, role: str, approved: bool) -> Any:
        from app.modules.safety.business_agent import executor
        from app.modules.safety.business_agent.schemas import SafetyDeps

        captured = self._install_stubs(monkeypatch)
        sid = "11111111-2222-3333-4444-555555555555"
        deps = SafetyDeps(
            db=SimpleNamespace(), person=None, role=role,
            session_id=sid, channel="test",
        )
        import asyncio

        out = asyncio.run(executor.resume(
            sid, deps, action_id="action-1", approved=approved,
            message_history_raw=self._history_raw(),
        ))
        return out, captured

    def test_approved_grants_tool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        out, captured = self._resume(monkeypatch, role="safety_admin", approved=True)
        assert out["executed"] is True
        assert captured["resume_tool_names"] == ["sync_domain_data"]
        assert list(captured["deferred_tool_results"].approvals.values()) == [True]

    def test_cancelled_denies_tool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pydantic_ai.tools import ToolDenied

        out, captured = self._resume(monkeypatch, role="safety_admin", approved=False)
        value = list(captured["deferred_tool_results"].approvals.values())[0]
        assert isinstance(value, ToolDenied)

    def test_low_role_denied_with_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pydantic_ai.tools import ToolDenied

        out, captured = self._resume(monkeypatch, role="dept_leader", approved=True)
        value = list(captured["deferred_tool_results"].approvals.values())[0]
        assert isinstance(value, ToolDenied)
        assert "权限不足" in str(value)
