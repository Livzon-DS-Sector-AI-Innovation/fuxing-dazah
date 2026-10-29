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
# #1 viewer 兜底（登录未绑定 → viewer；匿名 → 全拒）
# ═══════════════════════════════════════════════════════════════


async def test_build_deps_viewer_fallback(db_session) -> None:
    """登录未绑定角色 → viewer 兜底（TEST-VIEWER-001 验收资产行）。"""
    from app.modules.safety.api.business_agent import _build_deps

    deps = await _build_deps(db_session, feishu_user_id="ou_test_viewer")
    assert deps.role == "viewer"


async def test_build_deps_bound_role_wins(db_session) -> None:
    """已绑定角色（许康福 creator）→ 兜底不覆盖真实角色。"""
    from app.modules.safety.api.business_agent import _build_deps

    deps = await _build_deps(
        db_session, feishu_user_id="ou_5773c42e1fc7ce3e554b83242c87aa0b",
    )
    assert deps.role == "creator"


async def test_build_deps_anonymous_stays_denied(db_session) -> None:
    """匿名（无 feishu_user_id）→ role=None 保持全拒。"""
    from app.modules.safety.api.business_agent import _build_deps

    deps = await _build_deps(db_session)
    assert deps.role is None


# ═══════════════════════════════════════════════════════════════
# #3 显式 chat_id 直发（点名群只发点名群，不写速递总卡）
# ═══════════════════════════════════════════════════════════════


class _FakeDb:
    async def commit(self) -> None:
        pass


def _fake_ctx():
    from app.modules.safety.business_agent.schemas import SafetyDeps

    deps = SafetyDeps(db=_FakeDb(), person=None, role="creator", session_id="s", channel="web")
    return SimpleNamespace(deps=deps)


def test_push_supervision_explicit_target_direct_send(monkeypatch) -> None:
    """点名群 → build_bulletin + send_group_card 直发；总卡 upsert 不被触碰。"""
    from datetime import date

    from app.modules.safety.feishu import daily_digest as digest_mod
    from app.modules.safety.feishu import notification as notify_mod
    from app.modules.safety.business_agent.tools.hazard_action_tools import (
        push_report_to_chat,
    )
    from app.modules.safety.service.hazard_direct import bulletin as bulletin_mod

    async def fake_build():
        return "# 通报正文", {"total": 5, "urgent": 2, "warning": 3}

    sent: list[dict] = []

    async def fake_send(*, chat_id, title, content):
        sent.append({"chat_id": chat_id, "title": title, "content": content})
        return True

    async def fail_upsert(*a, **kw):  # 总卡写入必须不被触碰
        raise AssertionError("点名群直发不应写速递总卡")

    monkeypatch.setattr(bulletin_mod, "build_bulletin", fake_build)
    monkeypatch.setattr(notify_mod, "send_group_card", fake_send)
    monkeypatch.setattr(digest_mod, "upsert_daily_digest", fail_upsert)

    out = asyncio.run(push_report_to_chat(
        _fake_ctx(), report_kind="supervision", chat_id="oc_whitelist_test",
    ))
    assert out["sent"] is True and "直发" in out["message"]
    assert sent == [{
        "chat_id": "oc_whitelist_test", "title": "隐患督办通报", "content": "# 通报正文",
    }]


def test_push_alarm_explicit_target_direct_send(monkeypatch) -> None:
    """报警日报点名群 → push=False 生成 + 直发，不投总卡。"""
    from app.modules.safety.feishu import notification as notify_mod
    from app.modules.safety.business_agent.tools.hazard_action_tools import (
        push_report_to_chat,
    )
    from app.modules.safety.service.central_alarm import service as ca_service_mod

    class _Resp:
        target_date = __import__("datetime").date(2026, 10, 29)
        total = 7
        markdown_report = "# 中控日报正文"

    class _Svc:
        def __init__(self, db):
            pass

        async def generate_daily_report(self, *, push, channel):
            assert push is False, "点名群直发必须 push=False 生成（不投总卡）"
            return _Resp()

    sent: list[dict] = []

    async def fake_send(*, chat_id, title, content):
        sent.append({"chat_id": chat_id, "title": title, "content": content})
        return True

    monkeypatch.setattr(ca_service_mod, "CentralAlarmService", _Svc)
    monkeypatch.setattr(notify_mod, "send_group_card", fake_send)

    out = asyncio.run(push_report_to_chat(
        _fake_ctx(), report_kind="alarm", scope="central", chat_id="oc_whitelist_test",
    ))
    assert out["sent"] is True and "直发" in out["message"]
    assert sent[0]["title"] == "中控报警日报 - 2026-10-29"
    assert sent[0]["content"] == "# 中控日报正文"


# ═══════════════════════════════════════════════════════════════
# #4 OH 工具缺键取值（直读行 mapped 条件写键）
# ═══════════════════════════════════════════════════════════════


class _OhRowViewFake:
    """模拟 oh_direct.OhRowView：mapped 缺键时 __getattr__ 抛 AttributeError。"""

    def __init__(self, record_id: str, mapped: dict) -> None:
        self.record_id = record_id
        self.mapped = mapped

    @property
    def id(self) -> str:
        return self.record_id

    def __getattr__(self, name):
        if name in self.mapped:
            return self.mapped[name]
        raise AttributeError(name)


def test_query_oh_exams_missing_keys_no_crash(monkeypatch) -> None:
    """A26：无体检号行（mapped 缺 exam_no 等键）不再 AttributeError 崩工具。"""
    from datetime import date

    from app.modules.safety.business_agent.tools import read_tools
    from app.modules.safety.service import oh_health_exam as exam_service_mod

    row = _OhRowViewFake("recX", {"employee_name": "张三", "exam_type": "periodic"})

    class _Svc:
        def __init__(self, db):
            pass

        async def get_exams(self, **kw):
            return [row], 1

    monkeypatch.setattr(exam_service_mod, "OhHealthExamService", _Svc)

    out = asyncio.run(read_tools.query_oh_exams(
        SimpleNamespace(deps=SimpleNamespace(db=None)), exam_type="periodic",
    ))
    assert out["total"] == 1
    item = out["items"][0]
    assert item["employee_name"] == "张三"
    assert item["exam_no"] is None and item["exam_date"] is None
    assert item["hazard_factors"] == []


def test_query_oh_persons_missing_keys_no_crash(monkeypatch) -> None:
    from app.modules.safety.business_agent.tools import read_tools
    from app.modules.safety.service import oh_person as person_service_mod

    row = _OhRowViewFake("recY", {"name": "李四"})

    class _Svc:
        def __init__(self, db):
            pass

        async def get_persons(self, **kw):
            return [row], 1

    monkeypatch.setattr(person_service_mod, "OhPersonService", _Svc)

    out = asyncio.run(read_tools.query_oh_persons(
        SimpleNamespace(deps=SimpleNamespace(db=None)), department="生产部",
    ))
    assert out["items"][0]["name"] == "李四"
    assert out["items"][0]["employee_no"] is None


# ═══════════════════════════════════════════════════════════════
# #7 粘性路由（裸肯定/否定沿用上轮口径）
# ═══════════════════════════════════════════════════════════════


def test_is_bare_confirmation_words() -> None:
    from app.modules.safety.business_agent.executor import _is_bare_confirmation

    assert _is_bare_confirmation("确认") is True
    assert _is_bare_confirmation(" 好的。") is True
    assert _is_bare_confirmation("取消！") is True
    assert _is_bare_confirmation("确认执行刚才那个操作") is False  # 带内容不粘
    assert _is_bare_confirmation("确认一下隐患整改情况") is False
    assert _is_bare_confirmation("") is False


def test_previous_user_message_strips_prefix() -> None:
    from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart

    from app.modules.safety.business_agent.executor import _previous_user_message

    history = [
        ModelRequest(parts=[
            UserPromptPart(content="工具目录：a, b, c\n---\n帮我把督办通报发到群里"),
        ]),
        ModelResponse(parts=[]),
    ]
    assert _previous_user_message(history) == "帮我把督办通报发到群里"
    assert _previous_user_message(None) is None
    assert _previous_user_message([]) is None


def test_run_turn_sticky_routing(monkeypatch) -> None:
    """B08b：裸「确认」应沿用上一轮用户消息的路由输入（审计记 sticky）。"""
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    from app.modules.safety.business_agent import executor as executor_mod
    from app.modules.safety.business_agent import tool_selector
    from app.modules.safety.business_agent.schemas import SafetyDeps
    from app.modules.safety.ai_config import scenario_store as _ss

    monkeypatch.setattr(_ss, "is_enabled", lambda scenario: True)
    routed_inputs: list[str] = []

    async def fake_route(msg):
        routed_inputs.append(msg)
        return SimpleNamespace(
            tool_names=["knowledge_search"], domains=("knowledge",),
            path="rule", confidence=1.0,
        )

    monkeypatch.setattr(tool_selector, "route_message_async", fake_route)

    audits: list[dict] = []

    async def fake_audit(deps, user_message, **kw):
        audits.append(kw)

    monkeypatch.setattr(executor_mod, "_audit_agent_turn", fake_audit)

    class _Out:
        output = "好的，已处理。"

        def all_messages(self):
            return []

        def new_messages(self):
            return []

    async def fake_agent_run(*a, **kw):
        return _Out()

    monkeypatch.setattr(executor_mod, "_agent_run", fake_agent_run)

    history = [
        ModelRequest(parts=[
            UserPromptPart(content="prefix\n---\n把隐患督办通报发到群里"),
        ]),
    ]
    deps = SafetyDeps(db=None, person=None, role="creator", session_id="s", channel="web")
    result = asyncio.run(executor_mod.run_turn("确认", deps, message_history=history))
    assert routed_inputs == ["把隐患督办通报发到群里"]  # 不是"确认"
    assert audits and audits[-1]["routing"].get("sticky") is True
    assert result["answer"]


# ═══════════════════════════════════════════════════════════════
# #10 引用提取回退 + snippet 清洗
# ═══════════════════════════════════════════════════════════════


def test_extract_knowledge_sources_content_fallback() -> None:
    """structured_content 抛错时回退解析 part.content JSON（A19 空 sources）。"""
    import json as _json

    from app.modules.safety.business_agent.executor import _extract_knowledge_sources

    payload = {"answer": "ok", "sources": [{"doc_title": "GB 3836.1", "feishu_url": "https://x"}]}
    part = SimpleNamespace(
        part_kind="tool-return",
        tool_name="knowledge_search",
        content=_json.dumps(payload, ensure_ascii=False),
    )

    def boom():
        raise RuntimeError("structured_content 不可用")

    part.structured_content = boom
    msg = SimpleNamespace(parts=[part])

    class _Result:
        def new_messages(self):
            return [msg]

    srcs = _extract_knowledge_sources(_Result())
    assert srcs and srcs[0]["doc_title"] == "GB 3836.1"


def test_clean_snippet_strips_html_and_truncates() -> None:
    from app.modules.safety.business_agent.tools.read_tools import _clean_snippet

    html = "<table><tr><td>数据交换规范</td></tr></table>正文内容  spaces"
    out = _clean_snippet(html)
    assert "<" not in out and "数据交换规范" in out and "  " not in out
    assert len(_clean_snippet("字" * 300)) == 121  # 120 + 省略号


# ═══════════════════════════════════════════════════════════════
# #9 /forget 记忆清除
# ═══════════════════════════════════════════════════════════════


async def test_delete_all_for_user_soft_delete(db_session) -> None:
    from app.modules.safety.business_agent.core.memory import delete_all_for_user
    from app.modules.safety.memory.models import AgentMemory

    db_session.add_all([
        AgentMemory(user_id="u-forget-test", memory_type="fact", content="暗号A", importance=0.5),
        AgentMemory(user_id="u-forget-test", memory_type="preference", content="偏好B", importance=0.5),
        AgentMemory(user_id="u-other", memory_type="fact", content="他人记忆", importance=0.5),
    ])
    await db_session.flush()

    deleted = await delete_all_for_user(db_session, "u-forget-test")
    assert deleted == 2
    # 幂等：再次清除为 0
    assert await delete_all_for_user(db_session, "u-forget-test") == 0
    # 他人记忆不受影响
    from sqlalchemy import select

    alive = (await db_session.execute(
        select(AgentMemory).where(
            AgentMemory.user_id == "u-other", AgentMemory.is_deleted == False,  # noqa: E712
        )
    )).scalars().all()
    assert len(alive) == 1


# ═══════════════════════════════════════════════════════════════
# #11 库存 summary 聚合
# ═══════════════════════════════════════════════════════════════


def test_query_stock_summary_aggregation(monkeypatch) -> None:
    from app.modules.warehouse.agent.tools import query as warehouse_query

    def cell_qty(v):
        return {"type": 1, "value": v}

    rows = [
        {"record_id": f"r{i}", "fields": {
            "物料名称": "乙醇", "单位": "kg", "剩余数量": cell_qty(q),
        }}
        for i, q in enumerate([100.0, 50.5, 25], start=1)
    ] + [
        {"record_id": "r9", "fields": {
            "物料名称": "乙醇", "单位": "L", "剩余数量": cell_qty(30),
        }},
        {"record_id": "r8", "fields": {
            "物料名称": "硫酸", "单位": "kg", "剩余数量": cell_qty(200),
        }},
    ]

    async def fake_fetch_all(table, view, names):
        return rows, len(rows), False

    monkeypatch.setattr(warehouse_query, "_fetch_all", fake_fetch_all)

    out = asyncio.run(warehouse_query.query_stock(summary=True))
    assert out["total"] == 5 and out["summary"] is True
    rows_out = {f"{r['物料名称']}|{r['单位']}": r for r in out["summary_rows"]}
    assert rows_out["硫酸|kg"]["总数量"] == "200"      # 整数量格式化为字符串
    assert rows_out["乙醇|kg"]["总数量"] == 175.5
    assert rows_out["乙醇|kg"]["批次数"] == 3
    assert rows_out["乙醇|L"]["总数量"] == "30"
    assert out["summary_materials"] == 3

    # 默认明细模式不聚合
    out2 = asyncio.run(warehouse_query.query_stock())
    assert "summary_rows" not in out2


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
