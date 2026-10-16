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


