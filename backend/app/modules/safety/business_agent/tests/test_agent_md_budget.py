"""agent.md 字节预算与语义锚点守护（agent-action-p3 T1）。

8192 字节是硬红线（二期口径，agent-action-p3 spec）；锚点句确保压缩
措辞时不丢规则条目（特征测试：重构保护网，压缩前后均须绿）。
"""

from __future__ import annotations

from pathlib import Path

AGENT_MD = Path(__file__).resolve().parents[1] / "agent.md"
HARD_BUDGET = 8192

# 覆盖各节的代表性锚点：业务规则、知识库检索硬规则、工具话术、示例
ANCHORS = [
    "写操作先复述后执行",
    "绝对禁止自动触发联网搜索",
    "kb_empty",
    "query_hazard_stats",
    "send_hazard_urge",
    "load_skill",
    "# 示例",
    "已关闭",
    "未关闭",
]


def test_agent_md_within_hard_budget() -> None:
    assert AGENT_MD.stat().st_size < HARD_BUDGET, (
        f"agent.md {AGENT_MD.stat().st_size} 字节超出硬红线 {HARD_BUDGET}，先压缩再动笔"
    )


def test_agent_md_rule_anchors_present() -> None:
    text = AGENT_MD.read_text(encoding="utf-8")
    missing = [a for a in ANCHORS if a not in text]
    assert not missing, f"agent.md 缺失语义锚点（规则条目疑似被删）: {missing}"
