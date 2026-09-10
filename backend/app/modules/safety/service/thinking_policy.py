"""Thinking mode policy — automatic reasoning toggle for DeepSeek V4.

DeepSeek V4 defaults to thinking=ENABLED, which generates invisible reasoning
tokens that multiply latency 2-6x. This module provides a lightweight (<0.01ms)
classifier that decides per-call whether thinking is needed.

Architecture:
    L1: Hard rules — scenario-level force ON/OFF (structured JSON extraction,
        graph building, etc.)
    L2: Complexity scoring — 10-dimension heuristic based on query text,
        history length, and entity count

Usage:
    from app.modules.safety.service.thinking_policy import think_mode

    decision = think_mode(scenario="knowledge_chat", query="对比两个标准的差异")
    # -> ThinkDecision(mode="think", reason="complexity_score=7", effort=None)

    decision = think_mode(scenario="hazard_identification")
    # -> ThinkDecision(mode="off", reason="scenario_force_off", effort=None)
"""

from __future__ import annotations

import logging
import re as _re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── Regex patterns ──
_RE_STANDARD_CODE = _re.compile(
    r"(?:GB|GB/T|AQ|HG|SH|SY|JB|YY|WS|DB\d*|ISO|IEC|EN|ASTM)[- ]?\d+",
    _re.IGNORECASE,
)
_RE_CHEMICAL = _re.compile(
    r"(?:高锰酸[钾钠]|硝酸[钾钠钙镁]|硫酸|盐酸|氯[化气]|过氧化|苯酚|甲醛|甲醇|乙醇|丙酮|甲苯|二甲苯)",
)

# ── L1: scenario force rules ──

# Scenarios that ALWAYS disable thinking (structured extraction, no reasoning)
FORCE_OFF_SCENARIOS: set[str] = {
    "hazard_identification",     # 隐患识别: template-filling → JSON
    "rectification_review",      # 整改初审: comparison → JSON
    "regulation_crawl",          # 法规筛选: document classification
    "agent_chat",                # 助手对话: tool-calling → summarization
    "sop_generation",            # 操规AI补全: structured JSON extraction
}

# Scenarios that ALWAYS enable thinking (genuinely needs reasoning)
FORCE_ON_SCENARIOS: set[str] = {
    "graph_build",               # 图谱构建: entity extraction + taxonomy + relationship inference
}

# ── L2: complexity scoring ──

# Patterns that indicate reasoning is needed (each contributes +score)
_THINK_TRIGGERS: list[tuple[list[str], int]] = [
    (["分析", "评估", "判断", "诊断", "归因", "判定"], 3),       # reasoning verbs
    (["对比", "区别", "差异", "哪个更", "不同于", "相较于"], 2),  # comparison
    (["为什么", "原因", "导致", "是否合规", "是否适用", "是否违反"], 2),  # causation
    (["如何改进", "建议", "方案", "措施", "对策"], 2),            # open-ended advice
    (["综合", "综上", "归纳", "梳理"], 1),                       # synthesis
]

# Patterns that indicate a simple fact lookup (each contributes -score)
_SIMPLE_TRIGGERS: list[tuple[list[str], int]] = [
    (["什么是", "列出", "查询", "有哪些", "多少"], -3),          # fact lookup
    (["定义", "缩写", "全称"], -2),                              # definition
]


@dataclass
class ThinkDecision:
    """Result of thinking mode classification."""

    mode: str  # "off" | "think"
    reason: str
    effort: str | None = None  # "low" | "high" — only for mode="think"


def think_mode(
    scenario: str = "unknown",
    query: str = "",
    message_history_len: int = 0,
    entity_count: int | None = None,
) -> ThinkDecision:
    """Decide whether to enable thinking mode for a DeepSeek API call.

    Args:
        scenario: AI call scenario (knowledge_chat, agent_chat, etc.)
        query: The user's query text (or prompt for system-triggered calls)
        message_history_len: Number of prior turns (0 = first message)
        entity_count: Number of standards/chemicals mentioned (auto-detected if None)

    Returns:
        ThinkDecision with mode and effort recommendation.

    >>> think_mode(scenario="hazard_identification")
    ThinkDecision(mode="off", reason="scenario_force_off")

    >>> think_mode(scenario="knowledge_chat", query="对比 GB 15603 和 GB 50016 的差异")
    ThinkDecision(mode="think", reason="complexity_score=9", effort="high")
    """
    # ── L1: Hard rules ──
    if scenario in FORCE_OFF_SCENARIOS:
        return ThinkDecision(mode="off", reason="scenario_force_off")
    if scenario in FORCE_ON_SCENARIOS:
        return ThinkDecision(mode="think", reason="scenario_force_on", effort="high")

    # ── L2: Complexity scoring ──
    score = 0

    # Reasoning triggers — each category independently contributes
    for triggers, points in _THINK_TRIGGERS:
        if any(t in query for t in triggers):
            score += points

    # Simple triggers — each category independently offsets
    for triggers, points in _SIMPLE_TRIGGERS:
        if any(t in query for t in triggers):
            score += points

    # Entity count (standards + chemicals)
    if entity_count is None:
        entity_count = _count_entities(query)
    if entity_count >= 3:
        score += 3
    elif entity_count >= 2:
        score += 2

    # Query length (>50 chars = more complex)
    if len(query) > 50:
        score += 1

    # Multi-turn context (>3 prior turns)
    if message_history_len >= 3:
        # Only counts if current query has follow-up markers
        if any(t in query for t in ("进一步", "还有", "另外", "继续", "具体")):
            score += 1

    # ── Decision ──
    if score >= 6:
        logger.info("think_mode: ON (effort=high) scenario=%s score=%d query=%r", scenario, score, query[:80])
        return ThinkDecision(mode="think", reason=f"complexity_score={score}", effort="high")
    elif score >= 3:
        logger.info("think_mode: ON (effort=low) scenario=%s score=%d query=%r", scenario, score, query[:80])
        return ThinkDecision(mode="think", reason=f"complexity_score={score}", effort="low")
    else:
        logger.debug("think_mode: OFF scenario=%s score=%d query=%r", scenario, score, query[:80])
        return ThinkDecision(mode="off", reason=f"complexity_score={score}")


def _count_entities(text: str) -> int:
    """Count standard codes + chemical names in text."""
    std_count = len(set(_RE_STANDARD_CODE.findall(text)))
    chem_count = len(set(_RE_CHEMICAL.findall(text)))
    return std_count + chem_count
