"""2-D URS 域 Agent 委派试点：开关路由 / delegate 元工具 / 挂起传播。

接缝（公共行为，不测内部实现）：
- 路由：SAFETY_AGENT_URS_DELEGATION 开 → urs 意图挂「核心集+delegate」；
  关 → 挂载式 9 工具（一键回退）
- delegate 元工具：未知域报错 / 正常回传 / DeferredToolRequests 透传为待确认结构
- 挂起传播：executor 提取 delegate 透传写请求 → 合成 ToolCallPart →
  resume 的 _find_deferred_in_history 能找到（确认门/审计链路复用）

依据：.scratch/safety-agent-optimization-p2/spec.md 2-D 节。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest


def _patch_delegation(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    from app.modules.safety.business_agent import tool_selector

    monkeypatch.setattr(tool_selector, "_urs_delegation_enabled", lambda: enabled)


# ── 路由开关两态 ─────────────────────────────────────────────────


def test_routing_off_keeps_mounted_urs_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """开关关（默认）= 挂载式：urs 意图挂整域工具（含 9 个 URS 工具）。"""
    from app.modules.safety.business_agent.tool_selector import (
        TOOL_GROUPS,
        route_message,
    )

    _patch_delegation(monkeypatch, enabled=False)
    decision = route_message("帮我发起一个 URS 智能审核")
    assert "urs" in decision.domains
    assert decision.path == "rule"
    for tool in TOOL_GROUPS["urs"]:
        if tool == "delegate":
            continue  # 开关关时 delegate 元工具不挂载（一键回退干净）
        assert tool in decision.tool_names
    assert "create_urs_review" in decision.tool_names
    assert "delegate" not in decision.tool_names


def test_routing_on_mounts_core_plus_delegate(monkeypatch: pytest.MonkeyPatch) -> None:
    """开关开 = 委派式：挂核心兜底集 + delegate，不挂 URS 域工具。"""
    from app.modules.safety.business_agent.tool_selector import (
        CORE_FALLBACK_TOOLS,
        route_message,
    )

    _patch_delegation(monkeypatch, enabled=True)
    decision = route_message("帮我发起一个 URS 智能审核")
    assert "urs" in decision.domains
    assert decision.path == "rule"
    assert "delegate" in decision.tool_names
    assert set(CORE_FALLBACK_TOOLS) <= set(decision.tool_names)
    assert "create_urs_review" not in decision.tool_names
    assert "run_urs_assessment" not in decision.tool_names


def test_delegation_toggle_does_not_affect_other_domains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_delegation(monkeypatch, enabled=True)
    from app.modules.safety.business_agent.tool_selector import route_message

    decision = route_message("查一下生产部未整改的隐患")
    assert "hazard" in decision.domains
    assert "query_hazards" in decision.tool_names
    assert "delegate" not in decision.tool_names


# ── 域 Agent 构建 ────────────────────────────────────────────────


def test_get_domain_agent_builds_and_caches() -> None:
    """域 Agent 可构建且进程内缓存复用（同配置同 prompt mtime → 同实例）。"""
    from pydantic_ai import Agent

    import app.modules.safety.business_agent.agent as agent_mod

    agent_mod._DOMAIN_AGENT_CACHE.clear()
    try:
        agent = agent_mod.get_domain_agent("urs")
        assert isinstance(agent, Agent)
        assert agent_mod.get_domain_agent("urs") is agent
    finally:
        agent_mod._DOMAIN_AGENT_CACHE.clear()


def test_get_domain_agent_unknown_domain_raises() -> None:
    from app.modules.safety.business_agent.agent import get_domain_agent

    with pytest.raises(ValueError, match="未知域"):
        get_domain_agent("nonexistent_domain")


def test_domain_agent_prompt_hot_reload(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """域 prompt 改动（mtime 变化）→ 新缓存 key → 新实例。"""
    import app.modules.safety.business_agent.agent as agent_mod

    monkeypatch.setattr(agent_mod, "_DOMAIN_AGENT_CACHE", {})
    a1 = agent_mod.get_domain_agent("urs")
    prompt = agent_mod._DOMAIN_PROMPTS_DIR / "urs.md"
    st = prompt.stat()
    import os

    prompt.write_text(prompt.read_text(encoding="utf-8") + "\n<!-- v2 -->\n", encoding="utf-8")
    os.utime(prompt, (st.st_atime, st.st_mtime + 10))
    try:
        a2 = agent_mod.get_domain_agent("urs")
        assert a1 is not a2
    finally:
        prompt.write_text(
            prompt.read_text(encoding="utf-8").replace("\n<!-- v2 -->\n", ""), encoding="utf-8"
        )
        os.utime(prompt, (st.st_atime, st.st_mtime))
        agent_mod._DOMAIN_AGENT_CACHE.clear()


# ── delegate 元工具行为 ──────────────────────────────────────────


def _fake_run_result(output):
    return SimpleNamespace(output=output, all_messages=lambda: [])


def test_delegate_unknown_domain() -> None:
    from app.modules.safety.business_agent.tools.delegate import delegate

    ctx = SimpleNamespace(deps=SimpleNamespace(role="safety_admin"))
    out = asyncio.run(delegate(ctx, "finance", "随便"))
    assert "error" in out and "urs" in out["error"]


def test_delegate_relays_sub_agent_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.safety.business_agent.tools import delegate as delegate_mod

    class _FakeAgent:
        async def run(self, query, *, deps=None, message_history=None):
            return _fake_run_result("URS 记录共 3 条，均已评估")

    monkeypatch.setattr(
        "app.modules.safety.business_agent.agent.get_domain_agent", lambda d: _FakeAgent()
    )
    ctx = SimpleNamespace(deps=SimpleNamespace(role="safety_admin"))
    out = asyncio.run(delegate_mod.delegate(ctx, "urs", "查 URS 记录"))
    assert out["deferred"] is False
    assert "3 条" in out["reply"]


def test_delegate_translates_deferral_not_executes(monkeypatch: pytest.MonkeyPatch) -> None:
    """子 Agent DeferredToolRequests → 透传待确认结构（绝不代为执行）。"""
    from pydantic_ai import DeferredToolRequests
    from pydantic_ai.messages import ToolCallPart

    from app.modules.safety.business_agent.tools import delegate as delegate_mod

    part = ToolCallPart(
        tool_name="create_urs_review",
        args={"equipment_name": "反应釜", "department": "生产部"},
        tool_call_id="sub-1",
    )

    class _FakeAgent:
        async def run(self, query, *, deps=None, message_history=None):
            return _fake_run_result(DeferredToolRequests(approvals=[part]))

    monkeypatch.setattr(
        "app.modules.safety.business_agent.agent.get_domain_agent", lambda d: _FakeAgent()
    )
    ctx = SimpleNamespace(deps=SimpleNamespace(role="safety_admin"))
    out = asyncio.run(delegate_mod.delegate(ctx, "urs", "发起 URS 审核"))
    assert out["deferred"] is True
    assert out["tool_name"] == "create_urs_review"
    assert out["arguments"]["equipment_name"] == "反应釜"
    assert "确认" in out["message"]


# ── 挂起传播：提取 + 合成 + resume 可见性 ────────────────────────


def _run_result_with_delegate_return(content: dict):
    """构造含 delegate ToolReturnPart 的伪 run result。"""
    from pydantic_ai.messages import ModelResponse, TextPart, ToolReturnPart

    part = ToolReturnPart(tool_name="delegate", content=content, tool_call_id="tc-1")
    text = ModelResponse(parts=[TextPart(content="请确认上述操作")])

    class _Result:
        output = "请确认上述操作"

        def all_messages(self):
            return [text, ModelResponse(parts=[part])]

    return _Result()


def test_extract_delegated_deferral() -> None:
    from app.modules.safety.business_agent.executor import _extract_delegated_deferral

    result = _run_result_with_delegate_return(
        {
            "deferred": True,
            "tool_name": "create_urs_review",
            "arguments": {"equipment_name": "反应釜"},
            "summary": "URS 域子流程请求执行写操作 create_urs_review",
        }
    )
    pending = _extract_delegated_deferral(result)
    assert pending is not None
    assert pending.tool_name == "create_urs_review"
    assert pending.arguments == {"equipment_name": "反应釜"}
    assert "create_urs_review" in pending.summary


def test_extract_delegated_deferral_ignores_normal_return() -> None:
    from app.modules.safety.business_agent.executor import _extract_delegated_deferral

    result = _run_result_with_delegate_return({"deferred": False, "reply": "3 条"})
    assert _extract_delegated_deferral(result) is None


def test_delegated_tool_call_visible_to_resume_finder() -> None:
    """合成 ToolCallPart 后，resume 的 _find_deferred_in_history 能找到挂起。"""
    from pydantic_ai.messages import (
        ModelMessagesTypeAdapter,
        ModelRequest,
        UserPromptPart,
    )

    from app.modules.safety.business_agent.executor import (
        _append_delegated_tool_call,
        _find_deferred_in_history,
    )
    from app.modules.safety.business_agent.schemas import PendingActionData

    pending = PendingActionData(
        tool_name="create_urs_review",
        arguments={"equipment_name": "反应釜"},
        summary="URS 域子流程请求执行写操作",
    )
    base = json.loads(
        ModelMessagesTypeAdapter.dump_json(
            [ModelRequest(parts=[UserPromptPart(content="发起 URS 审核")])]
        )
    )
    raw = _append_delegated_tool_call(base, pending)
    messages = ModelMessagesTypeAdapter.validate_python(raw)
    deferred = _find_deferred_in_history(messages)
    assert deferred is not None
    assert deferred.approvals, "resume 应能从合成消息中重建挂起请求"
    assert deferred.approvals[0].tool_name == "create_urs_review"


# ── 委派挂起走现有 resume 链路（集成）────────────────────────────


def test_delegated_pending_resumes_through_existing_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """确认后的委派写请求 → resume() 以既有 DeferredToolResults 机制继续执行。"""
    from pydantic_ai.messages import (
        ModelMessagesTypeAdapter,
        ModelRequest,
        UserPromptPart,
    )

    from app.modules.safety.business_agent import executor
    from app.modules.safety.business_agent.schemas import PendingActionData, SafetyDeps

    # ① 组装含合成委派写调用的消息历史（run_turn 委派挂起分支的输出形态）
    pending = PendingActionData(
        tool_name="create_urs_review",
        arguments={"equipment_name": "反应釜"},
        summary="URS 域子流程请求执行写操作 create_urs_review",
    )
    base = json.loads(
        ModelMessagesTypeAdapter.dump_json(
            [ModelRequest(parts=[UserPromptPart(content="发起 URS 审核")])]
        )
    )
    history_raw = executor._append_delegated_tool_call(base, pending)

    # ② 打桩：_agent_run 捕获恢复参数，事件/审计 no-op，db 用假会话
    captured: dict = {}

    class _FakeDb:
        def __init__(self) -> None:
            self.added: list = []

        async def execute(self, stmt):
            return SimpleNamespace(scalar_one=lambda: 0)

        async def flush(self):
            return None

        def add(self, obj):
            self.added.append(obj)

    async def fake_agent_run(user_message, deps, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            output="已创建 URS 审核记录", all_messages=lambda: [],
            new_messages=lambda: [],
        )

    async def fake_record_tool_events(deps, result):
        return None

    async def fake_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(executor, "_agent_run", fake_agent_run)
    monkeypatch.setattr(executor, "_record_tool_events", fake_record_tool_events)
    monkeypatch.setattr(executor, "_audit_agent_resume", fake_audit)

    sid = "11111111-2222-3333-4444-555555555555"
    deps = SafetyDeps(
        db=_FakeDb(), person=None, role="safety_admin",
        session_id=sid, channel="test",
    )

    out = asyncio.run(executor.resume(sid, deps, action_id="action-1", approved=True, message_history_raw=history_raw))

    # ③ resume 找到合成挂起 → 授权 + 以既有机制继续（挂载被确认工具）
    assert "已创建 URS 审核" in out["answer"]
    results = captured["deferred_tool_results"]
    approved_ids = list(results.approvals.keys())
    assert len(approved_ids) == 1
    assert results.approvals[approved_ids[0]] is True
    assert captured["resume_tool_names"] == ["create_urs_review"]


def test_domain_agent_excludes_delegate_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    """审查修复回归：域子 Agent 工具面不含 delegate，防递归委派自身。

    TOOL_GROUPS["urs"] 含 delegate 是 orchestrator 路由挂载口径；
    get_domain_agent 注册域工具时必须剔除，否则子 Agent 可递归委派。
    """
    import app.modules.safety.business_agent.agent as agent_mod
    from app.modules.safety.business_agent.tools import registry as reg_mod

    agent_mod._DOMAIN_AGENT_CACHE.clear()
    captured: list[list[str]] = []

    def fake_register(agent, names):
        captured.append(list(names))

    monkeypatch.setattr(reg_mod, "register_tools_subset", fake_register)
    try:
        agent_mod.get_domain_agent("urs")
        assert captured, "应调用 register_tools_subset"
        assert "delegate" not in captured[0]
        # 9 个 URS 域工具仍在
        assert "query_urs_records" in captured[0]
        assert "create_urs_review" in captured[0]
    finally:
        agent_mod._DOMAIN_AGENT_CACHE.clear()
