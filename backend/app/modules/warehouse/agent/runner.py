"""仓储 Agent Runner — tool-calling 循环（S1 ticket 03）。

替换票02 的桩实现，gateway↔Runner 接口契约不变：
- `run(session, text)` 的 session 为已定位会话（history 属性已加载；对象可能
  已脱离创建它的 AsyncSession，Runner 需要新事务时自开 session，勿复用调用方事务）；
- 正常返回 Reply（text 为 markdown 文本；data 携带最后一次成功工具的结构化
  结果，gateway 经 cards.render_reply_card 渲染专用/文本卡片，ticket 04）；
- 业务失败 / 内部错误直接抛异常，由 gateway 统一兜底降级话术。

循环契约（spec Implementation Decisions 5）：
- 组装 messages = 系统提示词 + 会话历史（SESSION_ROUNDS 轮裁剪）+ 本轮用户消息；
- 调 WarehouseLLMClient.chat_with_tools，工具调用经 tools/query 注册表执行，
  结果 JSON 序列化后截断 4KB/条、以 role=tool 回填；
- 终局判定 = 无 tool_calls 且 content 非空；≤ WAREHOUSE_AGENT_MAX_TURNS 轮，
  超限返回兜底话术（不抛异常）；
- 每次工具调用写 warehouse_agent_audit（自开事务，写失败不阻断主流程）；
- 本轮工具调用摘要追加进 session.history["tool_logs"]（内存追加 + 自开事务
  持久化；user/assistant 消息由 gateway 落库，见票02 契约——Runner 不重复写，
  内存追加使 gateway 尾部覆盖写库时自然带上 tool_logs）。

构造参数可注入（llm/max_turns/session_rounds/db 注入口），对齐 S0 测试风格。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent import repository
from app.modules.warehouse.agent.llm_client import (
    AssistantMessage,
    ToolCall,
    WarehouseLLMClient,
)
from app.modules.warehouse.agent.prompts import build_system_prompt
from app.modules.warehouse.agent.tools.query import (
    TOOLS,
    execute_tool,
    serialize_tool_result,
)
from app.modules.warehouse.models import WarehouseAgentSession

logger = logging.getLogger(__name__)

# 轮次耗尽的兜底话术（ticket 03：MAX_TURNS 超限返回兜底话术）
FALLBACK_REPLY = (
    "抱歉，这个问题连续多轮处理仍未得出结论，已记录。\n"
    "请换个问法试试，或把问题拆小一些（例如先问物料基本信息，再问库存/时间段）。"
)

# content 为空且无 tool_calls 时的推进消息（reasoning 契约：防空转耗尽轮次）
_NUDGE_MESSAGE = "请基于以上信息直接给出最终回答，不要再调用工具。"

# tool_logs 保留条数（每轮对话最多 1 条摘要，≈ SESSION_ROUNDS 轮）
TOOL_LOGS_MAX = 12

# args_summary 每参数值的截断长度 / 最多收录参数个数
_ARG_VALUE_MAX = 60
_ARG_MAX_ITEMS = 8


# ── 数据库会话注入口（与 gateway 同模式）──


@asynccontextmanager
async def _production_db() -> AsyncIterator[AsyncSession]:
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        yield session
        await session.commit()


_db_session: Callable[[], AbstractAsyncContextManager[AsyncSession]] = _production_db


@dataclass
class Reply:
    """Runner 终局回复。

    text: markdown 文本（gateway 落库/兜底文本卡片用）；
    data: 最后一次使用的工具名 + 原始结果 dict（{"tool": 名称, "result": 结果}，
          ticket 04 卡片渲染输入；无工具调用 / 工具均失败 / 兜底话术时为 None）。
    """

    text: str
    data: dict[str, Any] | None = None


class Runner:
    """tool-calling 循环 Runner：LLM + 4 个查询工具 + 会话/审计持久化。"""

    def __init__(
        self,
        *,
        llm: WarehouseLLMClient | None = None,
        max_turns: int | None = None,
        session_rounds: int | None = None,
    ) -> None:
        self._llm = llm
        if max_turns is None or session_rounds is None:
            from app.core.config import get_settings

            settings = get_settings()
            max_turns = (
                max_turns if max_turns is not None else int(settings.WAREHOUSE_AGENT_MAX_TURNS)
            )
            session_rounds = (
                session_rounds
                if session_rounds is not None
                else int(settings.WAREHOUSE_AGENT_SESSION_ROUNDS)
            )
        self._max_turns = max(1, int(max_turns))
        self._session_rounds = max(1, int(session_rounds))

    def _ensure_llm(self) -> WarehouseLLMClient:
        if self._llm is None:
            self._llm = WarehouseLLMClient()
        return self._llm

    async def _pending_summary(self, session: WarehouseAgentSession) -> str:
        """汇总该用户待处理的确认/提醒（spec 决策 5：pending 草稿摘要）。"""
        try:
            async with _db_session() as db:
                drafts = await repository.list_actionable_drafts(db, session.user_open_id)
        except Exception:
            logger.warning("待处理事项查询失败，跳过注入", exc_info=True)
            return ""
        lines: list[str] = []
        for d in drafts:
            if d.status == "pending_confirm":
                scene = d.scene or "confirm"
                lines.append(f"- 有一个待你确认的{scene}事项（草稿 {d.draft_no}），尚未执行")
            elif d.status == "scheduled":
                trigger = d.expires_at.strftime("%m-%d %H:%M") if d.expires_at else "待定"
                lines.append(f"- 有一个定时提醒（{trigger}）尚未触发（草稿 {d.draft_no}）")
        return "\n".join(lines)

    # ── 主循环 ──

    async def run(self, session: WarehouseAgentSession, text: str) -> Reply:
        llm = self._ensure_llm()
        history_messages = list((session.history or {}).get("messages") or [])
        trimmed = history_messages[-(self._session_rounds * 2):]
        system_text = await build_system_prompt(session.user_open_id)
        pending_note = await self._pending_summary(session)
        if pending_note:
            system_text += "\n\n## 六、当前待处理事项（用户可能追问进展）\n" + pending_note
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_text},
            *trimmed,
            {"role": "user", "content": text},
        ]

        tool_logs: list[dict[str, Any]] = []
        reply_data: dict[str, Any] | None = None
        final_text: str | None = None
        for _turn in range(self._max_turns):
            msg = await llm.chat_with_tools(messages, tools=TOOLS)
            messages.append(self._assistant_message(msg))

            if msg.tool_calls:
                for tc in msg.tool_calls:
                    executed = await self._run_tool(session, tc)
                    tool_logs.append(executed["log"])
                    if "error" not in executed["result"]:
                        # 记录最后一次成功的工具名+结果（卡片渲染输入，ticket 04）
                        reply_data = {"tool": tc.name, "result": executed["result"]}
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": executed["content"],
                    })
                continue  # 工具结果已回填，进入下一轮

            if (msg.content or "").strip():
                final_text = msg.content  # 终局：无 tool_calls 且 content 非空
                break
            messages.append({"role": "user", "content": _NUDGE_MESSAGE})

        if final_text is None:
            logger.warning(
                "仓库 Runner 达到最大轮次: session_id=%s turns=%s tools=%s",
                session.id, self._max_turns, [log["tool"] for log in tool_logs],
            )
            final_text = FALLBACK_REPLY
            reply_data = None  # 兜底话术不携带数据卡片

        await self._persist_tool_logs(session, tool_logs)
        return Reply(text=final_text, data=reply_data)

    # ── 消息组装 ──

    @staticmethod
    def _assistant_message(msg: AssistantMessage) -> dict[str, Any]:
        """assistant 消息回填（OpenAI 协议：tool_calls 需原始 arguments 串）。"""
        out: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            out["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": tc.arguments_raw
                        or json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in msg.tool_calls
            ]
        return out

    # ── 工具执行 + 审计 ──

    async def _run_tool(
        self, session: WarehouseAgentSession, tc: ToolCall
    ) -> dict[str, Any]:
        """执行单个工具调用：结果序列化 + audit（自开事务）。返回回填内容与摘要。

        session 传整对象（detached 但列属性已加载，读取安全）：plan 类工具
        经 ctx 拿会话定位（chat_id 发进度卡片、session_id 关联计划，ticket 05）。
        """
        started = time.monotonic()
        ctx = {
            "session_id": session.id,
            "chat_id": session.chat_id,
            "open_id": session.user_open_id,
        }
        result = await execute_tool(tc.name, tc.arguments, ctx=ctx)
        serialized = serialize_tool_result(result)
        duration_ms = int((time.monotonic() - started) * 1000)
        status = "error" if "error" in result else "ok"
        error_code = result.get("error_code")
        await self._write_audit(
            session.id,
            tool_name=tc.name,
            args_summary=self._args_summary(tc.arguments),
            result_status=status,
            error_code=str(error_code)[:30] if error_code else None,
            duration_ms=duration_ms,
        )
        return {
            "content": serialized,
            "result": result,
            "log": {
                "tool": tc.name,
                "args": tc.arguments,
                "status": status,
                "duration_ms": duration_ms,
            },
        }

    @staticmethod
    def _args_summary(arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            str(key)[:30]: str(value)[:_ARG_VALUE_MAX]
            for key, value in list(arguments.items())[:_ARG_MAX_ITEMS]
        }

    async def _write_audit(
        self,
        session_id: uuid.UUID | None,
        *,
        tool_name: str,
        args_summary: dict[str, Any],
        result_status: str,
        error_code: str | None = None,
        duration_ms: int = 0,
    ) -> None:
        """写 warehouse_agent_audit；失败只记日志（审计不阻断主流程）。"""
        try:
            async with _db_session() as db:
                await repository.insert_agent_audit(
                    db,
                    tool_name=tool_name,
                    args_summary=args_summary,
                    result_status=result_status,
                    error_code=error_code,
                    duration_ms=duration_ms,
                    session_id=session_id,
                )
        except Exception:
            logger.exception("仓库 Runner 审计写入失败: tool=%s", tool_name)

    # ── 会话 tool 摘要持久化 ──

    async def _persist_tool_logs(
        self, session: WarehouseAgentSession, tool_logs: list[dict[str, Any]]
    ) -> None:
        """本轮工具调用摘要追加进 history["tool_logs"]（裁剪保留最近 TOOL_LOGS_MAX 条）。

        - 内存追加到入参 session 对象：gateway 尾部以同一对象的 history 覆盖
          写库时自然携带（见 gateway._handle_text_message），不会丢失；
        - 同时自开事务 fresh-read 合并写库：Runner 被直接调用（不经 gateway）
          时也能持久化。不写 messages 键——user/assistant 由 gateway 落库。
        """
        if not tool_logs:
            return
        try:
            history = dict(session.history or {})
            logs = [dict(log) for log in history.get("tool_logs") or []]
            logs.extend(tool_logs)
            history["tool_logs"] = logs[-TOOL_LOGS_MAX:]
            session.history = history  # 内存同步（detached 对象，安全）
            async with _db_session() as db:
                await repository.update_session_history(db, session.id, history)
        except Exception:
            logger.exception("仓库 Runner 会话摘要写入失败: session_id=%s", session.id)


_runner: Runner | None = None


def get_runner() -> Runner:
    """Runner 工厂（模块级单例）。gateway 每次文本消息调用，gateway 不感知实现。"""
    global _runner
    if _runner is None:
        _runner = Runner()
    return _runner
