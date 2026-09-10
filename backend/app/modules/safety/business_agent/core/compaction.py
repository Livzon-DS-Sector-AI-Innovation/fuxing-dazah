"""token 驱动压缩（S6）。

解决"按消息条数触发"的缺陷：一条 tool return 可能 10k token，条数无法反映真实上下文
压力。改为按派生消息列表估算 input token，超过阈值（24k）对早期事件做摘要压缩、
保留最近 ``_SUMMARY_KEEP_RECENT`` 轮原文。

职责（自旧 ``executor._summarize_history``/``_compress_history`` 迁入，逻辑不变，触发改 token 驱动）：
- ``estimate_tokens``：tokenizer 估算（tiktoken 优先，字符近似回退）。
- ``estimate_messages_tokens``：消息列表总 input token。
- ``maybe_compact``：超阈值 → AI 早期摘要 + 保留最近 N 轮；否则原样返回。

作用对象：派生后送模型的消息列表（``derive_messages`` 的输出）。事件源（``agent_session_events``
表）永不压缩，保持完整可回放——compaction 只压缩"送模型"的派生视图，不改事件表。

设计遵循 CLAUDE.md：只改 ``app/modules/safety/business_agent/``；不引入新 AI 调用（复用
executor 迁入的 AI 一行式摘要）；不引入新依赖（tiktoken 若已装则用，否则字符近似 4 char ≈ 1 token）。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from pydantic_ai.messages import ModelMessage, SystemPromptPart

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ── 常量（触发从"条数"改为"token 压力"，语义沿用 executor） ──
_COMPACTION_BASE_THRESHOLD = 24_000    # 基准 input token 阈值（spec US5），不含 system+tool 开销
# system+tool 固定开销估算：agent.md 约 2-3k token + tool definitions 约 3.5k token，
# 每轮请求都会占用模型窗口，必须从消息增长阈值中扣除，否则消息先顶到窗口上限才触发压缩。
_ESTIMATED_SYSTEM_TOOL_OVERHEAD = 6_000
# 有效触发阈值 = 基准 24k − system/tool 开销 6k（计算口径：24k 保持不变，实际判定线 18k）
_COMPACTION_THRESHOLD = _COMPACTION_BASE_THRESHOLD - _ESTIMATED_SYSTEM_TOOL_OVERHEAD
_SUMMARY_KEEP_RECENT = 10               # 保留最近 10 轮原文不参与摘要（沿用 executor 常量）
_MAX_HISTORY_MESSAGES = 20              # 兼容常量：压缩后消息数上限参照（保留旧语义）
SUMMARY_PREFIX = "[早前对话摘要]"        # 摘要 system 消息前缀（验收接缝）

_HISTORY_SUMMARY_PROMPT = (
    "用一句话（≤40字）总结以下对话的核心内容，只保留关键事实。"
)


# ═══════════════════════════════════════════════════════════════
# tokenizer 选型
# ═══════════════════════════════════════════════════════════════


def estimate_tokens(text: str) -> int:
    """估算文本 token 数。

    - 优先 ``tiktoken``（已装）：用 ``cl100k_base`` 编码（DeepSeek/GPT 通用近似），精确。
    - 否则：字符近似（4 char ≈ 1 token），偏粗略但零依赖。

    实现时选型：tiktoken 已在环境可用（``import tiktoken`` 成功），走精确路径。
    """
    if not text:
        return 0
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:  # pragma: no cover — 降级分支，tiktoken 缺失时保护
        # 字符近似：4 字符 ≈ 1 token
        return max(1, len(text) // 4)


def _extract_part_text(content) -> str:
    """从单个 part 载荷提取文本供 token 计数/摘要。"""
    if isinstance(content, str):
        return content
    if isinstance(content, (dict, list)):
        try:
            return json.dumps(content, ensure_ascii=False, default=str)
        except Exception:
            return str(content)
    return ""


def _extract_message_text(msg) -> str:
    """从 ModelMessage 提取文本内容（跳过超大 tool return，与旧 executor 一致）。

    迁自 ``executor._extract_message_text``，逻辑不变：
    - 优先遍历 ``parts`` 取各 part 的 ``content``/``args`` 文本；
    - 超长 tool return（>500）截断，避免长文本注入摘要/token 计数。
    """
    parts = getattr(msg, "parts", None)
    if parts:
        texts: list[str] = []
        for p in parts:
            content = getattr(p, "content", None)
            if content is None:
                content = getattr(p, "args", None)
            txt = _extract_part_text(content)
            if txt:
                if len(txt) > 500:
                    txt = txt[:500] + "..."
                texts.append(txt)
        return " ".join(texts)
    content = getattr(msg, "content", None)
    return _extract_part_text(content)


def estimate_messages_tokens(messages: list) -> int:
    """估算消息列表的总输入 token。

    ``sum(estimate_tokens(extract_text(msg)) for msg in messages)``——
    对每条消息提取文本后累加 token 数（压缩触发判定用）。
    """
    total = 0
    for msg in messages:
        text = _extract_message_text(msg)
        total += estimate_tokens(text)
    return total


# ═══════════════════════════════════════════════════════════════
# AI 早期消息摘要（迁自旧 executor._summarize_history，逻辑不变）
# ═══════════════════════════════════════════════════════════════


async def _summarize(early: list[ModelMessage]) -> str:
    """对早期对话消息做一行式摘要（≤40字）。

    迁自 ``executor._summarize_history``，逻辑不变：极简 AI 调用（~100 input + ~50 output
    tokens），失败静默降级返回空字符串。调用方（executor）已把本函数的 AI 调用 mock 化测试。
    """
    parts: list[str] = []
    for msg in early:
        text = _extract_message_text(msg)
        if text and len(text) > 10:
            parts.append(text[:200])
    if len(parts) <= 2:
        return ""

    try:
        from app.modules.safety.service.config import create_ai_service

        ai = create_ai_service("text")
        try:
            result = await ai.chat(
                messages=[
                    {"role": "system", "content": _HISTORY_SUMMARY_PROMPT},
                    {"role": "user", "content": "\n".join(parts[:20])},
                ],
                response_format="text",
                temperature=0.0,
                max_tokens=64,
            )
        finally:
            await ai.close()
        return result.strip()
    except Exception:
        logger.debug("History summarization failed, skipping", exc_info=True)
        return ""


# ═══════════════════════════════════════════════════════════════
# 压缩主入口
# ═══════════════════════════════════════════════════════════════


def _compact_message(
    messages: list[ModelMessage],
    summary: str,
    first_msg: ModelMessage,
) -> list[ModelMessage]:
    """构造"摘要 system 消息 + 最近 N 条原文"的压缩结果。

    复用旧 ``executor._compress_history`` 的容器类型推断（用原列表首条消息的类型构造），
    保证 Pydantic AI ``ModelMessage`` 类型一致。
    """
    summary_msg = type(first_msg)(parts=[SystemPromptPart(content=f"{SUMMARY_PREFIX} {summary}")])
    return [summary_msg] + list(messages)


async def maybe_compact(messages: list[ModelMessage], deps=None) -> list[ModelMessage]:
    """token 压力压缩主入口。

    1. 算派生消息列表的总 input token（``estimate_messages_tokens``）。
    2. 超 ``_COMPACTION_THRESHOLD``(24k) → 早期消息（除最近 ``_SUMMARY_KEEP_RECENT`` 条）做
       AI 摘要（复用 ``_summarize``），首位注入摘要 system 消息 + 保留最近 N 条原文。
    3. 不超 → 原样返回（noop）。

    ``deps`` 保留参数签名以对齐调用点（executor 传入），当前不消费（摘要 AI 动态建实例）。
    """
    if not messages:
        return messages

    total = estimate_messages_tokens(messages)
    if total < _COMPACTION_THRESHOLD:
        return messages

    # 早期消息（除最近 N 条）做摘要；消息不足时整体视为 early
    recent = messages[-_SUMMARY_KEEP_RECENT:]
    early = messages[:-_SUMMARY_KEEP_RECENT] if len(messages) > _SUMMARY_KEEP_RECENT else []

    summary = await _summarize(early) if early else ""
    if not summary:
        # 摘要失败/为空：不得截断 —— 返回原始 messages（宁可暂时超阈值也不丢上下文）
        logger.warning(
            "History summarization failed/empty — skipping compaction, "
            "returning %d original messages", len(messages),
        )
        return messages
    return _compact_message(recent, summary, messages[0])
