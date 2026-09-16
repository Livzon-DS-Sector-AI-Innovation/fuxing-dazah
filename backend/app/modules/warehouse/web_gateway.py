"""仓储 Agent Web 网关（分期B Ticket 05）：HTTP/SSE 通道。

与飞书入口（gateway.py，IM 事件驱动）共享 Runner、审计、场景熔断与会话：
- 会话按 web 维度隔离（chat_id="web"，user_open_id="web:{user_id}"）；
- SSE 事件流先行：accepted → stage → message（完整回复，前端打字机渲染）
  → finished/error，每事件带递增 seq；LLM token 级流式需重构 Runner，后续升级；
- 场景熔断（agent_chat 停用）返回 503；通道内异常以 error 事件下发。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent import repository as agent_repository
from app.modules.warehouse.agent.llm_client import WarehouseLLMError
from app.modules.warehouse.agent.runner import get_runner
from app.modules.warehouse.ai_audit.context import warehouse_audit_scope
from app.modules.warehouse.ai_config.exceptions import ScenarioDisabledError
from app.modules.warehouse.ai_config.scenario_store import scenario_store
from app.modules.warehouse.models import WarehouseAgentSession
from app.modules.warehouse.ops_config.runtime_store import runtime_store
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission

logger = logging.getLogger(__name__)

router = APIRouter()

WEB_CHAT_ID = "web"


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000, description="用户消息")


@asynccontextmanager
async def _db_session() -> AsyncIterator[AsyncSession]:
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        yield session
        await session.commit()


def _sse(event: str, data: dict[str, Any], seq: int) -> str:
    payload = {"seq": seq, **data}
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post(
    "/agent/chat/stream",
    summary="AI 助手对话（SSE 流式，与飞书侧共用 Runner）",
)
async def agent_chat_stream(
    payload: AgentChatRequest,
    user: User = Depends(require_permission("warehouse:stock:read")),
) -> Response:
    if not scenario_store.is_enabled("agent_chat"):
        return JSONResponse(
            status_code=503,
            content={"code": 503, "message": "仓库助手暂时不可用（已熔断），请稍后再试"},
        )

    user_id = str(user.id)
    open_id = f"web:{user_id}"
    started = time.monotonic()

    async def gen() -> AsyncIterator[str]:
        seq = 0
        trace_id = str(uuid.uuid4())
        session_id: uuid.UUID | None = None

        def emit(event: str, data: dict[str, Any]) -> str:
            nonlocal seq
            seq += 1
            return _sse(event, {"trace_id": trace_id, **data}, seq)

        try:
            yield emit("accepted", {"open_id": open_id})

            async with _db_session() as db:
                session: WarehouseAgentSession | None = (
                    await agent_repository.get_or_create_session(
                        db, chat_id=WEB_CHAT_ID, user_open_id=open_id
                    )
                )
            if session is None:  # 理论不可达（get_or_create_session 必返回）
                raise RuntimeError("Web 会话定位失败")
            session_id = session.id

            yield emit("stage", {"label": "正在处理"})

            with warehouse_audit_scope(
                "agent_chat",
                trace_id=trace_id,
                resource="chat",
                session_id=str(session_id) if session_id else None,
                chat_id=WEB_CHAT_ID,
                user_open_id=open_id,
                channel="web",
            ):
                reply = await get_runner().run(session, payload.message, scene_hint=None)

            yield emit("message", {"text": reply.text})

            # 会话历史追加 + 网关审计（对齐飞书侧 _handle_text_message 模式）
            duration_ms = int((time.monotonic() - started) * 1000)
            async with _db_session() as db:
                history = dict(session.history or {}) if session is not None else {}
                messages = list(history.get("messages") or [])
                messages.append({"role": "user", "content": payload.message})
                messages.append({"role": "assistant", "content": reply.text})
                history["messages"] = messages[-int(runtime_store.get_value("history_max_messages")) :]
                if session_id is not None:
                    await agent_repository.update_session_history(db, session_id, history)
                await agent_repository.insert_agent_audit(
                    db,
                    tool_name="web_gateway",
                    args_summary={"message": payload.message[:100]},
                    result_status="ok",
                    duration_ms=duration_ms,
                    session_id=session_id,
                )

            yield emit("finished", {"duration_ms": duration_ms})
        except ScenarioDisabledError:
            logger.warning("仓库助手 Web 通道场景熔断: user=%s", user_id)
            yield emit("error", {"message": "仓库助手暂时不可用（已熔断），请稍后再试"})
        except WarehouseLLMError as exc:
            logger.warning("仓库助手 Web 通道 LLM 故障: %s", exc)
            yield emit("error", {"message": "助手处理失败，请稍后再试"})
        except Exception:  # noqa: BLE001 — 通道内异常以 error 事件下发，不断流
            logger.exception("仓库助手 Web 通道处理失败")
            yield emit("error", {"message": "助手处理失败，请稍后再试"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
