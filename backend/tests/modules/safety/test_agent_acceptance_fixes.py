"""验收缺陷修复钉子（docs/agent-acceptance-20261029/fix-plan.md）。

批次①稳定性：
- #2 Provider 超时接线（timeout 进指纹 + http_client 生效）+ 轮次看门狗
- #6 overview 单域采集超时降级
- #8 pending 守门（历史尾部未回包写 ToolCall → 拦截新消息不进模型）
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest


# ═══════════════════════════════════════════════════════════════
# #2 Provider 超时
# ═══════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _clear_agent_cache():
    from app.modules.safety.business_agent import agent as agent_mod

    agent_mod._AGENT_CACHE.clear()
    yield
    agent_mod._AGENT_CACHE.clear()


def _patch_config(monkeypatch, *, timeout: int | None = 120) -> dict:
    from app.modules.safety.ai_config import scenario_store, store

    cfg: dict = {
        "model": "deepseek-flash", "api_key": "sk-test-abcd1234",
        "temperature": 0.1, "max_tokens": 8192,
    }
    if timeout is not None:
        cfg["timeout"] = timeout
    monkeypatch.setattr(store, "get_profile_config", lambda p: dict(cfg))
    monkeypatch.setattr(scenario_store, "get_effective_profile", lambda s: "text")
    return cfg


def test_runtime_config_has_timeout_and_default(monkeypatch) -> None:
    _patch_config(monkeypatch, timeout=None)
    from app.modules.safety.business_agent.agent import resolve_runtime_config

    cfg = resolve_runtime_config()
    assert cfg.timeout == 120  # registry 默认兜底


def test_timeout_wired_into_provider_http_client(monkeypatch) -> None:
    """_build_agent 必须把 timeout 接进 http_client（openai SDK 默认 600s 是挂死根因）。"""
    _patch_config(monkeypatch, timeout=77)
    from app.modules.safety.business_agent.agent import get_agent_for_tools

    agent = get_agent_for_tools(["knowledge_search"])
    client = agent.model.provider.client
    assert client.timeout.read == pytest.approx(77.0)
    assert client.timeout.connect == pytest.approx(5.0)


def test_timeout_changes_fingerprint(monkeypatch) -> None:
    _patch_config(monkeypatch, timeout=120)
    from app.modules.safety.business_agent.agent import resolve_runtime_config

    fp_120 = resolve_runtime_config().fingerprint
    _patch_config(monkeypatch, timeout=180)
    fp_180 = resolve_runtime_config().fingerprint
    assert fp_120 != fp_180


# ═══════════════════════════════════════════════════════════════
# #8 pending 守门
# ═══════════════════════════════════════════════════════════════


def _dangling_write_history():
    """历史尾部 = 写工具 ToolCall 无 ToolReturn（确认卡未处理形态）。"""
    from pydantic_ai.messages import ModelResponse, ToolCallPart

    return [
        ModelResponse(parts=[
            ToolCallPart(
                tool_name="push_report_to_chat",
                args={"report_name": "daily"},
                tool_call_id="call-1",
            ),
        ]),
    ]


def _resolved_write_history():
    """写调用后紧跟 ToolReturn（确认已点掉）形态。"""
    from pydantic_ai.messages import ModelResponse, ToolReturnPart

    return [
        ModelResponse(parts=[
            ToolReturnPart(
                tool_name="push_report_to_chat",
                content="ok",
                tool_call_id="call-1",
            ),
        ]),
    ]


def test_has_unprocessed_write_call_dangling() -> None:
    from app.modules.safety.business_agent.executor import _has_unprocessed_write_call
    from app.modules.safety.business_agent.schemas import SafetyDeps

    deps = SafetyDeps(db=None, person=None, role="creator", session_id="s", channel="web")
    assert asyncio.run(_has_unprocessed_write_call(_dangling_write_history(), deps)) is True


def test_has_unprocessed_write_call_resolved() -> None:
    from app.modules.safety.business_agent.executor import _has_unprocessed_write_call
    from app.modules.safety.business_agent.schemas import SafetyDeps

    deps = SafetyDeps(db=None, person=None, role="creator", session_id="s", channel="web")
    assert asyncio.run(_has_unprocessed_write_call(_resolved_write_history(), deps)) is False


def test_has_unprocessed_write_call_empty() -> None:
    from app.modules.safety.business_agent.executor import _has_unprocessed_write_call
    from app.modules.safety.business_agent.schemas import SafetyDeps

    deps = SafetyDeps(db=None, person=None, role="creator", session_id="s", channel="web")
    assert asyncio.run(_has_unprocessed_write_call(None, deps)) is False
    assert asyncio.run(_has_unprocessed_write_call([], deps)) is False


def test_run_turn_pending_guard_intercepts(monkeypatch) -> None:
    """B05d：出卡未点 → 发新消息 → 守门话术，不进模型。"""
    from app.modules.safety.business_agent import executor as executor_mod
    from app.modules.safety.business_agent.schemas import SafetyDeps
    from app.modules.safety.ai_config import scenario_store as _ss

    monkeypatch.setattr(_ss, "is_enabled", lambda scenario: True)

    called = {"agent_run": 0}

    async def _fake_agent_run(*a, **kw):
        called["agent_run"] += 1
        raise AssertionError("守门生效时不应进模型")

    monkeypatch.setattr(executor_mod, "_agent_run", _fake_agent_run)

    deps = SafetyDeps(db=None, person=None, role="creator", session_id="s", channel="web")
    result = asyncio.run(executor_mod.run_turn(
        "继续帮我查隐患", deps, message_history=_dangling_write_history(),
    ))
    assert called["agent_run"] == 0
    assert "等待确认" in result["answer"]
    assert result["pending_action"] is None


# ═══════════════════════════════════════════════════════════════
# #2 轮次看门狗
# ═══════════════════════════════════════════════════════════════


def test_run_turn_watchdog_timeout(monkeypatch) -> None:
    """挂死轮必在 timeout+30s 内终态：超时话术 + failed 审计。"""
    from app.modules.safety.business_agent import executor as executor_mod
    from app.modules.safety.business_agent.schemas import SafetyDeps
    from app.modules.safety.ai_config import scenario_store as _ss

    monkeypatch.setattr(_ss, "is_enabled", lambda scenario: True)
    monkeypatch.setattr(executor_mod, "_TURN_WATCHDOG_SLACK", 0)

    async def _fake_route(msg):
        return SimpleNamespace(
            tool_names=["knowledge_search"], domains=["knowledge"],
            path="rule", confidence=1.0,
        )

    from app.modules.safety.business_agent import tool_selector
    monkeypatch.setattr(tool_selector, "route_message_async", _fake_route)

    class _Cfg:
        timeout = 0  # wait_for(…, timeout=0) 立即超时

    monkeypatch.setattr(
        executor_mod, "resolve_runtime_config", lambda: _Cfg(),
    )

    async def _hang(*a, **kw):
        await asyncio.sleep(30)

    monkeypatch.setattr(executor_mod, "_agent_run", _hang)

    audits: list[dict] = []

    async def _fake_audit(deps, user_message, **kw):
        audits.append(kw)

    monkeypatch.setattr(executor_mod, "_audit_agent_turn", _fake_audit)

    deps = SafetyDeps(db=None, person=None, role="creator", session_id="s", channel="web")
    result = asyncio.run(executor_mod.run_turn("查一下隐患", deps))
    assert "超时" in result["answer"]
    assert result["pending_action"] is None
    assert audits and audits[0]["status"] == "failed"
    assert "TimeoutError" in (audits[0]["error"] or "")


# ═══════════════════════════════════════════════════════════════
# #2 工具层超时（pipeline）
# ═══════════════════════════════════════════════════════════════


def test_execute_tool_timeout_returns_error(monkeypatch) -> None:
    from app.modules.safety.business_agent.core import pipeline

    monkeypatch.setattr(pipeline, "perm_check", lambda role, name: True)
    monkeypatch.setattr(pipeline, "_TOOL_EXEC_TIMEOUT", 0.05)

    audits: list[dict] = []

    async def _fake_audit(ctx, tool_name, args, **kw):
        audits.append({"tool": tool_name, **kw})

    monkeypatch.setattr(pipeline, "_post_audit", _fake_audit)

    async def slow_tool(ctx, **kw):
        await asyncio.sleep(30)
        return {"never": True}

    ctx = SimpleNamespace(deps=SimpleNamespace(
        person=None, role="creator", session_id="s", channel="web",
    ))
    out = asyncio.run(pipeline.execute_tool(ctx, "knowledge_search", {}, slow_tool))
    assert isinstance(out, dict) and "超时" in out["error"]
    assert audits and audits[0]["ok"] is False and audits[0]["error"]


# ═══════════════════════════════════════════════════════════════
# #8 web 会话断链修复（get_or_create_session 行 id 回查）
# ═══════════════════════════════════════════════════════════════


async def test_get_or_create_session_resumes_by_row_id(db_session) -> None:
    """web 续轮回传行 id 必须命中同一会话行（原按 chat_id 查 miss 每轮新建空行）。"""
    from app.modules.safety.business_agent.session_store import get_or_create_session

    s1 = await get_or_create_session(
        db_session, channel="web", chat_id="web-fresh-random-sid",
    )
    await db_session.flush()
    assert s1.chat_id == "web-fresh-random-sid"

    # 续轮：前端回传首轮响应里的 session_id（= 行 id），应续用同一行
    s2 = await get_or_create_session(
        db_session, channel="web", chat_id=str(s1.id),
    )
    assert s2.id == s1.id

    # 飞书语义不回归：oc_ 前缀 chat_id（非 UUID）仍按 chat_id 精确匹配
    s3 = await get_or_create_session(
        db_session, channel="feishu", chat_id="oc_abc123",
    )
    await db_session.flush()
    s4 = await get_or_create_session(
        db_session, channel="feishu", chat_id="oc_abc123",
    )
    assert s4.id == s3.id


# ═══════════════════════════════════════════════════════════════
# #6 overview 单域超时
# ═══════════════════════════════════════════════════════════════


def test_overview_domain_timeout_degrades(monkeypatch) -> None:
    from app.modules.safety.service import overview as overview_mod
    from tests.modules.safety.test_overview import _stub_collectors

    monkeypatch.setattr(overview_mod, "_DOMAIN_TIMEOUT", 0.05)
    stubs = _stub_collectors()

    async def hang():
        await asyncio.sleep(30)

    stubs["hazards"] = hang
    data = asyncio.run(overview_mod.build_overview(collectors=stubs))
    assert data["hazards"] is None
    assert any("TimeoutError" in e for e in data["errors"])
