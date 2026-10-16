"""token 驱动压缩（S6）。

解决"按消息条数触发"的缺陷：一条 tool return 可能 10k token，条数无法反映真实上下文
压力。改为按派生消息列表估算 input token，超过阈值（12k）对早期事件做摘要压缩、
保留最近 ``_SUMMARY_KEEP_RECENT`` 轮原文；压缩在后台任务执行，本轮照常返回、下轮生效。

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
# 1-B：基准 24k → 12k（减法后单轮上下文预算整体收紧，压缩更早介入）。
_COMPACTION_BASE_THRESHOLD = 12_000    # 基准 input token 阈值，不含 system+tool 开销
# system+tool 固定开销估算：agent.md（瘦身后 <10KB ≈ 3.5k token）+ 常驻工具 schema
# 2-6k token（路由命中子集更小），保守取 6k；消息增长阈值需扣除，否则先顶窗口才压缩。
_ESTIMATED_SYSTEM_TOOL_OVERHEAD = 6_000
# 有效触发阈值 = 基准 12k − system/tool 开销 6k（计算口径：12k 保持不变，实际判定线 6k）
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


def _extract_message_text(msg, *, cap: int | None = None) -> str:
    """从 ModelMessage 提取文本内容。

    迁自 ``executor._extract_message_text``：
    - 优先遍历 ``parts`` 取各 part 的 ``content``/``args`` 文本；
    - ``cap`` 非 None 时超长文本截断（摘要输入防注入；token 计数传 None 用全文——
      1-B 修复：旧实现对计数也截 500 字符，4KB 工具结果被低估 ~8 倍，阈值形同虚设）。
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
                if cap is not None and len(txt) > cap:
                    txt = txt[:cap] + "..."
                texts.append(txt)
        return " ".join(texts)
    content = getattr(msg, "content", None)
    return _extract_part_text(content)


def estimate_messages_tokens(messages: list) -> int:
    """估算消息列表的总输入 token（全文口径，无截断）。"""
    total = 0
    for msg in messages:
        total += estimate_tokens(_extract_message_text(msg))
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


# ═══════════════════════════════════════════════════════════════
# 1-B 后台压缩：本轮照常返回，压缩结果下轮生效
# ═══════════════════════════════════════════════════════════════
# 主链路历史来自 agent_sessions.message_history（每轮 = 旧历史前缀 + 新增尾部）：
# 后台任务对「本轮输入历史」跑 maybe_compact 并缓存，下一轮前缀命中即替换——
# 消除旧内联实现的「偶发一整轮摘要 AI 延迟尖刺」。进程内缓存，重启自愈（重新触发）。

_BG_COMPACT_CACHE: dict[str, dict] = {}   # session_id → {"base": msgs, "compacted": msgs}
_BG_PENDING: dict[str, list] = {}         # session_id → 正在后台压缩的 base（防重复调度）
_BG_COMPACT_CACHE_MAX = 16                # 缓存会话数上限（超出淘汰最旧）
_BG_TASKS: set = set()                    # 强引用防 GC（done 后自动移除）


def apply_cached_compaction(messages: list, deps=None) -> list:
    """应用上一轮后台压缩结果：历史前缀与缓存 base 完全一致时替换为压缩版。

    前缀不匹配（历史被其它路径改写/会话重置）则原样返回，保守不压缩。
    """
    key = str(getattr(deps, "session_id", "") or "")
    if not key or not messages:
        return messages
    entry = _BG_COMPACT_CACHE.get(key)
    if not entry:
        return messages
    base = entry["base"]
    if len(messages) <= len(base) or messages[: len(base)] != base:
        return messages
    return list(entry["compacted"]) + list(messages[len(base):])


def schedule_background_compaction(messages: list, deps=None) -> None:
    """超阈值时调度后台压缩任务（不阻塞本轮返回）。

    - 未超阈值 / 会话无 id / 消息过少：直接返回（估算零 AI 调用）。
    - 同 base 已有缓存或已在压缩中：跳过（防每轮重复调度）。
    """
    import asyncio

    key = str(getattr(deps, "session_id", "") or "")
    if not key or len(messages) < _SUMMARY_KEEP_RECENT + 2:
        return
    if estimate_messages_tokens(messages) < _COMPACTION_THRESHOLD:
        return
    cached = _BG_COMPACT_CACHE.get(key)
    if cached and cached["base"] == messages:
        return
    pending = _BG_PENDING.get(key)
    if pending == messages:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # 同步上下文（脚本/测试直调）无事件循环：不调度，生产链路下轮会再触发
        logger.debug("schedule_background_compaction: no running loop, skip")
        return
    _BG_PENDING[key] = list(messages)
    task = loop.create_task(_bg_compact(key, list(messages)))
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)


async def _bg_compact(session_key: str, base: list) -> None:
    """后台执行 maybe_compact 并写入缓存；任何失败静默（下轮可重新触发）。"""
    try:
        compacted = await maybe_compact(list(base))
        if compacted == base:
            return  # 未超阈值或摘要失败（maybe_compact 原样返回）
        if (
            session_key not in _BG_COMPACT_CACHE
            and len(_BG_COMPACT_CACHE) >= _BG_COMPACT_CACHE_MAX
        ):
            _BG_COMPACT_CACHE.pop(next(iter(_BG_COMPACT_CACHE)), None)
        _BG_COMPACT_CACHE[session_key] = {
            "base": list(base),
            "compacted": compacted,
        }
    except Exception:
        logger.debug("Background compaction failed", exc_info=True)
    finally:
        _BG_PENDING.pop(session_key, None)
