"""FastMCP 服务实例 — 按模块创建独立的 MCP 服务器。

每个业务模块通过 get_module_mcp() 获取自己的 FastMCP 实例，
工具函数通过 @mcp.tool() 装饰器注册到对应模块的服务器上。
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from starlette.middleware import Middleware

from app.platform.mcp.logging_middleware import MCPToolLoggingMiddleware

# 按模块名缓存的 FastMCP 实例
_module_mcps: dict[str, FastMCP] = {}


def get_module_mcp(module_name: str) -> FastMCP:
    """获取或创建指定模块的 FastMCP 实例。

    每个模块拥有独立的 FastMCP 服务器，自动注入日志中间件。
    同一 module_name 多次调用返回同一实例（幂等）。
    """
    if module_name not in _module_mcps:
        mcp = FastMCP(f"dazah-{module_name}")
        mcp.add_middleware(MCPToolLoggingMiddleware())
        _module_mcps[module_name] = mcp
    return _module_mcps[module_name]


def get_mcp_app(
    mcp: FastMCP,
    path: str = "/",
    middleware: list[Middleware] | None = None,
) -> Any:
    """生成可挂载到 FastAPI 的 ASGI 应用。

    Args:
        mcp: FastMCP 实例
        path: MCP Streamable HTTP 端点路径
        middleware: Starlette Middleware 列表

    Returns:
        Starlette ASGI app
    """
    return mcp.http_app(path=path, middleware=middleware)
