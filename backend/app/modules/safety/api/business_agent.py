"""业务 Agent Web 入口。

POST /api/v1/safety/agent/chat         → 发送消息
POST /api/v1/safety/agent/actions/{id}/confirm → 确认/取消写操作
GET  /api/v1/safety/agent/sessions/{id} → 获取会话详情

依赖注入：``get_db`` → 数据库会话，``get_current_user`` → 从 JWT/session 取当前用户（``CurrentUser``）。

⚠️ 重要：所有涉及 business_agent 子模块（executor / agent / session_store / permissions）
的 import 全部延迟到函数内部，确保模块加载时 business_agent_router 的路由一定能注册，
不因 DeepSeek API key 缺失或 pydantic-ai 初始化失败而导致整个路由缺失（404）。
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.business_agent.schemas import (
    AgentChatRequest,
    PendingActionData,
    SafetyDeps,
)
from app.modules.safety.feishu.identity_resolver import IdentityResolver

logger = logging.getLogger(__name__)

business_agent_router = APIRouter()

# ── 参考法规区块剥离 ──

def _strip_reference_section(answer: str) -> str:
    """移除业务 Agent 可能在末尾追加的参考法规列表区块。

    检测模式：
    1. "参考法规" / "参考来源" / "📚" 标题块（向后兼容）
    2. 末尾连续的 "[N] ... 查看原文" 链接行（无标题的纯列表）
    """
    if not answer:
        return answer

    import re

    # ── 模式 1：含关键词标题 ──
    best_pos = len(answer)
    for keyword in ("参考法规", "关联制度文件", "法规依据", "参考来源"):
        pos = answer.rfind(keyword)
        if pos >= 0 and pos < best_pos:
            best_pos = pos
    if best_pos < len(answer):
        before = answer[:best_pos]
        for sep in ("\n---", "\n**", "\n📚", "\n- "):
            sep_pos = before.rfind(sep)
            if sep_pos > 0 and best_pos - sep_pos < 500:
                logger.info("Stripped reference section (%d → %d chars)", len(answer), sep_pos)
                return answer[:sep_pos].rstrip()
        if best_pos > len(answer) * 0.6:
            logger.info("Stripped reference section (%d → %d chars)", len(answer), best_pos)
            return answer[:best_pos].rstrip()

    # ── 模式 2：末尾连续的编号引用行 ──
    _ref_line_re = re.compile(
        r"^(\[(\d+)\]\s+.+查看原文"
        r"|《[^》]+》\[(\d+)\].*"
        r"|\[(\d+)\]\s+《[^》]+》"
        r")"
    )
    lines = answer.split("\n")
    ref_start = None
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if not stripped:
            continue
        if _ref_line_re.match(stripped):
            ref_start = i
        else:
            break

    if ref_start is not None:
        ref_count = sum(
            1 for j in range(ref_start, len(lines))
            if _ref_line_re.match(lines[j].strip())
        )
        if ref_count >= 2:
            cut = ref_start
            while cut > 0 and (
                not lines[cut - 1].strip()
                or lines[cut - 1].strip().startswith("---")
                or lines[cut - 1].strip().startswith("**")
            ):
                cut -= 1
            logger.info(
                "Stripped %d reference lines (%d → %d chars)",
                ref_count, len(answer), len("\n".join(lines[:cut]).rstrip()),
            )
            return "\n".join(lines[:cut]).rstrip()

    return answer


async def _build_deps(
    db: AsyncSession,
    *,
    session_id: str | None = None,
    feishu_user_id: str | None = None,
) -> SafetyDeps:
    """为每次请求构建 SafetyDeps 依赖。"""
    sid = session_id or str(uuid.uuid4())

    # 身份
    person = None
    role = None
    if feishu_user_id:
        resolver = IdentityResolver(db)
        person = await resolver.resolve_by_user_id(feishu_user_id)
        if person:
            from app.modules.safety.business_agent.session_store import get_user_role
            role = await get_user_role(db, feishu_user_id)

    return SafetyDeps(db=db, person=person, role=role, session_id=sid, channel="web")


# ── Web 匿名 → 办公室创建动作降级提示 ──────────────────────────

_WEB_OFFICE_GRANT_HINT = (
    "Web 端暂无法把文件管理权限授予发起人，创建后请手动在飞书共享"
)

# 这些工具在飞书端会在创建/上传成功后自动授予发起人管理权限；
# Web 端 deps.person=None 无法完成授权，需要在响应里友好提示。
_OFFICE_CREATE_TOOL_NAMES: frozenset[str] = frozenset({
    "office_create_docx",
    "office_create_sheet",
    "office_create_base",
    "office_create_slides",
    "office_upload_file",
})


def _web_office_grant_hint_needed(
    person: object | None,
    pending_action: PendingActionData | None = None,
    *,
    tool_name: str | None = None,
) -> bool:
    """判断当前 Web 匿名响应是否需要对办公室创建动作追加降级提示。"""
    if person is not None:
        return False
    name = tool_name or (pending_action.tool_name if pending_action else None)
    return name in _OFFICE_CREATE_TOOL_NAMES


def _append_web_office_grant_hint(answer: str) -> str:
    """把 Web 匿名办公室创建的友好降级提示拼接到 answer 末尾。"""
    if answer:
        return f"{answer.rstrip()}\n\n💡 {_WEB_OFFICE_GRANT_HINT}"
    return f"💡 {_WEB_OFFICE_GRANT_HINT}"


# ═══════════════════════════════════════════════════════════════
# 端点（所有重量级 import 延迟到函数内部）
# ═══════════════════════════════════════════════════════════════


async def _execute_turn_and_persist(
    db: AsyncSession,
    *,
    message: str,
    session_id: str | None,
    feishu_user_id: str | None,
):
    """Web 渠道执行一轮对话并持久化（/agent/chat 与 /agent/chat/stream 共用）。

    流水：建会话 → 恢复历史 → run_turn → 办公降级提示 → pending 落库 →
    历史/消息持久化 → commit → 调度记忆提取。返回 (result, session, pending_action_id)。

    轮次串行化（turn_gate）：同 session_id 的并发轮次互斥，防事件流 seq
    撞唯一索引 / message_history 相互覆写；尾部显式 commit 后才调度记忆
    提取（后台任务用独立 session，见 executor.schedule_memory_extraction）。
    """
    from app.modules.safety.business_agent.executor import (
        run_turn,
        schedule_memory_extraction,
    )
    from app.modules.safety.business_agent.session_store import (
        create_pending_action,
        get_or_create_session,
        save_message,
        update_session_history,
    )
    from app.modules.safety.business_agent.turn_gate import turn_gate

    deps = await _build_deps(db, session_id=session_id, feishu_user_id=feishu_user_id)
    async with turn_gate(f"web:{deps.session_id}"):
        session = await get_or_create_session(
            db,
            channel="web",
            chat_id=deps.session_id,
            user_id=feishu_user_id,
            role=deps.role,
        )
        # web 断链修复（验收 #8）：事件流/记忆提取按真实会话行 id 归位——
        # 首轮 deps.session_id 是随机串，行 id 是服务端生成的另一 UUID，
        # 不对齐则首轮事件全部孤儿化、派生历史永远为空。
        # （直接赋值而非 replace：测试替身可能不是 dataclass）
        if deps.session_id != str(session.id):
            deps.session_id = str(session.id)
        history = session.message_history if isinstance(session.message_history, list) else None
        result = await run_turn(message, deps, message_history=history)

        # Web 匿名 + 办公室创建动作：追加友好降级提示（不动 executor 逻辑）
        pending = result.get("pending_action")
        if _web_office_grant_hint_needed(deps.person, pending):
            result["answer"] = _append_web_office_grant_hint(result["answer"])
            pending.summary = _append_web_office_grant_hint(pending.summary)

        pending_action_id = None
        if pending:
            pa_record = await create_pending_action(
                db,
                session_id=session.id,
                pending=pending,
                message_history_snapshot=result["messages"],
            )
            pending_action_id = str(pa_record.id)

        await update_session_history(
            db, session, messages=result["messages"],
            title=message[:80] if session.message_count == 0 else None,
        )
        await save_message(
            db,
            session_id=session.id,
            user_message=message,
            agent_answer=result["answer"],
            pending_action_id=uuid.UUID(pending_action_id) if pending_action_id else None,
        )
        await db.commit()

        # ── 记忆提取：commit 后调度，后台任务用独立 session ──
        schedule_memory_extraction(
            session_id=str(session.id), user_message=message,
            agent_answer=result["answer"], deps=deps,
        )
    return result, session, pending_action_id


@business_agent_router.post("/agent/chat", response_model=ApiResponse, summary="业务 Agent 对话")
async def agent_chat(
    body: AgentChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """向业务 Agent 发送消息，返回文本或待确认的写操作方案。"""
    result, session, pending_action_id = await _execute_turn_and_persist(
        db,
        message=body.message,
        session_id=body.session_id,
        feishu_user_id=current_user.feishu_user_id if current_user else None,
    )
    return ApiResponse(data={
        "session_id": str(session.id),
        "answer": _strip_reference_section(result["answer"]),
        "pending_action_id": pending_action_id,
        "pending_action": result["pending_action"].model_dump() if result["pending_action"] else None,
        "sources": result.get("sources") or [],
    })


@business_agent_router.post(
    "/agent/chat/stream",
    summary="业务 Agent 对话（SSE 事件流）",
)
async def agent_chat_stream(
    body: AgentChatRequest,
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """流式版对话：accepted → stage(处理中) → message(完整回复) → finished。

    挂起轮在 message 前下发 pending 事件（确认卡片交互不变，confirm 走旧端点）；
    异常以 error 事件收尾不断流；场景熔断直接 503。事件流为「阶段反馈」
    （对齐仓储 web_gateway 模式），message 一次性携带完整回复——非 token 级。
    DB 会话流内自开（请求结束即 commit 的 get_db 不适用于长流），尾部一次 commit。
    """
    import json as _json
    import time as _time

    from fastapi.responses import StreamingResponse

    from app.modules.safety.ai_config.scenario_store import scenario_store

    if not scenario_store.is_enabled("agent_chat"):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=503,
            content={"code": 503, "message": "AI 助手功能已停用", "data": None},
        )

    feishu_user_id = current_user.feishu_user_id if current_user else None
    started = _time.monotonic()

    def _sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {_json.dumps(data, ensure_ascii=False)}\n\n"

    async def gen():
        seq = 0

        def _next(**fields) -> dict:
            nonlocal seq
            seq += 1
            return {"seq": seq, **fields}

        yield _sse("accepted", _next(message=body.message[:80]))
        try:
            from app.core.database import async_session_factory

            async with async_session_factory() as db:
                yield _sse("stage", _next(label="正在处理"))

                result, session, pending_action_id = await _execute_turn_and_persist(
                    db,
                    message=body.message,
                    session_id=body.session_id,
                    feishu_user_id=feishu_user_id,
                )
                pending = result.get("pending_action")
                await db.commit()

                if pending:
                    yield _sse("pending", _next(
                        pending_action_id=pending_action_id,
                        pending_action=pending.model_dump(),
                    ))
                yield _sse("message", _next(
                    session_id=str(session.id),
                    answer=_strip_reference_section(result["answer"]),
                    sources=result.get("sources") or [],
                ))
        except Exception as exc:  # noqa: BLE001 — SSE 流内异常转 error 事件，不断流
            logger.exception("agent_chat_stream 执行失败")
            yield _sse("error", _next(error=f"{type(exc).__name__}: {exc}"))
            return
        yield _sse("finished", _next(
            duration_ms=int((_time.monotonic() - started) * 1000),
        ))

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@business_agent_router.post(
    "/agent/actions/{action_id}/confirm", response_model=ApiResponse,
    summary="确认/取消挂起的写操作",
)
async def confirm_action(
    action_id: str,
    approved: bool = Query(..., description="True=确认执行, False=取消"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """用户对 Agent 提议的写操作方案做出决定。"""
    from app.modules.safety.business_agent.executor import resume
    from app.modules.safety.business_agent.session_store import (
        get_pending_action,
        get_session,
        resolve_pending_action,
        save_message,
        update_session_history,
    )

    pa = await get_pending_action(db, action_id)
    if pa is None:
        raise HTTPException(status_code=404, detail=f"待确认操作 {action_id} 不存在")
    if pa.status != "pending":
        raise HTTPException(status_code=400, detail=f"该操作已处理（状态: {pa.status}）")

    session = await get_session(db, str(pa.session_id))
    if session is None:
        raise HTTPException(status_code=404, detail="关联会话不存在")

    feishu_user_id = current_user.feishu_user_id if current_user else None
    deps = await _build_deps(
        db,
        session_id=str(session.id),
        feishu_user_id=feishu_user_id,
    )

    from app.modules.safety.business_agent.turn_gate import turn_gate

    async with turn_gate(f"web:{str(session.id)}"):
        # 执行
        result = await resume(
            str(session.id),
            deps,
            action_id=action_id,
            approved=approved,
            message_history_raw=(
                pa.message_history_snapshot
                if isinstance(pa.message_history_snapshot, list) else []
            ),
        )

        # Web 匿名 + 办公室创建动作：确认执行后追加友好降级提示
        if approved and _web_office_grant_hint_needed(
            deps.person, tool_name=pa.tool_name,
        ):
            result["answer"] = _append_web_office_grant_hint(result["answer"])

        # 持久化
        await resolve_pending_action(
            db, pa, approved=approved, approved_by=feishu_user_id,
            result_data=result.get("messages") if result["executed"] else None,
        )
        await update_session_history(db, session, messages=result["messages"])
        await save_message(
            db,
            session_id=session.id,
            user_message=f"[确认操作: {action_id}]",
            agent_answer=result["answer"],
        )
        await db.commit()

    return ApiResponse(data={
        "session_id": str(session.id),
        "answer": _strip_reference_section(result["answer"]),
        "executed": result["executed"],
    })


@business_agent_router.get(
    "/agent/sessions/{session_id}", response_model=ApiResponse,
    summary="获取业务 Agent 会话详情",
)
async def get_agent_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取指定会话的元信息（不含消息历史全文）。"""
    from app.modules.safety.business_agent.session_store import get_session

    session = await get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    return ApiResponse(data={
        "id": str(session.id),
        "channel": session.channel,
        "title": session.title,
        "message_count": session.message_count,
        "role": session.role,
        "last_active_at": session.last_active_at.isoformat() if session.last_active_at else None,
    })
