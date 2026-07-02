"""FastMCP 服务实例与 ASGI 应用生成。

负责创建 FastMCP 实例并生成可挂载到 FastAPI 的 ASGI app。
工具函数在各业务模块的 mcp_tools.py 中通过 @mcp.tool() 注册。
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from starlette.middleware import Middleware

from app.platform.mcp.logging_middleware import MCPToolLoggingMiddleware

# 全局 FastMCP 实例
mcp = FastMCP("dazah-mcp")
mcp.add_middleware(MCPToolLoggingMiddleware())


def create_mcp_server() -> FastMCP:
    """返回全局 MCP 服务实例。"""
    return mcp


def get_mcp_app(path: str = "/mcp", middleware: list[Middleware] | None = None) -> Any:
    """生成可挂载到 FastAPI 的 ASGI 应用。

    Args:
        path: MCP Streamable HTTP 端点路径
        middleware: Starlette Middleware 列表

    Returns:
        Starlette ASGI app
    """
    if middleware:
        return mcp.http_app(path=path, middleware=middleware)
    return mcp.http_app(path=path)
