"""MCP 请求认证中间件。

负责：
1. 从 API-Key header 验证 Agent 身份
2. 为每个 MCP 请求创建/清理 DB session
3. 将 db session 写入 contextvars

使用纯 ASGI 中间件（非 BaseHTTPMiddleware），避免 Starlette BaseHTTPMiddleware
对 SSE 流式响应的已知缺陷（call_next 等待响应体结束，导致 db.commit() 不执行）。
"""

import logging

from starlette.middleware import Middleware
from starlette.responses import JSONResponse

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.platform.mcp.deps import reset_context, set_agent_api_key, set_context

logger = logging.getLogger(__name__)


class MCPAuthMiddleware:
    """纯 ASGI 中间件：MCP 认证与 DB 会话管理。

    只处理 /mcp 路径请求，验证 API Key 后创建数据库会话并写入 contextvars。
    请求结束后 commit（成功）或 rollback（失败），然后清理资源。

    与 BaseHTTPMiddleware 的区别：
    - 不使用 call_next，直接 await self.app(scope, receive, send)
    - 对 JSON 响应：app 返回后立即 commit（可靠）
    - 对 SSE 响应：app 在流关闭后才返回，commit 延后
      （tool 函数内的显式 commit 兜底 SSE 场景）
    """

    def __init__(self, app, valid_keys: set[str]):
        self.app = app
        self._valid_keys = valid_keys

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not path.startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        # 1. 验证 API Key
        headers = dict(scope.get("headers", []))
        api_key = (headers.get(b"api-key", b"")).decode()
        if not api_key or api_key not in self._valid_keys:
            logger.warning(
                "MCP 请求 API Key 无效: %s...",
                api_key[:8] if api_key else "<empty>",
            )
            response = JSONResponse(
                status_code=401,
                content={
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32001,
                        "message": "Agent API Key 无效或已过期",
                    },
                    "id": None,
                },
            )
            await response(scope, receive, send)
            return

        # 2. 记录 Agent 身份（供日志中间件使用）
        set_agent_api_key(api_key)

        # 3. 创建 DB session 并写入 contextvars
        db = async_session_factory()
        db_token, user_token = set_context(db, None)

        try:
            await self.app(scope, receive, send)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()
            reset_context(db_token, user_token)


def build_mcp_middleware() -> list:
    """构建 MCP 应用的中间件列表，供 FastMCP http_app 使用。"""
    settings = get_settings()
    raw = settings.MCP_AGENT_API_KEYS
    valid_keys: set[str] = (
        {k.strip() for k in raw.split(",") if k.strip()} if raw else set()
    )
    return [
        Middleware(MCPAuthMiddleware, valid_keys=valid_keys),
    ]
