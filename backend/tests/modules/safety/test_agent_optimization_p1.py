"""安全业务 Agent 一期优化（单体减法）特性级回归钉子。

按 .scratch/safety-agent-optimization-p1/spec.md 逐 ticket 累积行为级断言：
- T02 采样参数（temp 0.1 / max_tokens 8192）
- T03 工具结果 4KB 截断
- T04 压缩阈值/后台化、记忆注入上限
- T08 常驻清单
- T09/T10 路由行为（另见 test_tool_selector_coverage.py）
"""

from __future__ import annotations


def test_sampling_params_aligned_to_warehouse() -> None:
    """T02（1-A）：temp 0.1 / max_tokens 8192，对齐仓储 Agent。"""
    from app.modules.safety.business_agent.agent import _make_agent

    agent = _make_agent()
    assert agent.model_settings == {"temperature": 0.1, "max_tokens": 8192}

