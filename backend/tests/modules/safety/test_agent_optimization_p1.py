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



