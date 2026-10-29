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

import asyncio
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

from app.modules.safety.business_agent.agent import (
    get_agent_for_tools,
    resolve_runtime_config,
)
from app.modules.safety.business_agent.permissions import check as perm_check
from app.modules.safety.business_agent.rules import check_output
from app.modules.safety.business_agent.schemas import (
    PendingActionData,
    SafetyDeps,
)
from app.modules.safety.business_agent.tools.registry import TOOL_KIND

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# P0-2：轮次看门狗 = 单次 LLM 超时 + 30s（覆盖模型多轮工具循环的正常收尾）。
# 超时走 failed 审计 + 友好话术 → SSE 下发 error/终态，前端不再无限转圈。
_TURN_WATCHDOG_SLACK = 30

# P1-8：pending 守门话术 —— 历史仍有未回包写 ToolCall（确认卡未处理）时，
# 直接拦截新消息，不进模型（否则 pydantic-ai UserError 会话报废）。
_PENDING_GUARD_PROMPT = (
    "⚠️ 您有一项写操作正在等待确认（见上方确认卡片），"
    "请先点击【确认执行】或【取消】后再继续提问。"
)


# ═══════════════════════════════════════════════════════════════
# 公共接口
# ═══════════════════════════════════════════════════════════════


async def run_turn(
    user_message: str,
    deps: SafetyDeps,
    *,
    message_history: list[ModelMessage] | None = None,
) -> dict:
    """执行一个对话回合（2-F：轮内事件批量收口——seq 内存分配 + 尾部一次 flush）。

    入口层约定：run_turn 返回并持久化/commit 之后，调用
    ``schedule_memory_extraction(...)`` 做后台记忆提取（见其 docstring）；
    本函数不再轮内调度（与主流程并发使用轮内会话会互踩 flush）。
    """
    from app.modules.safety.business_agent.core import events as _events_mod

    _events_mod.start_turn_event_batch(deps.db, _session_uuid(deps))
    try:
        return await _run_turn_impl(
            user_message, deps, message_history=message_history,
        )
    finally:
        await _events_mod.end_turn_event_batch()


async def _run_turn_impl(
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
    #   2-A：绑定（model_profile）已经 per-turn resolve 即时生效（换 profile/
    #   调参零重启）；此处仅保留 enabled 熔断。
    from app.modules.safety.ai_config.scenario_store import scenario_store

    if not scenario_store.is_enabled("agent_chat"):
        logger.info("agent_chat 场景已停用，run_turn 直接返回停用文案")
        return {
            "answer": "AI 助手功能已停用，请联系管理员。",
            "messages": message_history or [],
            "pending_action": None,
            "sources": None,
        }

    # ── P1-8：pending 守门 ──
    #   历史尾部存在未回包的写 ToolCall（确认卡未处理）时，新用户消息会让
    #   pydantic-ai 抛 UserError("unprocessed tool calls") 报废整会话；
    #   此处提前拦截，不进模型，session 不落死。
    if await _has_unprocessed_write_call(message_history, deps):
        logger.warning(
            "run_turn: 检测到未处理的写工具挂起，拦截新消息 session=%s", deps.session_id,
        )
        return {
            "answer": _PENDING_GUARD_PROMPT,
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
        except Exception:
            logger.exception("run_turn: append user_message 事件失败（不影响主流程）")

    started = time.monotonic()
    trace_id: str | None = None

    # 1-D：路由决策（命中域/路径/置信度）——工具面选择与审计同源
    # P1-7 粘性路由：裸肯定/否定短词（确认/好的/取消…）对嵌入层是噪声
    # （两字分类漂移到无关域 = 裸「确认」脱轨根因），改用上一轮用户消息
    # 的路由口径，让上一轮提议的写工具仍在挂载面内。
    routing_extra: dict | None = None
    routed_tools: list[str] | None = None
    if user_message:
        from app.modules.safety.business_agent.tool_selector import route_message_async

        route_input = user_message
        sticky_used = False
        if _is_bare_confirmation(user_message):
            prev = _previous_user_message(message_history)
            if prev:
                route_input = prev
                sticky_used = True
                logger.info("粘性路由生效：%r → 沿用上轮口径 %r", user_message, prev[:40])
        decision = await route_message_async(route_input)
        routed_tools = decision.tool_names
        routing_extra = {
            "domains": list(decision.domains),
            "path": decision.path,
            "confidence": decision.confidence,
            "tool_count": len(decision.tool_names),
        }
        if sticky_used:
            routing_extra["sticky"] = True
    try:
        # 审计作用域：最外层开 safety.agent_chat 根 span（tracing 启用时），
        # 并让工具内嵌套的知识库 AI 调用继承 用户/会话/渠道/trace_id
        from app.modules.safety.ai_audit import ai_audit_scope

        _turn_timeout = float(resolve_runtime_config().timeout) + _TURN_WATCHDOG_SLACK
        with ai_audit_scope(
            scenario="agent_chat",
            session_id=deps.session_id or None,
            channel=deps.channel,
            user_name=deps.person.name if deps.person else None,
        ) as audit_ctx:
            trace_id = audit_ctx.trace_id
            result = await asyncio.wait_for(
                _agent_run(
                    user_message, deps,
                    message_history=message_history,
                    routed_tool_names=routed_tools,
                ),
                timeout=_turn_timeout,
            )
    except asyncio.TimeoutError:
        logger.error("agent run 超时（>%ss）session=%s", _turn_timeout, deps.session_id)
        err_msg = (
            f"抱歉，本次请求处理超时（{_turn_timeout:.0f} 秒）已自动中止，"
            "请稍后重试或换个问法；仍超时可输入 /new 重置会话。"
        )
        await _audit_agent_turn(
            deps, user_message,
            answer=None, result=None, pending=None, sources=None, guard_hits=None,
            status="failed",
            error=f"TimeoutError: turn exceeded {_turn_timeout:.0f}s",
            latency_ms=int((time.monotonic() - started) * 1000),
            trace_id=trace_id, routing=routing_extra,
        )
        return {
            "answer": err_msg,
            "messages": message_history or [],
            "pending_action": None,
            "sources": None,
        }
    except Exception as e:
        logger.exception("agent run 失败")
        err_msg = f"抱歉，处理您的请求时发生内部错误，请输入/new重置会话后再尝试提问：{type(e).__name__}: {e}"
        await _audit_agent_turn(
            deps, user_message,
            answer=None, result=None, pending=None, sources=None, guard_hits=None,
            status="failed", error=f"{type(e).__name__}: {e}",
            latency_ms=int((time.monotonic() - started) * 1000),
            trace_id=trace_id, routing=routing_extra,
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

    # → 记忆提取：不再轮内调度（见 schedule_memory_extraction docstring）——
    #    由入口层在事务 commit 后调用，后台任务用独立 session。

    # → 检查是否有待确认的写操作
    pending = _extract_pending_action(result)
    delegated = None
    if pending is None:
        # 2-D 委派挂起：delegate 元工具透传的子 Agent 写请求 → 同样走确认门
        delegated = _extract_delegated_deferral(result)
        pending = delegated
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
            trace_id=trace_id, routing=routing_extra,
        )
        messages_raw = _serialize_messages(result)
        if delegated is not None:
            # 合成子 Agent 写调用进消息尾部：resume 的 _find_deferred_in_history
            # 依据「无对应 ToolReturn 的写 ToolCallPart」找到它，从而完全复用
            # 既有确认 → resume → 权限再校验 → 执行 → 审计链路
            messages_raw = _append_delegated_tool_call(messages_raw, delegated)
        return {
            "answer": _pending_prompt(pending),
            "messages": messages_raw,
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
        trace_id=trace_id, routing=routing_extra,
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
    """恢复被挂起的写操作执行（2-F：轮内事件批量收口同 run_turn）。"""
    from app.modules.safety.business_agent.core import events as _events_mod

    _events_mod.start_turn_event_batch(deps.db, _session_uuid(session_id))
    try:
        return await _resume_impl(
            session_id, deps, action_id, approved, message_history_raw,
        )
    finally:
        await _events_mod.end_turn_event_batch()


async def _resume_impl(
    session_id: str,
    deps: SafetyDeps,
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

        _turn_timeout = float(resolve_runtime_config().timeout) + _TURN_WATCHDOG_SLACK
        with ai_audit_scope(
            scenario="agent_chat",
            session_id=session_id or None,
            channel=deps.channel,
            user_name=deps.person.name if deps.person else None,
        ) as audit_ctx:
            trace_id = audit_ctx.trace_id
            final = await asyncio.wait_for(
                _agent_run(
                    None,  # 无新用户消息，仅执行 approved tools
                    deps,
                    message_history=messages,
                    deferred_tool_results=results,
                    # 1-C：被确认的工具（可能属按需域）必须在本轮挂载面内
                    resume_tool_names=[c.tool_name for c in deferred_requests.approvals],
                ),
                timeout=_turn_timeout,
            )
    except asyncio.TimeoutError:
        # 写工具可能已执行（超时点常在模型收尾生成），话术须防重复发起
        logger.error("resume 超时（>%ss）action=%s", _turn_timeout, action_id)
        await _append_turn_end_event(
            deps, status="failed", error=f"resume timeout after {_turn_timeout:.0f}s",
        )
        await _audit_agent_resume(
            deps, session_id,
            action_id=action_id, approved=approved,
            tool_names=[c.tool_name for c in deferred_requests.approvals],
            answer="操作执行超时", result=None,
            trace_id=trace_id,
        )
        return {
            "answer": (
                "操作执行超时，执行结果未知——请勿立即重复发起，"
                "可先查询相关数据确认是否已执行，或联系管理员。"
            ),
            "messages": message_history_raw,
            "executed": False,
        }
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
#    压缩逻辑/摘要 AI 调用已迁至 ``core/compaction.maybe_compact``（token 驱动，超 12k
#    触发；1-B 起由 schedule/apply_cached_compaction 后台化，本轮不内联等待）。
#    旧符号 _summarize_history/_co)
#    常量保留兼容（外部若引用不 404，但不参与新触发逻辑）。
_MAX_HISTORY_MESSAGES = 20       # 最多保留 20 条消息（~10 轮对话，compaction 兼容参考）
_SUMMARY_TRIGGER_LENGTH = 20     # 旧条数触发阈值（已弃，token 驱动取代）
_SUMMARY_KEEP_RECENT = 10        # 保留最近 10 条原文不参与摘要（core/compaction 沿用同名常量）


def _registered_tool_names(tool_names: list[str] | None) -> list[str]:
    """本轮 Agent 实际会注册的工具名（口径与 get_agent_for_tools 一致）。

    None/空 = 常驻集（1-C：默认 Agent 只注册 RESIDENT_TOOLS，不再全量）；
    否则取子集，未知名字与 register_tools_subset 一样静默丢弃。tool_catalog 节
    必须用这份名单渲染，否则模型会被提示去调用一个不在工具表里的工具
    （"工具未挂载"根因）。
    """
    if not tool_names:
        from app.modules.safety.business_agent.tools.registry import RESIDENT_TOOLS

        return sorted(RESIDENT_TOOLS)
    return sorted({name for name in tool_names if name in TOOL_KIND})


def _resume_mount_tools(resume_tool_names: list[str]) -> list[str]:
    """resume 轮挂载面 = 常驻集 + 被确认工具（按需域工具如 URS 必须可达）。"""
    from app.modules.safety.business_agent.tools.registry import RESIDENT_TOOLS

    return sorted(
        set(RESIDENT_TOOLS) | {n for n in resume_tool_names if n in TOOL_KIND}
    )


async def _agent_run(
    user_message: str | None,
    deps: SafetyDeps,
    *,
    message_history: list[ModelMessage] | None = None,
    deferred_tool_results: DeferredToolResults | None = None,
    resume_tool_names: list[str] | None = None,
    routed_tool_names: list[str] | None = None,
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
    #    1-B 后台化：token 压力超 12k 时调度后台压缩（复用 maybe_compact 逻辑），
    #    本轮照常返回原始历史，下一轮经前缀替换应用压缩结果——消除内联摘要
    #    的偶发整轮 LLM 延迟尖刺。
    if message_history:
        from app.modules.safety.business_agent.core.compaction import (
            apply_cached_compaction,
            schedule_background_compaction,
        )

        message_history = apply_cached_compaction(message_history, deps)
        schedule_background_compaction(message_history, deps)

    # 按需选择工具子集（减少 tool definitions 开销 66%）
    # 必须在 prompt 组装之前算出来：tool_catalog 节要按「本轮真正挂载的工具」
    # 渲染，否则模型会被提示去调用一个不在工具表里的工具（"工具未挂载"根因）。
    # 1-D：路由决策由 run_turn 经 route_message 算好传入（决策同步写审计）。
    selected_tools: list[str] | None = None
    if resume_tool_names:
        # 1-C：resume（写确认恢复）轮必须包含被确认的按需工具（如 URS），
        # 挂「常驻集 + pending 工具」，不允许退回全量。
        selected_tools = _resume_mount_tools(resume_tool_names)
    else:
        selected_tools = routed_tool_names

    # S4：system-prompt 分节组装（persona/runtime_date/user_context/memories/tool_catalog）
    # 替代旧 MemoryInjector 的 build_user_context + inject_memory_context 前缀拼接。
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
            context={
                "memories": memories or [],
                "query": effective_message,
                # 与下面 get_agent_for_tools 用同一份名单，tool_catalog 只说真话
                "tool_names": _registered_tool_names(selected_tools),
            },
        )
        if prompt_prefix:
            effective_message = f"{prompt_prefix}\n---\n{effective_message}"

    agent = get_agent_for_tools(selected_tools)

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


def _extract_delegated_deferral(result) -> PendingActionData | None:
    """从 delegate 元工具的返回中提取子 Agent 透传的写请求（2-D 委派挂起）。

    只看最近一次 delegate 调用的返回：deferred=True → 组装 PendingActionData
    （工具名/参数原样透传）；deferred=False 或无 delegate 调用 → None。
    """
    from pydantic_ai.messages import ToolReturnPart

    from app.modules.safety.business_agent.tools.delegate import DELEGATED_KEY

    try:
        for msg in reversed(result.all_messages()):
            for part in getattr(msg, "parts", []):
                if isinstance(part, ToolReturnPart) and part.tool_name == "delegate":
                    content = part.content
                    if isinstance(content, str):
                        try:
                            content = json.loads(content)
                        except json.JSONDecodeError:
                            content = None
                    if isinstance(content, dict) and content.get(DELEGATED_KEY):
                        tool_name = str(content.get("tool_name") or "")
                        if not tool_name:
                            return None
                        args = content.get("arguments")
                        return PendingActionData(
                            tool_name=tool_name,
                            arguments=dict(args) if isinstance(args, dict) else {},
                            summary=str(content.get("summary") or tool_name),
                        )
                    return None  # 最近一次 delegate 调用未挂起
    except Exception:
        logger.debug("delegated deferral 提取失败", exc_info=True)
    return None


def _append_delegated_tool_call(
    raw_messages: list[dict], pending: PendingActionData
) -> list[dict]:
    """把委派挂起的写调用合成为消息尾部的 ToolCallPart（无对应 ToolReturn）。

    resume() 的 _find_deferred_in_history 据此重建 DeferredToolRequests，
    使委派挂起与 orchestrator 自身挂起共用同一确认/执行/审计链路。
    """
    from pydantic_ai.messages import ModelResponse, ToolCallPart

    part = ToolCallPart(
        tool_name=pending.tool_name,
        args=pending.arguments,
        tool_call_id=f"delegated-{uuid.uuid4().hex[:12]}",
    )
    synthetic = json.loads(ModelMessagesTypeAdapter.dump_json([ModelResponse(parts=[part])]))[0]
    raw_messages.append(synthetic)
    return raw_messages


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
    确认卡先给部门/月份/文件名，并说明执行范围。提炼四/五/六部走部门
    监护人台账，其余部门走平台作业票。
    """
    dept = args.get("dept_keyword", "")
    year = args.get("year", "")
    month = args.get("month", "")
    filename = args.get("filename") or ""

    from app.modules.safety.service.subsidy_dept_ledgers import match_ledger_source

    if match_ledger_source(str(dept)) is not None:
        title = "监护补贴统计（部门监护人台账）"
        scope = (
            "重拉部门监护人台账（Bitable）→ 按月份整理、级别以台账登记为准 → "
            "计算补贴 → 生成 Excel（主表 + 待核对/跳过说明页）→ 回传当前会话"
        )
    else:
        title = "监护补贴统计（平台作业票）"
        scope = (
            "从平台重拉作业票（±1 月窗口）→ 按部门/月份/证书匹配整理 → "
            "计算补贴 → 生成 Excel（主表 + 待核对/跳过说明页）→ 回传当前会话"
        )

    lines = [
        f"📊 **{title}**",
        "",
        f"• 部门关键词：{dept}",
        f"• 统计月份：{year}年{month}月",
        f"• 执行内容：{scope}",
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
            # P2-10：structured_content 失败/非 dict 时回退解析 part.content
            # JSON（A19 sources 空提取根因）；仍无 sources 打 debug 便于定位 RAG 侧
            data = None
            try:
                data = part.structured_content()
            except Exception:
                data = None
            if not isinstance(data, dict):
                try:
                    raw = part.content
                    if isinstance(raw, str):
                        raw = json.loads(raw)
                    if isinstance(raw, dict):
                        data = raw
                except Exception:
                    data = None
            if not isinstance(data, dict):
                continue
            srcs = data.get("sources") or []
            if not srcs:
                logger.debug(
                    "knowledge_search 返回无 sources（tool_call_id=%s）",
                    getattr(part, "tool_call_id", "?"),
                )
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


async def _has_unprocessed_write_call(
    message_history: list[ModelMessage] | None,
    deps: SafetyDeps,
) -> bool:
    """P1-8：会话历史尾部是否存在未回包的写 ToolCall（确认卡未处理）。

    历史来源与 ``_agent_run`` 同序：显式传入优先，None 时从事件表派生
    （web 首轮/飞书链路可能不传旧列）。只探测不消费，失败视为无挂起。
    """
    history = message_history
    if history is None and deps.db is not None and deps.session_id:
        history = await _derive_session_history(deps)
    if not history:
        return False
    try:
        if isinstance(history[0], dict):
            history = ModelMessagesTypeAdapter.validate_python(history)
        return _find_deferred_in_history(history) is not None
    except Exception:
        logger.debug("pending 守门历史探测失败（按无挂起处理）", exc_info=True)
        return False


# P1-7：裸肯定/否定白名单（从严：整条消息须恰为其中一个短词）
_BARE_CONFIRM_WORDS: frozenset[str] = frozenset({
    "确认", "确定", "好的", "好", "是", "是的", "嗯", "可以", "执行", "同意",
    "继续", "取消", "不用", "不用了", "否", "算了", "ok", "好嘞", "对的",
})


def _is_bare_confirmation(message: str | None) -> bool:
    """整条消息是否为裸肯定/否定短词（去标点后精确匹配白名单，≤6 字符）。"""
    text = (message or "").strip().strip("。，！!？?、 \t")
    return 0 < len(text) <= 6 and text.lower() in _BARE_CONFIRM_WORDS


def _previous_user_message(
    message_history: list[ModelMessage] | None,
) -> str | None:
    """P1-7：取上一条用户消息原文（粘性路由的输入）。

    剥掉 S4 prompt 前缀（``前缀\\n---\\n用户原文``，取最后一段）；纯内存
    扫描（web 断链修复后历史必传入；None/失败回退常规路由）。
    空合成 prompt（resume 轮会塞空 UserPromptPart）与裸确认词自身都跳过，
    继续向前找最近一条有内容的真实用户消息。
    """
    if not message_history:
        return None
    try:
        from pydantic_ai.messages import ModelRequest, UserPromptPart

        history = message_history
        if isinstance(history[0], dict):
            history = ModelMessagesTypeAdapter.validate_python(history)
        for msg in reversed(history):
            if not isinstance(msg, ModelRequest):
                continue
            for part in msg.parts:
                if not isinstance(part, UserPromptPart):
                    continue
                text = str(part.content).rsplit("\n---\n", 1)[-1].strip()
                if text and not _is_bare_confirmation(text):
                    return text
        return None
    except Exception:
        logger.debug("上一条用户消息提取失败（回退常规路由）", exc_info=True)
        return None


# ═══════════════════════════════════════════════════════════════
# 审计留痕（独立 session，失败仅告警，绝不阻塞对话）
# ═══════════════════════════════════════════════════════════════


def _model_name() -> str:
    """当前 Agent 使用的模型名（2-A：per-turn resolve，随配置即时变化）。"""
    return resolve_runtime_config().model


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
    routing: dict | None = None,
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
        if routing:
            # 1-D：路由决策（域/路径/置信度/挂载数）入审计，供持续调优
            extra["routing"] = routing
        # 2-A：生效配置入审计（核对换 profile/调参是否落地）
        _rt = resolve_runtime_config()
        extra["model_profile"] = {
            "profile": _rt.profile,
            "model": _rt.model,
            "fingerprint": _rt.fingerprint,
        }
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
    except Exception:
        logger.exception("append approval_requested 事件失败（不影响主流程）")


# ═══════════════════════════════════════════════════════════════
# 记忆提取调度（入口层 commit 后调用）
# ═══════════════════════════════════════════════════════════════

# 强引用防 GC（done 后自动移除）；与 core/compaction._BG_TASKS 同款
_MEMORY_TASKS: set = set()


def schedule_memory_extraction(
    *,
    session_id: str | None,
    user_message: str,
    agent_answer: str,
    deps: SafetyDeps,
):
    """调度后台记忆提取任务（fire-and-forget，不阻塞回复）。

    ⚠️ 必须在轮次事务 commit 之后调用（入口层负责）：
    - 对话文本直接由参数传入，不回读事件表——轮内事件未提交时回读会
      错配到上一轮的 assistant 消息；
    - ``memory_write`` 事件要在独立 session 里分配 seq，早于轮次提交
      会与轮内事件撞 ``(session_id, seq)`` 唯一索引。

    后台任务全程使用自开的 ``async_session_factory`` 会话，绝不触碰
    ``deps.db``（历史 bug：与主流程并发 autoflush/commit 同一轮内会话，
    触发 ``InvalidRequestError: Session is already flushing``，整轮
    对话历史随外层异常回滚丢失）。deps 仅供 person/role 提取上下文。

    Returns:
        创建的 Task；无需提取（缺文本/匿名/无事件循环）时 None。
    """
    import asyncio

    sid = _session_uuid(session_id)
    if sid is None or not user_message or not agent_answer:
        return None
    if not deps.person or not deps.person.user_id:
        return None

    async def _bg_extract():
        try:
            from app.core.database import async_session_factory
            from app.modules.safety.business_agent.core.memory import (
                extract_and_save_texts,
            )

            async with async_session_factory() as db:
                saved = await extract_and_save_texts(
                    db, session_id=sid,
                    user_message=user_message, agent_reply=agent_answer,
                    deps=deps,
                )
            if saved:
                logger.info(
                    "Memory extraction(texts): saved %d facts for user=%s",
                    saved, deps.person.name if deps.person else "?",
                )
        except Exception:
            logger.debug("Background memory extraction(texts) failed", exc_info=True)

    try:
        task = asyncio.create_task(_bg_extract())
    except RuntimeError:
        # 无运行中的事件循环（同步脚本上下文）：跳过
        return None
    _MEMORY_TASKS.add(task)
    task.add_done_callback(_MEMORY_TASKS.discard)
    return task


def _schedule_memory_extraction(
    user_message: str,
    result,
    deps: SafetyDeps,
) -> None:
    """调度后台记忆提取任务（fire-and-forget）。

    DEPRECATED：由入口层 post-commit 的 ``schedule_memory_extraction`` 取代
    （独立 session + 对话文本直传）。保留兼容，不删除。
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
