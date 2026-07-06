"""MCP 请求认证中间件。

负责：
1. 从 API-Key header 验证 Agent 身份
2. 将 Agent API Key 写入 contextvars

DB session 的生命周期由 MCPToolLoggingMiddleware（FastMCP 层）管理，
按 tool 调用粒度创建/销毁，避免 SSE 流式响应期间长时间占用连接。
"""

import logging

from starlette.middleware import Middleware
from starlette.responses import JSONResponse

from app.core.config import get_settings
from app.platform.mcp.deps import set_agent_api_key

logger = logging.getLogger(__name__)


class MCPAuthMiddleware:
    """纯 ASGI 中间件：MCP 认证。

    只处理 /mcp 路径请求，验证 API Key。
    DB session 不再在此层管理（已移至 FastMCP MCPToolLoggingMiddleware）。
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

        # 3. 直接转发，不再创建 DB session
        await self.app(scope, receive, send)


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
