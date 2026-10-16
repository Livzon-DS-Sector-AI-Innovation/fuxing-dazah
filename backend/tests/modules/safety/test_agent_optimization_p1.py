"""安全业务 Agent 一期优化（单体减法）特性级回归钉子。

按 .scratch/safety-agent-optimization-p1/spec.md 逐 ticket 累积行为级断言：
- T02 采样参数（temp 0.1 / max_tokens 8192）
- T03 工具结果 4KB 截断
- T04 压缩阈值/后台化、记忆注入上限
- T08 常驻清单
- T09/T10 路由行为（另见 test_tool_selector_coverage.py）
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest


def test_sampling_params_aligned_to_warehouse() -> None:
    """T02（1-A）：temp 0.1 / max_tokens 8192，对齐仓储 Agent。"""
    from app.modules.safety.business_agent.agent import _make_agent

    agent = _make_agent()
    assert agent.model_settings == {"temperature": 0.1, "max_tokens": 8192}


# ── T03（1-B）：工具结果 4KB 截断 ─────────────────────────────────


def _run_tool(data):
    """经 execute_tool 统一管道跑一个返回 data 的假工具（safety_admin 放行）。"""
    from app.modules.safety.business_agent.core.pipeline import execute_tool

    async def fake_func(ctx, **kwargs):  # noqa: ARG001
        return data

    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            role="safety_admin", session_id=None, channel="test", person=None,
        )
    )
    return asyncio.run(execute_tool(ctx, "query_hazards", {}, fake_func))


def _size(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False).encode())


def test_small_result_passes_through_untouched() -> None:
    out = _run_tool({"items": [1, 2, 3], "total": 3})
    assert out == {"items": [1, 2, 3], "total": 3}


def test_large_list_truncated_with_notice() -> None:
    records = [{"id": i, "blob": "x" * 300} for i in range(100)]
    out = _run_tool({"records": records, "total": 100})
    assert "truncation_notice" in out
    assert len(out["records"]) < 100
    assert "共 100 条" in out["truncation_notice"]
    assert "已显示前" in out["truncation_notice"]
    assert _size(out) <= 4096 + 512


def test_large_text_truncated_to_preview() -> None:
    out = _run_tool({"content": "x" * 30_000})
    assert _size(out) <= 4096 + 512
    assert "截断" in json.dumps(out, ensure_ascii=False)


def test_error_result_not_truncated() -> None:
    from app.modules.safety.business_agent.core.pipeline import execute_tool

    async def boom(ctx, **kwargs):  # noqa: ARG001
        raise ValueError("E" * 300)

    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            role="safety_admin", session_id=None, channel="test", person=None,
        )
    )
    out = asyncio.run(execute_tool(ctx, "query_hazards", {}, boom))
    assert out["error"].startswith("ValueError")
    assert len(out["error"]) > 300  # 错误信息完整，不截断


# ── T04（1-B）：压缩阈值 12k + 后台化 + 记忆注入上限 ──────────────


def test_compaction_base_threshold_is_12k() -> None:
    from app.modules.safety.business_agent.core import compaction

    assert compaction._COMPACTION_BASE_THRESHOLD == 12_000


def _big_history(n: int = 60):
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    # tiktoken 会把 "x" 连串合并分词，需足够长才能稳定越过 12k 压缩线
    return [
        ModelRequest(parts=[UserPromptPart(content=f"消息{i} " + "x" * 2000)])
        for i in range(n)
    ]


def test_background_compaction_applies_next_turn(monkeypatch) -> None:
    """超阈值：本轮原样返回；后台压缩完成后，下轮历史前缀被替换为压缩版。"""
    from app.modules.safety.business_agent.core import compaction

    compaction._BG_COMPACT_CACHE.clear()
    compaction._BG_PENDING.clear()

    async def fake_summarize(early):  # noqa: ARG001
        return "这是早期对话摘要"

    monkeypatch.setattr(compaction, "_summarize", fake_summarize)

    deps = SimpleNamespace(session_id="sess-t04")
    base = _big_history()

    async def turn_and_drain() -> None:
        # 本轮：只调度，不改历史（调度需在事件循环内，与 executor 异步链路一致）
        compaction.schedule_background_compaction(base, deps)
        assert compaction.apply_cached_compaction(base, deps) == base
        while compaction._BG_TASKS:
            await next(iter(compaction._BG_TASKS))

    asyncio.run(turn_and_drain())
    assert "sess-t04" in compaction._BG_COMPACT_CACHE

    # 下轮：历史 = base 前缀 + 新增尾部 → 前缀替换为压缩版
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    tail = [ModelRequest(parts=[UserPromptPart(content="新的一轮")])]
    nxt = base + tail
    applied = compaction.apply_cached_compaction(nxt, deps)
    assert applied[-1:] == tail                      # 新增尾部保留
    assert len(applied) < len(nxt)                   # 早期被摘要替换
    first_text = applied[0].parts[0].content
    assert first_text.startswith(compaction.SUMMARY_PREFIX)

    compaction._BG_COMPACT_CACHE.clear()
    compaction._BG_PENDING.clear()


def test_apply_cached_compaction_prefix_mismatch_untouched() -> None:
    from app.modules.safety.business_agent.core import compaction

    compaction._BG_COMPACT_CACHE.clear()
    other = _big_history(5)
    compaction._BG_COMPACT_CACHE["sess-x"] = {
        "base": _big_history(20), "compacted": other,
    }
    deps = SimpleNamespace(session_id="sess-x")
    fresh = _big_history(30)  # 前缀不匹配（内容不同）
    assert compaction.apply_cached_compaction(fresh, deps) == fresh
    compaction._BG_COMPACT_CACHE.clear()


def test_memory_injection_capped(monkeypatch) -> None:
    """记忆注入每轮 ≤5 条：常量上限 + executor 调用点 top_k=3。"""
    from app.modules.safety.business_agent.core import memory

    assert memory.MEMORY_INJECT_MAX_PER_TURN == 5

    recorded: dict = {}

    async def fake_retrieve(db, user_id, query, top_k=5, **kw):  # noqa: ARG001
        recorded["top_k"] = top_k
        return [{"id": "1", "content": "m", "memory_type": "fact"}]

    monkeypatch.setattr(memory, "retrieve_with_decay", fake_retrieve)
    monkeypatch.setattr(
        memory, "inject_to_prompt", lambda results: [r["content"] for r in results],
    )
    from app.modules.safety.business_agent import executor

    out = asyncio.run(executor._retrieve_memories("u1", "查隐患", None))
    assert out == ["m"]
    assert recorded["top_k"] <= memory.MEMORY_INJECT_MAX_PER_TURN


# ── T06（1-C）：读域合并 4 组（分发器行为） ────────────────────────


def _fake_ctx():
    return SimpleNamespace(deps=SimpleNamespace(db=None))


def test_query_drills_dispatch(monkeypatch) -> None:
    from app.modules.safety.business_agent.tools import read_tools

    calls: list[dict] = []

    async def fake_plans(ctx, **kw):
        calls.append({"impl": "plans", **kw})
        return {"items": [], "total": 0}

    async def fake_records(ctx, **kw):
        calls.append({"impl": "records", **kw})
        return {"items": [], "total": 0}

    monkeypatch.setattr(read_tools, "_query_drill_plans_impl", fake_plans)
    monkeypatch.setattr(read_tools, "_query_drill_records_impl", fake_records)

    asyncio.run(read_tools.query_drills(_fake_ctx()))                       # 默认 plans
    asyncio.run(read_tools.query_drills(_fake_ctx(), kind="records", department="生产部"))
    assert calls[0]["impl"] == "plans"
    assert calls[1]["impl"] == "records"
    assert calls[1]["department"] == "生产部"


def test_query_msds_dispatch(monkeypatch) -> None:
    from app.modules.safety.business_agent.tools import read_tools

    calls: list[dict] = []

    async def fake_docs(ctx, **kw):
        calls.append({"impl": "documents", **kw})
        return {"items": [], "total": 0}

    async def fake_collections(ctx, **kw):
        calls.append({"impl": "collections", **kw})
        return {"items": [], "total": 0}

    monkeypatch.setattr(read_tools, "_query_msds_documents_impl", fake_docs)
    monkeypatch.setattr(read_tools, "_query_msds_collections_impl", fake_collections)

    asyncio.run(read_tools.query_msds(_fake_ctx(), name="异丙醇"))
    asyncio.run(read_tools.query_msds(_fake_ctx(), kind="collections", parse_status="failed"))
    assert calls[0]["impl"] == "documents"
    assert calls[0]["name"] == "异丙醇"
    assert calls[1]["impl"] == "collections"
    assert calls[1]["parse_status"] == "failed"


def test_query_oh_dispatch(monkeypatch) -> None:
    from app.modules.safety.business_agent.tools import read_tools

    calls: list[dict] = {}

    def make(name):
        async def impl(ctx, **kw):
            calls[name] = kw
            return {"items": [], "total": 0}
        return impl

    monkeypatch.setattr(read_tools, "_query_oh_positions_impl", make("positions"))
    monkeypatch.setattr(read_tools, "_query_oh_followups_impl", make("followups"))
    monkeypatch.setattr(read_tools, "_query_oh_hazard_enums_impl", make("hazard_enums"))

    asyncio.run(read_tools.query_oh(_fake_ctx(), entity="positions", department="生产部"))
    assert calls["positions"] == {
        "department": "生产部", "hazard_factors_status": None, "limit": 20,
    }

    asyncio.run(read_tools.query_oh(_fake_ctx(), entity="followups", status="open"))
    assert calls["followups"]["status"] == "open"

    asyncio.run(read_tools.query_oh(_fake_ctx(), entity="hazard_enums"))
    assert calls["hazard_enums"] == {}

    out = asyncio.run(read_tools.query_oh(_fake_ctx(), entity="不存在的"))
    assert "error" in out and "entity" in out["error"]


def test_query_latest_regulations_view_dispatch(monkeypatch) -> None:
    from app.modules.safety.business_agent.tools import read_tools

    calls: list[dict] = []

    async def fake_crawl(ctx, **kw):
        calls.append({"view": "crawl", **kw})
        return {"items": [], "total": 0}

    async def fake_ingested(ctx, **kw):
        calls.append({"view": "ingested", **kw})
        return {"success": True, "items": [], "total": 0}

    monkeypatch.setattr(read_tools, "_query_regulations_crawl_impl", fake_crawl)
    monkeypatch.setattr(read_tools, "_query_regulations_ingested_impl", fake_ingested)

    asyncio.run(read_tools.query_latest_regulations(_fake_ctx()))  # 默认爬取视角
    asyncio.run(read_tools.query_latest_regulations(_fake_ctx(), view="ingested", limit=3))
    assert calls[0]["view"] == "crawl"
    assert calls[1] == {"view": "ingested", "limit": 3}


# ── T07（1-C）：报警生成合一（scope+period） ──────────────────────


def test_generate_alarm_report_dispatch(monkeypatch) -> None:
    from app.modules.safety.business_agent.tools import write_tools

    calls: list[dict] = []

    def make(name):
        async def impl(ctx, **kw):
            calls.append({"impl": name, **kw})
            return {"success": True}
        return impl

    monkeypatch.setattr(write_tools, "_generate_fire_alarm_daily_impl", make("fire_daily"))
    monkeypatch.setattr(write_tools, "_generate_fire_alarm_monthly_impl", make("fire_monthly"))
    monkeypatch.setattr(write_tools, "_generate_central_alarm_daily_impl", make("central_daily"))

    asyncio.run(write_tools.generate_alarm_report(_fake_ctx(), scope="fire"))
    asyncio.run(
        write_tools.generate_alarm_report(_fake_ctx(), scope="fire", period="monthly", target_date="2026-08-31")
    )
    asyncio.run(write_tools.generate_alarm_report(_fake_ctx(), scope="central"))

    assert calls[0] == {"impl": "fire_daily", "target_date": None}
    assert calls[1] == {"impl": "fire_monthly", "month_end": "2026-08-31"}
    assert calls[2] == {"impl": "central_daily", "target_date": None}

    out = asyncio.run(
        write_tools.generate_alarm_report(_fake_ctx(), scope="central", period="monthly")
    )
    assert out["success"] is False
    assert "中控暂无月报" in out["error"]


# ── T08（1-C）：常驻清单 + 按需域可达 + resume 挂载 ────────────────


def test_resident_tools_within_budget_and_consistent() -> None:
    from app.modules.safety.business_agent.tools.registry import (
        RESIDENT_TOOLS,
        TOOL_KIND,
    )

    assert len(RESIDENT_TOOLS) <= 38
    assert RESIDENT_TOOLS <= set(TOOL_KIND)
    on_demand = set(TOOL_KIND) - RESIDENT_TOOLS
    assert len(on_demand) == len(TOOL_KIND) - len(RESIDENT_TOOLS)


def test_default_agent_mounts_resident_set() -> None:
    """measure 同口径：默认注册面 = 常驻集（mock transport 计数）。"""
    import httpx
    from pydantic_ai import Agent
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["tools"] = json.loads(request.content).get("tools", [])
        return httpx.Response(
            200,
            json={
                "id": "x", "object": "chat.completion", "created": 1, "model": "m",
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    async def run() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        agent = Agent(
            OpenAIChatModel("t", provider=OpenAIProvider(api_key="x", http_client=client))
        )
        from app.modules.safety.business_agent.tools.registry import (
            RESIDENT_TOOLS,
            register_all_tools,
        )

        register_all_tools(agent)
        await agent.run("你好")
        names = {t["function"]["name"] for t in captured["tools"]}
        await client.aclose()
        assert names == set(RESIDENT_TOOLS)

    asyncio.run(run())


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("帮我看下最近的URS智能审核记录", "query_urs_records"),
        ("发起一个设备采购URS审核", "create_urs_review"),
        ("轮询一下隐患AI分析", "poll_hazard_ai_analysis"),
        ("补一下隐患的整改审核", "poll_hazard_rectification_review"),
        ("查一下当前的AI配置和模型清单", "query_ai_config"),
        ("把这个月的日报整理成多维表格", "office_create_base"),
        ("查一下特种作业持证到期预警", "query_cert_warnings"),
    ],
)
def test_on_demand_tools_reachable_via_routing(message: str, expected: str) -> None:
    """按需域工具（urs/ops/office 写/证照）经关键词路由可达。"""
    from app.modules.safety.business_agent.tool_selector import select_tool_names

    names = select_tool_names(message)
    assert names is not None, message
    assert expected in names, f"{message!r} → {sorted(names)[:12]}"


def test_resume_mounts_pending_on_demand_tool() -> None:
    from app.modules.safety.business_agent import executor
    from app.modules.safety.business_agent.tools.registry import RESIDENT_TOOLS

    mounted = executor._resume_mount_tools(["confirm_urs_assessment", "不存在的工具"])
    assert "confirm_urs_assessment" in mounted          # 按需工具可达
    assert RESIDENT_TOOLS <= set(mounted)               # 常驻集全在
    assert "不存在的工具" not in mounted
    assert len(mounted) <= len(RESIDENT_TOOLS) + 5      # 未退回全量




