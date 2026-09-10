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


@business_agent_router.post("/agent/chat", response_model=ApiResponse, summary="业务 Agent 对话")
async def agent_chat(
    body: AgentChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """向业务 Agent 发送消息，返回文本或待确认的写操作方案。"""
    # 延迟导入：避免模块加载时初始化 pydantic-ai Agent（需要 API key 等）
    from app.modules.safety.business_agent.executor import run_turn
    from app.modules.safety.business_agent.session_store import (
        create_pending_action,
        get_or_create_session,
        save_message,
        update_session_history,
    )

    feishu_user_id = current_user.feishu_user_id if current_user else None
    deps = await _build_deps(db, session_id=body.session_id, feishu_user_id=feishu_user_id)

    # 获取或创建会话
    session = await get_or_create_session(
        db,
        channel="web",
        chat_id=deps.session_id,
        user_id=feishu_user_id,
        role=deps.role,
    )

    # 恢复消息历史
    history = session.message_history if isinstance(session.message_history, list) else None

    # 执行
    result = await run_turn(body.message, deps, message_history=history)

    # Web 匿名 + 办公室创建动作：追加友好降级提示（不动 executor 逻辑）
    pending = result.get("pending_action")
    if _web_office_grant_hint_needed(deps.person, pending):
        result["answer"] = _append_web_office_grant_hint(result["answer"])
        pending.summary = _append_web_office_grant_hint(pending.summary)

    # 持久化
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
        title=body.message[:80] if session.message_count == 0 else None,
    )
    await save_message(
        db,
        session_id=session.id,
        user_message=body.message,
        agent_answer=result["answer"],
        pending_action_id=uuid.UUID(pending_action_id) if pending_action_id else None,
    )

    return ApiResponse(data={
        "session_id": str(session.id),
        "answer": _strip_reference_section(result["answer"]),
        "pending_action_id": pending_action_id,
        "pending_action": result["pending_action"].model_dump() if result["pending_action"] else None,
        "sources": result.get("sources") or [],
    })


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
