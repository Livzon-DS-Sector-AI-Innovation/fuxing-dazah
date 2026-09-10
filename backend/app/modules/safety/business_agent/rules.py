"""业务 Agent 输出硬护栏。

区别于 agent.md（软性引导）：本文件对 Agent 的**最终文本回复**做代码层校验，
目前聚焦「禁语检测」——即使模型忽略了 agent.md 里的语言习惯，这里也能兜底发现。

复用 ``ai_hazard_identification.rules`` 已维护的 ``BANNED_PHRASES``，避免重复维护两份禁语表；
再补充少量对话场景特有的空泛套话。

注意：对话 Agent 的输出是自由文本（非隐患识别那种结构化 JSON），所以这里是**检测/告警**
为主，不做破坏性改写。是否据此拦截或要求模型重写，由 executor 决定。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

# 复用隐患识别插件维护的禁语表，保持全模块一致
from app.modules.safety.ai_hazard_identification.rules import (
    BANNED_PHRASES as _HAZARD_BANNED_PHRASES,
)

logger = logging.getLogger(__name__)

# 对话 Agent 场景补充的空泛表述（与隐患识别表合并、去重）
_AGENT_EXTRA_BANNED = [
    "提高认识",
    "引以为戒",
    "举一反三",
    "确保安全",
]

BANNED_PHRASES: tuple[str, ...] = tuple(
    dict.fromkeys([*_HAZARD_BANNED_PHRASES, *_AGENT_EXTRA_BANNED])
)


@dataclass
class OutputCheckResult:
    """输出校验结果。"""

    ok: bool
    banned_hits: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.ok


def find_banned_phrases(text: str) -> list[str]:
    """返回文本中命中的禁语（去重、保序）。"""
    if not text:
        return []
    hits = [p for p in BANNED_PHRASES if p in text]
    return list(dict.fromkeys(hits))


def check_output(text: str) -> OutputCheckResult:
    """校验 Agent 最终回复；命中禁语时 ok=False 并记录告警。"""
    hits = find_banned_phrases(text)
    if hits:
        logger.warning("business_agent 输出命中禁语: %s", hits)
        return OutputCheckResult(ok=False, banned_hits=hits)
    return OutputCheckResult(ok=True)
