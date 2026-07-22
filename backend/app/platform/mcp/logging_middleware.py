"""MCP 工具调用日志 + DB 会话管理中间件。

FastMCP Middleware，在每次工具调用时：
1. 创建短生命周期 DB session（per-tool-call），解决 SSE 流式响应期间连接泄漏问题
2. 记录调用方 Agent 身份（API Key 前 8 位）、工具名称、入参、返回数据、耗时

通过 mcp.add_middleware() 注册，集成到项目统一日志体系。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import mcp.types as mt
from fastmcp.server.middleware.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult

from app.core.database import async_session_factory
from app.platform.mcp.deps import get_agent_api_key, reset_context, set_context

logger = logging.getLogger(__name__)

# 返回数据最大记录长度（字符），超出截断
_MAX_RESULT_LENGTH = 8000


def _serialize_result(result: Any) -> str:
    """将 ToolResult 序列化为 JSON 字符串。

    优先用 content（MCP 客户端实际收到的文本），
    同时保留 structured_content 作为补充。
    """
    if isinstance(result, ToolResult):
        parts: dict[str, Any] = {}
        # 内容块 → 提取 text 文本（客户端实际看到的数据）
        if result.content:
            texts: list[str] = []
            for c in result.content:
                try:
                    d = c.model_dump(mode="json")
                    if "text" in d:
                        texts.append(d["text"])
                    else:
                        texts.append(json.dumps(d, ensure_ascii=False, default=str))
                except Exception:
                    texts.append(str(c))
            if texts:
                parts["content"] = texts if len(texts) > 1 else texts[0]
        # 结构化数据作为补充
        if result.structured_content is not None:
            parts["structured"] = result.structured_content
        if result.is_error:
            parts["is_error"] = True
        return json.dumps(parts, ensure_ascii=False, default=str)
    try:
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception:
        return str(result)


def _summarize(s: str, max_len: int = _MAX_RESULT_LENGTH) -> str:
    """截断过长字符串，并附加原始长度提示。"""
    if len(s) <= max_len:
        return s
    return s[:max_len] + f"...<truncated, total {len(s)} chars>"


class MCPToolLoggingMiddleware(Middleware):
    """FastMCP 中间件：per-tool-call DB 会话管理 + 请求/响应日志。

    会话生命周期（解决 SSE 连接泄漏）：
    - 每次 tool 调用创建独立 DB session，写入 contextvars
    - tool 返回后立即 commit/rollback + close，连接秒级归还连接池
    - 即使 SSE 流长时间不关闭，连接也不会被占用

    日志格式（结构化 key=value）：
        event=mcp_tool_start|mcp_tool_success|mcp_tool_error
        tool=<工具名>
        agent=<API Key 前8位>
        args=<入参 JSON>
        result=<返回数据 JSON>      (仅 success)
        error=<错误信息>            (仅 error)
        duration_ms=<耗时>
    """

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool_name = context.message.name
        arguments = context.message.arguments or {}
        agent = get_agent_api_key()

        # 入参脱敏处理：屏蔽 password / token / secret 字段
        safe_args = {
            k: ("***" if any(s in k.lower() for s in ("password", "token", "secret")) else v)
            for k, v in arguments.items()
        }
        args_json = json.dumps(safe_args, ensure_ascii=False, default=str)

        logger.info(
            "event=mcp_tool_start tool=%s agent=%s args=%s",
            tool_name,
            agent,
            args_json,
        )

        # ── per-tool-call DB session ──
        # 每次 tool 调用创建独立会话，tool 执行完立即归还连接，
        # 避免 SSE 流式响应期间长时间占用导致连接泄漏。
        db = async_session_factory()
        db_token, user_token = set_context(db, None)

        start = time.perf_counter()
        try:
            result = await call_next(context)
            await db.commit()
            duration_ms = round((time.perf_counter() - start) * 1000, 2)

            result_str = _serialize_result(result)
            logger.info(
                "event=mcp_tool_success tool=%s agent=%s duration_ms=%s result=%s",
                tool_name,
                agent,
                duration_ms,
                _summarize(result_str),
            )
            return result
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.error(
                "event=mcp_tool_error tool=%s agent=%s duration_ms=%s error=%s",
                tool_name,
                agent,
                duration_ms,
                exc,
            )
            raise
        finally:
            try:
                await db.rollback()
                await db.close()
            except Exception:
                pass
            reset_context(db_token, user_token)
