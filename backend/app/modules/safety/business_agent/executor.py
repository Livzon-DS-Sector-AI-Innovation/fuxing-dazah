"""业务 Agent 执行器 —— tool-calling 循环 + 权限 + 确认流。

核心流程::

    run_turn(user_message, deps)
      → agent.run() → 生成 DeferredToolRequests（写操作挂起）
      → 权限校验 → 构建 PendingActionData
      → 返回 AgentRunResult（含 pending_action 信息）
    resume(session, action_id, approved)
      → 构建 DeferredToolResults → agent.run(message_history=..., deferred_tool_results=...)
      → 返回最终执行结果

所有对话历史通过 ``ModelMessagesTypeAdapter`` 序列化后存储在 session_store（持久层）
中；executor 自身是纯无状态函数，每次调用独立创建 agent 运行。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import TYPE_CHECKING

from pydantic_ai import (
    DeferredToolRequests,
    DeferredToolResults,
    ModelMessagesTypeAdapter,
    ToolDenied,
)
from pydantic_ai.messages import ModelMessage

from app.modules.safety.business_agent.agent import business_agent
from app.modules.safety.business_agent.permissions import check as perm_check
from app.modules.safety.business_agent.rules import check_output
from app.modules.safety.business_agent.schemas import (
    PendingActionData,
    SafetyDeps,
)
from app.modules.safety.business_agent.tools.registry import (
    TOOL_KIND,
    register_all_tools,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ── 确保工具在 agent 上注册一次 ──
register_all_tools(business_agent)


# ═══════════════════════════════════════════════════════════════
# 公共接口
# ═══════════════════════════════════════════════════════════════


async def run_turn(
    user_message: str,
    deps: SafetyDeps,
    *,
    message_history: list[ModelMessage] | None = None,
) -> dict:
    """执行一个对话回合。

    1. 注入 user message → agent.run()
    2. 若模型尝试调用写工具 → 停止 + 返回 pending_action 给入口层做确认
    3. 若模型直接返回文本 → 做禁语检查 + 返回 answer

    Args:
        user_message: 用户输入文本
        deps: 注入的 DB session / 用户身份 / 角色
        message_history: 历史消息列表（首次为 None）

    Returns:
        {
            "answer": str,           # Agent 的自然语言回复
            "messages": [...],       # 本轮后的完整消息列表（调用方持久化）
            "pending_action": PendingActionData | None,  # 非 None 表示有待确认的写操作
            "sources": list[dict] | None,  # 知识库检索的法规来源（含 feishu_url 可点击链接）
        }
    """
    # 构建 deps 的 hashable 副本用于调试
    role_tag = deps.role or "unknown"
    user_tag = deps.person.name if deps.person else "anonymous"
    logger.info("run_turn: user=%r role=%r session=%s", user_tag, role_tag, deps.session_id)

    # ── 场景熔断：agent_chat 停用 → 不触模型、不建审计作用域，直接返回停用文案 ──
    #   绑定不生效（Agent 模型模块级创建 _PROVIDER/_MODEL，重启生效——一期决策），
    #   前端在 agent_chat 绑定列标注「重启生效」（backend-design §5.1）。
    from app.modules.safety.ai_config.scenario_store import scenario_store

    if not scenario_store.is_enabled("agent_chat"):
        logger.info("agent_chat 场景已停用，run_turn 直接返回停用文案")
        return {
            "answer": "AI 助手功能已停用，请联系管理员。",
            "messages": message_history or [],
            "pending_action": None,
            "sources": None,
        }

    # S3 事件流：入口 user_message 事件（双写期，逐事件 append）
    if deps.session_id:
        try:
            import uuid as _uuid

            _sid = _uuid.UUID(str(deps.session_id))
            from app.modules.safety.business_agent.core import events
            await events.append_event(
                deps.db, session_id=_sid, event_type=events.EventType.USER_MESSAGE,
                payload={"content": user_message},
            )
            await deps.db.flush()
        except Exception:
            logger.exception("run_turn: append user_message 事件失败（不影响主流程）")

    started = time.monotonic()
    trace_id: str | None = None
    try:
        # 审计作用域：最外层开 safety.agent_chat 根 span（tracing 启用时），
        # 并让工具内嵌套的知识库 AI 调用继承 用户/会话/渠道/trace_id
        from app.modules.safety.ai_audit import ai_audit_scope

        with ai_audit_scope(
            scenario="agent_chat",
            session_id=deps.session_id or None,
            channel=deps.channel,
            user_name=deps.person.name if deps.person else None,
        ) as audit_ctx:
            trace_id = audit_ctx.trace_id
            result = await _agent_run(user_message, deps, message_history=message_history)
    except Exception as e:
        logger.exception("agent run 失败")
        err_msg = f"抱歉，处理您的请求时发生内部错误，请输入/new重置会话后再尝试提问：{type(e).__name__}: {e}"
        await _audit_agent_turn(
            deps, user_message,
            answer=None, result=None, pending=None, sources=None, guard_hits=None,
            status="failed", error=f"{type(e).__name__}: {e}",
            latency_ms=int((time.monotonic() - started) * 1000),
            trace_id=trace_id,
        )
        return {
            "answer": err_msg,
            "messages": message_history or [],
            "pending_action": None,
            "sources": None,
        }

    latency_ms = int((time.monotonic() - started) * 1000)

    # → 提取知识库检索的法规来源
    sources = _extract_knowledge_sources(result)

    # → 异步记忆提取（不阻塞回复，失败不影响业务）S5：从事件流提取
    await _schedule_memory_extraction_from_events(deps)

    # → 检查是否有待确认的写操作
    pending = _extract_pending_action(result)
    if pending:
        # S3 事件流：写工具挂起 → approval_requested（工具调用/结果由残余消息事件承载）
        await _append_approval_requested_event(deps, pending)
        await _record_tool_events(deps, result)
        await _append_assistant_and_turn_end(
            deps, content=_pending_prompt(pending), status="success",
        )
        await _audit_agent_turn(
            deps, user_message,
            answer=_pending_prompt(pending), result=result, pending=pending,
            sources=sources, guard_hits=None, status="success", latency_ms=latency_ms,
            trace_id=trace_id,
        )
        return {
            "answer": _pending_prompt(pending),
            "messages": _serialize_messages(result),
            "pending_action": pending,
            "sources": sources,
        }

    # → 硬拦截：日报工具的特殊处理 — 直接透传 markdown_report，不让模型改写
    daily_report_md = _extract_daily_report_markdown(result)
    if daily_report_md:
        answer = daily_report_md
    else:
        # → 纯文本回复：做禁语检查
        answer = _strip_reference_section(
            result.output if isinstance(result.output, str) else str(result.output)
        )
    guard = check_output(answer)
    if not guard.ok:
        logger.warning("agent 输出命中禁语: %s", guard.banned_hits)

    # S3 事件流：工具调用/结果逐事件 + assistant_message + turn_end（双写期）
    await _record_tool_events(deps, result)
    await _append_assistant_event(
        deps, content=answer,
        usage=_extract_usage_dict(result),
    )
    await _append_turn_end_event(deps, status="success")

    await _audit_agent_turn(
        deps, user_message,
        answer=answer, result=result, pending=None, sources=sources,
        guard_hits=guard.banned_hits if not guard.ok else None,
        status="success", latency_ms=latency_ms,
        trace_id=trace_id,
    )

    return {
        "answer": answer,
        "messages": _serialize_messages(result),
        "pending_action": None,
        "sources": sources,
    }


async def resume(
    session_id: str,
    deps: SafetyDeps,
    *,
    action_id: str,
    approved: bool,
    message_history_raw: list[dict],
) -> dict:
    """恢复被挂起的写操作执行。

    基于之前 run_turn 返回的 message_history，用用户的选择构建
    DeferredToolResults 并调用 agent.run() 继续，使其执行被允许的工具。

    Args:
        session_id: 会话 ID
        deps: 注入的 DB session 等
        action_id: 待确认动作的 ID（run_turn 返回的 pending_action 中的 action_id）
        approved: True=确认执行，False=取消
        message_history_raw: run_turn 返回的消息列表的 JSON-dump 后的原始列表

    Returns:
        {
            "answer": str,
            "messages": [...],  # 更新后的消息列表
            "executed": bool,   # True=已执行，False=已拒绝/失败
        }
    """
    messages: list[ModelMessage] = ModelMessagesTypeAdapter.validate_python(
        message_history_raw
    )

    # S3 事件流：resume 入口 — approval_resolved（用户决定：确认/取消）
    sid = _session_uuid(session_id)
    if sid is not None:
        try:
            from app.modules.safety.business_agent.core import events
            await events.append_event(
                deps.db, session_id=sid, event_type=events.EventType.APPROVAL_RESOLVED,
                payload={
                    "action_id": action_id,
                    "approved": approved,
                    "by": deps.person.name if deps.person else None,
                },
            )
            await deps.db.flush()
        except Exception:
            logger.exception("resume: append approval_resolved 事件失败（不影响主流程）")

    # 从历史中找到挂起的请求
    deferred_requests = _find_deferred_in_history(messages)
    if deferred_requests is None:
        return {
            "answer": "该操作已过期或不存在，请重新发起。",
            "messages": message_history_raw,
            "executed": False,
        }

    results = DeferredToolResults()
    if approved:
        # 权限再校验：在「执行时」再次确认当前用户是否有权
        for call in deferred_requests.approvals:
            if not perm_check(deps.role, call.tool_name):
                results.approvals[call.tool_call_id] = ToolDenied(
                    f"权限不足：角色 {deps.role!r} 无权执行 {call.tool_name!r}"
                )
                logger.warning(
                    "resume: 权限拒绝 tool=%r role=%r user=%r",
                    call.tool_name,
                    deps.role,
                    deps.person.name if deps.person else "?",
                )
            else:
                results.approvals[call.tool_call_id] = True
    else:
        for call in deferred_requests.approvals:
            results.approvals[call.tool_call_id] = ToolDenied("用户取消了该操作")

    logger.info(
        "resume: action_id=%s approved=%s tools=%s",
        action_id,
        approved,
        [c.tool_name for c in deferred_requests.approvals],
    )

    trace_id: str | None = None
    try:
        from app.modules.safety.ai_audit import ai_audit_scope

        with ai_audit_scope(
            scenario="agent_chat",
            session_id=session_id or None,
            channel=deps.channel,
            user_name=deps.person.name if deps.person else None,
        ) as audit_ctx:
            trace_id = audit_ctx.trace_id
            final = await _agent_run(
                None,  # 无新用户消息，仅执行 approved tools
                deps,
                message_history=messages,
                deferred_tool_results=results,
            )
    except Exception:
        logger.exception("resume 执行失败")
        return {
            "answer": "操作执行失败，请重试或联系管理员。",
            "messages": message_history_raw,
            "executed": False,
        }

    answer = _strip_reference_section(
        final.output if isinstance(final.output, str) else str(final.output)
    )

    # S3 事件流：resume 收尾 — tool_call/tool_result 逐事件 + assistant_message + turn_end
    await _record_tool_events(deps, final)
    await _append_assistant_event(deps, content=answer, usage=_extract_usage_dict(final))
    await _append_turn_end_event(
        deps, status="success" if approved else "failed",
        error=("用户取消了该操作" if not approved else None),
    )

    # ── 审计留痕：AI 行为（ai_call_audits）+ 人工确认动作（audit.logs） ──
    tool_names = [c.tool_name for c in deferred_requests.approvals]
    await _audit_agent_resume(
        deps, session_id,
        action_id=action_id, approved=approved,
        tool_names=tool_names, answer=answer, result=final,
        trace_id=trace_id,
    )

    return {
        "answer": answer,
        "messages": _serialize_messages(final),
        "executed": approved,
    }


# ═══════════════════════════════════════════════════════════════
# 内部辅助
# ═══════════════════════════════════════════════════════════════


def _session_uuid(deps_or_id) -> uuid.UUID | None:
    """从 deps.session_id 或字符串解析会话 UUID；失败返回 None。"""
    import uuid as _uuid
    sid = deps_or_id
    if hasattr(sid, "session_id"):
        sid = sid.session_id
    if not sid:
        return None
    try:
        return _uuid.UUID(str(sid))
    except (ValueError, AttributeError, TypeError):
        return None


async def _record_tool_events(deps: SafetyDeps, result) -> None:
    """S3：把本轮 agent.run() 产生的 tool_call / tool_result 逐事件 append（双写期）。

    从 ``result.all_messages()`` 的新消息中提取 tool-call / tool-return parts，
    payload 存 Pydantic AI part 原文，保证 ``derive_messages`` 可无损重建。
    失败仅告警，不阻塞主流程。
    """
    sid = _session_uuid(deps)
    if sid is None:
        return
    try:
        from app.modules.safety.business_agent.core import events

        for msg in result.all_messages():
            parts = getattr(msg, "parts", []) or []
            for p in parts:
                if p.part_kind == "tool-call":
                    await events.append_event(
                        deps.db, session_id=sid, event_type=events.EventType.TOOL_CALL,
                        payload={
                            "tool_name": p.tool_name,
                            "args": p.args,
                            "tool_call_id": p.tool_call_id,
                        },
                    )
                elif p.part_kind == "tool-return":
                    await events.append_event(
                        deps.db, session_id=sid, event_type=events.EventType.TOOL_RESULT,
                        payload={
                            "tool_name": p.tool_name,
                            "tool_call_id": p.tool_call_id,
                            "ok": p.outcome != "failed",
                            "data": p.content,
                            "denied": p.outcome == "denied",
                        },
                    )
        await deps.db.flush()
    except Exception:
        logger.exception("run_turn: append tool 事件失败（不影响主流程）")


async def _append_assistant_event(
    deps: SafetyDeps, *, content: str, usage: dict | None = None,
) -> None:
    """S3 事件流：追加 assistant_message 事件。"""
    sid = _session_uuid(deps)
    if sid is None:
        return
    try:
        from app.modules.safety.business_agent.core import events
        await events.append_event(
            deps.db, session_id=sid, event_type=events.EventType.ASSISTANT_MESSAGE,
            payload={"content": content, "usage": usage or {}},
        )
        await deps.db.flush()
    except Exception:
        logger.exception("append assistant_message 事件失败（不影响主流程）")


async def _append_turn_end_event(deps: SafetyDeps, *, status: str, error: str | None = None) -> None:
    """S3 事件流：追加 turn_end 事件。"""
    sid = _session_uuid(deps)
    if sid is None:
        return
    try:
        from app.modules.safety.business_agent.core import events
        await events.append_event(
            deps.db, session_id=sid, event_type=events.EventType.TURN_END,
            payload={"status": status, "error": error},
        )
        await deps.db.flush()
    except Exception:
        logger.exception("append turn_end 事件失败（不影响主流程）")


async def _append_assistant_and_turn_end(deps: SafetyDeps, *, content: str, status: str) -> None:
    """S3 事件流：追加 assistant_message + turn_end（写工具挂起分支收尾）。"""
    await _append_assistant_event(deps, content=content)
    await _append_turn_end_event(deps, status=status)


def _extract_usage_dict(result) -> dict:
    """从 agent.run() 结果提取 token 用量为 dict（失败返回空 dict）。"""
    in_t, out_t = _extract_usage(result)
    return {"in": in_t, "out": out_t}


async def _derive_session_history(deps: SafetyDeps) -> list[ModelMessage] | None:
    """S3：从事件表派生会话历史（优先于旧 message_history）。

    读 ``agent_session_events`` 事件 → ``core/events.derive_messages`` 重建 LLM 消息。
    失败/无事件返回 None，让上层回退旧列。
    """
    sid = _session_uuid(deps)
    if sid is None:
        return None
    try:
        from app.modules.safety.business_agent.core import events
        evs = await events.get_events(deps.db, sid)
        return events.derive_messages(evs) if evs else None
    except Exception:
        logger.exception("_derive_session_history 失败（回退旧 message_history）")
        return None


def _extract_daily_report_markdown(result) -> str | None:
    """从 agent.run() 结果中提取 generate_daily_report 的 markdown_report。

    日报由 ReportBuilder 预生成完整模板，不应被模型二次加工。
    此函数检测工具调用链中是否有 generate_daily_report，有则直接返回其 markdown_report，
    外加一句简短引导语，完全绕过模型的文本生成。
    """
    try:
        parts = getattr(result, "all_parts", None) or []
        for part in parts:
            if getattr(part, "part_kind", "") != "tool-return":
                continue
            tool_name = getattr(part, "tool_name", "")
            if tool_name != "generate_daily_report":
                continue
            content = getattr(part, "content", None)
            if isinstance(content, dict) and content.get("markdown_report"):
                md = content["markdown_report"]
                return f"📋 {md}"
    except Exception:
        pass
    return None


def _strip_reference_section(text: str) -> str:
    """移除文本末尾模型可能追加的参考法规列表区块。

    作为硬护栏：即使 agent.md 禁止了参考法规列表，模型仍可能不遵守。
    此函数在 answer 返回给调用方前做最终清理。
    """
    if not text:
        return text

    import re

    # ── 模式 1：含关键词标题的区块 ──
    # 找所有关键词中最靠前（最先出现）的位置，从此处截断
    best_keyword = ""
    best_pos = len(text)
    for keyword in ("参考法规", "关联制度文件", "法规依据", "参考来源"):
        pos = text.rfind(keyword)
        if pos >= 0 and pos < best_pos:
            best_pos = pos
            best_keyword = keyword
    if best_pos < len(text):
        before = text[:best_pos]
        for sep in ("\n---", "\n**", "\n📚", "\n- "):
            sep_pos = before.rfind(sep)
            if sep_pos > 0 and best_pos - sep_pos < 500:
                logger.info("EXECUTOR strip ref section: keyword=%r sep=%r cut_at=%d", best_keyword, sep, sep_pos)
                return text[:sep_pos].rstrip()
        if best_pos > len(text) * 0.6:
            logger.info("EXECUTOR strip ref section fallback: keyword=%r cut_at=%d", best_keyword, best_pos)
            return text[:best_pos].rstrip()

    # ── 模式 2：末尾连续的 "[N] ... 查看原文" 行（无标题纯列表）──
    # 从末尾向前扫描，收集连续的编号引用行，检测到即整块移除
    _ref_line_re = re.compile(
        r"^(\[(\d+)\]\s+.+查看原文"          # [N] 《法规》 — [查看原文](url)
        r"|《[^》]+》\[(\d+)\].*"             # 《法规名》[N]
        r"|\[(\d+)\]\s+《[^》]+》"            # [N] 《法规名》
        r")"
    )
    lines = text.split("\n")
    # 从最后一行向前找到连续的引用行
    ref_start = None
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if not stripped:
            continue  # 跳过空行
        if _ref_line_re.match(stripped):
            ref_start = i
        else:
            break  # 遇到非引用行，停止

    if ref_start is not None:
        # ref_start 是第一条引用行的索引。确认至少有 2 条引用才移除（避免误杀单条内联引用）
        ref_count = sum(
            1 for j in range(ref_start, len(lines))
            if _ref_line_re.match(lines[j].strip())
        )
        if ref_count >= 2:
            # 移除引用区块前可能的空行和分隔符
            cut = ref_start
            while cut > 0 and (
                not lines[cut - 1].strip()
                or lines[cut - 1].strip().startswith("---")
                or lines[cut - 1].strip().startswith("**")
                or lines[cut - 1].strip().startswith("- ")
            ):
                cut -= 1
            logger.info("EXECUTOR strip ref lines: count=%d cut_at_line=%d", ref_count, cut)
            return "\n".join(lines[:cut]).rstrip()

    return text


# ── History 压缩（S6 已迁至 core/compaction.py，此处只留常量以作兼容参考） ──
#    压缩逻辑/摘要 AI 调用已迁至 ``core/compaction.maybe_compact``（token 驱动，超 24k 触发）。
#    旧符号 _summarize_history/_co)
#    常量保留兼容（外部若引用不 404，但不参与新触发逻辑）。
_MAX_HISTORY_MESSAGES = 20       # 最多保留 20 条消息（~10 轮对话，compaction 兼容参考）
_SUMMARY_TRIGGER_LENGTH = 20     # 旧条数触发阈值（已弃，token 驱动取代）
_SUMMARY_KEEP_RECENT = 10        # 保留最近 10 条原文不参与摘要（core/compaction 沿用同名常量）


async def _agent_run(
    user_message: str | None,
    deps: SafetyDeps,
    *,
    message_history: list[ModelMessage] | None = None,
    deferred_tool_results: DeferredToolResults | None = None,
):
    """统一的 agent.run() 调用包装。"""
    # S3 事件流：读历史优先从事件表 derive（derive_messages），回退旧 message_history。
    # deps.db 通常为空（executor 无状态），故仅当存在时才尝试事件派生。
    if message_history is None and deps.db is not None and deps.session_id:
        try:
            _derived = await _derive_session_history(deps)
            if _derived:
                message_history = _derived
        except Exception:
            logger.exception("_agent_run: 事件派生历史失败，回退 message_history（不影响主流程）")

    # pydantic-ai 2.8.0 的 resolve_conversation_id 遍历 message_history
    # 并访问 .conversation_id 属性；从 JSONB 读出的 raw dict 需先反序列化。
    if message_history and isinstance(message_history[0], dict):
        message_history = ModelMessagesTypeAdapter.validate_python(message_history)

    # ── History 压缩：防止长对话 token 线性增长 ──
    #    S6：触发从"消息条数 ≥20"改为"token 压力超 24k"（tokenizer 估算），
    #    迁到 core/compaction.maybe_compact（复用 _summarize_history 的 AI 摘要，不引入新调用）。
    if message_history:
        from app.modules.safety.business_agent.core.compaction import maybe_compact

        message_history = await maybe_compact(message_history, deps)

    # ── S4：system-prompt 分节组装（persona/runtime_date/user_context/memories/tool_catalog）
    #    替代旧 MemoryInjector 的 build_user_context + inject_memory_context 前缀拼接。
    effective_message = user_message or ""
    if effective_message and deps.person and deps.person.user_id:
        from app.modules.safety.business_agent.core.prompt import ALL_SECTIONS, assemble

        # 检索相关记忆（Phase 3，供 memories 节渲染）
        memories = await _retrieve_memories(
            deps.person.user_id, effective_message, deps.db,
        )

        prompt_prefix = assemble(
            ALL_SECTIONS,
            deps,
            context={"memories": memories or [], "query": effective_message},
        )
        if prompt_prefix:
            effective_message = f"{prompt_prefix}\n---\n{effective_message}"

    # ── 按需选择工具子集（减少 tool definitions 开销 66%）─────────
    agent = business_agent  # fallback: all tools
    if effective_message and deferred_tool_results is None:
        from app.modules.safety.business_agent.agent import get_agent_for_tools
        from app.modules.safety.business_agent.tool_selector import select_tool_names

        # 用原始用户消息做意图词匹配（不用拼了 prompt_prefix 的 effective_message，
        # 否则 agent.md/上下文里的"法规/隐患/制度"等词会污染意图判定 → 全量注册工具）
        tool_names = select_tool_names(user_message or "")
        if tool_names:
            agent = get_agent_for_tools(tool_names)

    return await agent.run(
        effective_message,
        deps=deps,
        message_history=message_history or [],
        deferred_tool_results=deferred_tool_results,
    )


def _serialize_messages(result) -> list[dict]:
    """从 agent run result 中提取完整消息列表并序列化为 JSONB 友好的列表。

    使用 dump_json → json.loads 确保 datetime 等非 JSON 类型转为 ISO 字符串，
    避免 SQLAlchemy JSONB 列写入时抛出 "Object of type datetime is not JSON serializable"。
    """
    try:
        msgs = result.all_messages()
        json_str = ModelMessagesTypeAdapter.dump_json(msgs)
        return json.loads(json_str)
    except Exception:
        logger.exception("序列化消息失败")
        return []


def _extract_pending_action(result) -> PendingActionData | None:
    """从 agent run result 中提取 DeferredToolRequests 并转为 PendingActionData。"""
    output = result.output
    if not isinstance(output, DeferredToolRequests):
        return None

    summaries: list[str] = []
    tool_names: list[str] = []
    all_args: dict[str, dict] = {}

    for call in output.approvals:
        tool_name = call.tool_name
        args = call.args_as_dict() if call.args else {}
        tool_names.append(tool_name)
        all_args[tool_name] = args

        summaries.append(_format_tool_summary(tool_name, args))

    summary = "\n\n".join(summaries) if summaries else "执行待确认操作"
    primary_tool = tool_names[0] if tool_names else "unknown"

    return PendingActionData(
        tool_name=primary_tool,
        arguments=all_args.get(primary_tool, {}),
        summary=summary,
    )


def _format_tool_summary(tool_name: str, args: dict) -> str:
    """为确认卡片生成人类可读的工具执行摘要。"""
    # ── generate_guardian_subsidy：监护补贴生成确认卡 ──
    if tool_name == "generate_guardian_subsidy":
        return _format_guardian_subsidy_summary(args)

    # ── 办公写工具：中文描述「即将创建/修改什么」 ──
    if tool_name in _OFFICE_WRITE_TOOL_NAMES:
        return _format_office_summary(tool_name, args)

    # ── 通用格式 ──
    is_write = TOOL_KIND.get(tool_name, True)
    verb = "写入" if is_write else "操作"
    return f"将在 {tool_name!r}（{verb}）中执行：{_format_args(args)}"


_OFFICE_WRITE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "office_create_docx",
        "office_create_sheet",
        "office_write_sheet",
        "office_create_base",
        "office_create_slides",
        "office_generate_docx_pdf",
        "office_upload_file",
    }
)


def _format_office_summary(tool_name: str, args: dict) -> str:
    """为办公写工具生成面向用户的中文执行方案摘要。"""
    title = args.get("title") or ""
    if tool_name == "office_create_docx":
        blocks = args.get("blocks") or []
        count = len(blocks) if isinstance(blocks, list) else 0
        suffix = f"，并写入 {count} 个内容块" if count else ""
        return f"将在飞书新建云文档《{title}》{suffix}"

    if tool_name == "office_create_sheet":
        rows = args.get("rows") or []
        count = len(rows) if isinstance(rows, list) else 0
        suffix = f"，并写入 {count} 行数据" if count else ""
        return f"将在飞书新建电子表格《{title}》{suffix}"

    if tool_name == "office_write_sheet":
        sheet_range = args.get("sheet_range", "")
        return (
            f"将写入飞书电子表格 {args.get('spreadsheet_token', '')} "
            f"的区域 {sheet_range}"
        )

    if tool_name == "office_create_base":
        tables = args.get("tables") or []
        count = len(tables) if isinstance(tables, list) else 0
        suffix = f"，含 {count} 张数据表定义" if count else ""
        return f"将在飞书新建多维表格《{title}》{suffix}"

    if tool_name == "office_create_slides":
        return f"将在飞书新建幻灯片《{title}》"

    if tool_name == "office_generate_docx_pdf":
        file_type = args.get("file_type", "docx") or "docx"
        return f"将本地生成 {str(file_type).upper()} 文件《{title}》"

    if tool_name == "office_upload_file":
        return f"将上传文件 {args.get('file_name') or args.get('file_path', '')} 到飞书云空间"

    return f"将执行办公写入工具 {tool_name}：{_format_args(args)}"


def _format_guardian_subsidy_summary(args: dict) -> str:
    """为 generate_guardian_subsidy 生成确认卡摘要。

    票数/监护人/总额在执行时才算得出（生成工具按同参数幂等重拉重算），
    确认卡先给部门/月份/文件名，并说明执行范围。
    """
    dept = args.get("dept_keyword", "")
    year = args.get("year", "")
    month = args.get("month", "")
    filename = args.get("filename") or ""

    lines = [
        "📊 **监护补贴统计（平台作业票）**",
        "",
        f"• 部门关键词：{dept}",
        f"• 统计月份：{year}年{month}月",
        "• 执行内容：从平台重拉作业票（±1 月窗口）→ 按部门/月份/证书匹配整理 → "
        "计算补贴 → 生成 Excel（主表 + 待核对/跳过说明页）→ 回传当前会话",
    ]
    if filename:
        lines.append(f"• 文件名：{filename}")
    return "\n".join(lines)


def _format_args(args: dict) -> str:
    """将工具参数字典格式化为人类可读的单行摘要。

    对于大型 JSON 字段（>80 字符），显示元素计数而非原始内容。
    """
    parts = []
    for k, v in args.items():
        if isinstance(v, str):
            if len(v) > 80:
                # 尝试解析 JSON 数组并显示计数
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        parts.append(f"{k}=[{len(parsed)} 条记录]")
                        continue
                    elif isinstance(parsed, dict):
                        parts.append(f"{k}={{...{len(parsed)} 个字段}}")
                        continue
                except (json.JSONDecodeError, TypeError):
                    pass
                v = v[:57] + "..."
        parts.append(f"{k}={v!r}")
    return ", ".join(parts) if parts else "无参数"


def _pending_prompt(action: PendingActionData) -> str:
    """生成面向用户的「执行方案确认」提示文本。"""
    return (
        f"📋 **执行方案确认**\n\n"
        f"{action.summary}\n\n"
        f"请确认是否执行以上操作。"
    )


def _extract_knowledge_sources(result) -> list[dict] | None:
    """从 agent run result 中提取 knowledge_search 工具返回的法规来源。

    遍历本轮生成的新消息，找到 knowledge_search 的 ToolReturnPart，
    解析其 model_response_str JSON 中的 ``sources`` 字段。

    返回去重后的 sources 列表（按 doc_title 去重），或 None（未调用知识库）。
    """
    try:
        new_messages = result.new_messages()
    except Exception:
        return None

    seen_titles: set[str] = set()
    all_sources: list[dict] = []

    for msg in new_messages:
        parts = getattr(msg, "parts", [])
        for part in parts:
            if getattr(part, "part_kind", None) != "tool-return":
                continue
            if getattr(part, "tool_name", None) != "knowledge_search":
                continue
            # 解析 tool return content 中的 sources
            try:
                data = part.structured_content()
                if not isinstance(data, dict):
                    continue
                srcs = data.get("sources", [])
            except Exception:
                continue
            for s in srcs:
                title = s.get("doc_title", "")
                if title and title not in seen_titles:
                    seen_titles.add(title)
                    all_sources.append(s)

    return all_sources if all_sources else None


def _find_deferred_in_history(
    messages: list[ModelMessage],
) -> DeferredToolRequests | None:
    """从最近的消息历史中回溯找到挂起的写工具调用，重建 DeferredToolRequests。

    挂起发生时，最后一条 ModelResponse 中包含写工具（TOOL_KIND=True）的
    ToolCallPart 且没有对应的 ToolReturn。只检查最近一条 ModelResponse：
    更早的写调用要么已执行、要么已被取消，不应重复恢复。
    """
    from pydantic_ai.messages import ModelResponse, ToolCallPart

    for msg in reversed(messages):
        if isinstance(msg, ModelResponse):
            calls = [
                p for p in msg.parts
                if isinstance(p, ToolCallPart) and TOOL_KIND.get(p.tool_name, False)
            ]
            if calls:
                return DeferredToolRequests(approvals=calls)
            return None  # 最近一条模型回复没有挂起的写调用
    return None


# ═══════════════════════════════════════════════════════════════
# 审计留痕（独立 session，失败仅告警，绝不阻塞对话）
# ═══════════════════════════════════════════════════════════════


def _model_name() -> str:
    """当前 Agent 使用的模型名。"""
    model = business_agent.model
    return getattr(model, "model_name", None) or str(model)


def _extract_usage(result) -> tuple[int | None, int | None]:
    """从 agent run result 提取 token 用量（失败返回 None）。

    pydantic-ai 2.x 中 ``result.usage`` 是属性（RunUsage）；早期版本为方法。
    """
    try:
        usage = result.usage
        if callable(usage):
            usage = usage()
        return usage.input_tokens or None, usage.output_tokens or None
    except Exception:
        return None, None


async def _audit_agent_turn(
    deps: SafetyDeps,
    user_message: str,
    *,
    answer: str | None,
    result,
    pending: PendingActionData | None,
    sources: list[dict] | None,
    guard_hits: list[str] | None,
    status: str,
    latency_ms: int,
    error: str | None = None,
    trace_id: str | None = None,
) -> None:
    """将一轮 Agent 对话写入 safety.ai_call_audits。

    DEPRECATED：轮次级审计将由 core/loop.py 迁入时保留；工具级审计改为
    ``core/pipeline.py::_post_audit`` 单点（scenario="agent_tool_call"）。
    本轮次审计（scenario="agent_chat"）与工具级审计分层不重叠。保留兼容期。
    """
    try:
        from app.modules.safety.ai_audit.store import insert_audit
        from app.modules.safety.business_agent.loader import instructions_version

        input_tokens, output_tokens = (None, None) if result is None else _extract_usage(result)
        extra: dict = {"role": deps.role}
        if pending:
            extra["pending_action"] = {
                "tool_name": pending.tool_name,
                "summary": pending.summary,
            }

        await insert_audit(
            trace_id=trace_id,
            scenario="agent_chat",
            session_id=deps.session_id,
            channel=deps.channel,
            user_name=deps.person.name if deps.person else None,
            model=_model_name(),
            prompt_version=instructions_version(),
            input_text=user_message,
            output_text=answer,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            status=status,
            error=error,
            cited_sources=sources,
            guard_hits=guard_hits,
            extra=extra,
        )
    except Exception:
        logger.exception("agent_chat 审计写入失败（不影响业务）")


async def _audit_agent_resume(
    deps: SafetyDeps,
    session_id: str,
    *,
    action_id: str,
    approved: bool,
    tool_names: list[str],
    answer: str,
    result,
    trace_id: str | None = None,
) -> None:
    """resume 双留痕：AI 行为进 ai_call_audits，人工确认动作进 audit.logs。

    DEPRECATED：resume 的写工具执行将在迁移 core/loop.py 后由管道 ``core/pipeline.py::_post_audit``
    单点审计；本方法保留兼容期（仍承担 action 人工确认留痕的 audit.logs 部分）。
    """
    user_name = deps.person.name if deps.person else None

    # ① AI 行为 → safety.ai_call_audits
    try:
        from app.modules.safety.ai_audit.store import insert_audit
        from app.modules.safety.business_agent.loader import instructions_version

        input_tokens, output_tokens = _extract_usage(result)
        await insert_audit(
            trace_id=trace_id,
            scenario="agent_chat",
            session_id=session_id,
            channel=deps.channel,
            user_name=user_name,
            model=_model_name(),
            prompt_version=instructions_version(),
            input_text=f"[写操作{'确认' if approved else '取消'}] action_id={action_id}",
            output_text=answer,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            status="success",
            extra={
                "action_id": action_id,
                "approved": approved,
                "tools": tool_names,
                "role": deps.role,
            },
        )
    except Exception:
        logger.exception("agent resume 审计写入失败（不影响业务）")

    # ② 人工确认动作 → audit.logs（平台业务操作审计，GB/T 45654 人工干预留痕）
    try:
        import uuid as _uuid

        from app.platform.audit.service import record_audit_log

        try:
            rid = _uuid.UUID(action_id)
        except (ValueError, AttributeError):
            rid = None
        await record_audit_log(
            deps.db,
            action="agent_write_execute" if approved else "agent_write_reject",
            resource_type="agent_pending_action",
            resource_id=rid,
            new_value={"tools": tool_names, "approved": approved},
            extra={"session_id": session_id, "user_name": user_name, "role": deps.role},
        )
    except Exception:
        logger.exception("agent resume 平台审计写入失败（不影响业务）")


# ═══════════════════════════════════════════════════════════════
# 异步记忆提取（Phase 2：后台执行，不阻塞 Agent 回复）
# ═══════════════════════════════════════════════════════════════


async def _append_approval_requested_event(
    deps: SafetyDeps, pending: PendingActionData,
) -> None:
    """S3 事件流：写工具挂起 → 追加 approval_requested 事件。

    payload 记录挂起方案（tool_name / summary / arguments），供审计与重放追溯。
    """
    sid = _session_uuid(deps)
    if sid is None:
        return
    try:
        from app.modules.safety.business_agent.core import events
        await events.append_event(
            deps.db, session_id=sid,
            event_type=events.EventType.APPROVAL_REQUESTED,
            payload={
                "tool_name": pending.tool_name,
                "summary": pending.summary,
                "arguments": pending.arguments,
            },
        )
        await deps.db.flush()
    except Exception:
        logger.exception("append approval_requested 事件失败（不影响主流程）")


async def _schedule_memory_extraction_from_events(deps: SafetyDeps) -> None:
    """调度基于事件流的内存提取任务（fire-and-forget，不阻塞回复）。

    S5：从 ``agent_session_events`` 事件流派生本轮对话并在后台提取记忆入库，
    完全替代旧 ``_schedule_memory_extraction``（后者从瞬态 result 对象扒对话）。
    失败静默降级，不影响主业务。
    """
    import asyncio

    sid = _session_uuid(deps)
    if sid is None or deps.db is None:
        return

    async def _bg_extract():
        try:
            from app.modules.safety.business_agent.core.memory import (
                extract_from_events,
            )

            saved = await extract_from_events(deps.db, sid, deps)
            if saved:
                logger.info(
                    "Memory extraction(events): saved %d facts for user=%s",
                    saved, deps.person.name if deps.person else "?",
                )
        except Exception:
            logger.debug("Background memory extraction(events) failed", exc_info=True)

    asyncio.create_task(_bg_extract())


def _schedule_memory_extraction(
    user_message: str,
    result,
    deps: SafetyDeps,
) -> None:
    """调度后台记忆提取任务（fire-and-forget）。

    DEPRECATED：S5 已由 ``_schedule_memory_extraction_from_events`` 取代（事件流提取，
    不依赖瞬态 result 对象）。保留兼容，不删除。
    """
    import asyncio

    from app.modules.safety.memory.extractor import MemoryExtractor

    answer = ""
    try:
        if hasattr(result, "output"):
            answer = result.output if isinstance(result.output, str) else str(result.output)
    except Exception:
        pass

    if not user_message or not answer:
        return

    async def _bg_extract():
        try:
            extractor = MemoryExtractor()
            session_id = None
            try:
                import uuid as _uuid
                session_id = _uuid.UUID(deps.session_id)
            except (ValueError, AttributeError):
                pass
            saved = await extractor.extract_and_save(
                user_message=user_message,
                agent_reply=answer,
                deps=deps,
                source_session_id=session_id,
            )
            if saved:
                logger.info(
                    "Memory extraction: saved %d facts for user=%s",
                    saved, deps.person.name if deps.person else "?",
                )
        except Exception:
            logger.debug("Background memory extraction failed", exc_info=True)

    asyncio.create_task(_bg_extract())


async def _retrieve_memories(
    user_id: str,
    query: str,
    db,
) -> list[str] | None:
    """检索与当前查询相关的用户记忆（供注入 Agent context）。

    S5：改走 ``core.memory.retrieve_with_decay``（衰减排序 + 命中后更新访问计数），
    渲染用 ``core.memory.inject_to_prompt``（带 memory_type + 时间）。失败静默降级。
    """
    try:
        from app.modules.safety.business_agent.core.memory import (
            inject_to_prompt,
            retrieve_with_decay,
        )

        results = await retrieve_with_decay(db, user_id, query, top_k=3)
        if results:
            return inject_to_prompt(results)
        return None
    except Exception:
        logger.debug("Memory retrieval failed, skipping", exc_info=True)
        return None
