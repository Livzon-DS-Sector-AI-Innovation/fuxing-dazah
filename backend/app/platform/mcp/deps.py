"""MCP tool 函数使用的 contextvars 依赖注入。

FastMCP 没有 FastAPI 的 Depends() 机制，用 Python 标准库 contextvars
在协程链上安全传递请求级资源（DB session、当前用户）。
"""

import contextvars

from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.identity.models import User

_session_ctx: contextvars.ContextVar[AsyncSession | None] = contextvars.ContextVar(
    "mcp_db_session", default=None
)

_user_ctx: contextvars.ContextVar[User | None] = contextvars.ContextVar(
    "mcp_user", default=None
)

_agent_api_key_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "mcp_agent_api_key", default=""
)


def get_db() -> AsyncSession:
    """获取当前 MCP 请求的数据库会话。"""
    db = _session_ctx.get()
    if db is None:
        raise RuntimeError("DB session 未初始化，请通过 MCP 中间件访问 tool 函数")
    return db


def get_user() -> User | None:
    """获取当前 MCP 请求的认证用户。"""
    return _user_ctx.get()


def get_agent_api_key() -> str:
    """获取当前 MCP 请求的 Agent API Key（掩码后 8 位）。"""
    key = _agent_api_key_ctx.get()
    if not key:
        return ""
    return key[:8] + "..." if len(key) > 8 else key


def set_agent_api_key(api_key: str) -> None:
    """设置当前 MCP 请求的 Agent API Key。"""
    _agent_api_key_ctx.set(api_key)


def set_context(
    db: AsyncSession, user: User | None = None
) -> tuple[contextvars.Token[AsyncSession | None], contextvars.Token[User | None]]:
    """一次性设置 db 和 user，返回两个 reset token。"""
    db_token = _session_ctx.set(db)
    user_token = _user_ctx.set(user)
    return db_token, user_token


def reset_context(
    db_token: contextvars.Token[AsyncSession | None],
    user_token: contextvars.Token[User | None],
) -> None:
    """重置 db 和 user 的 contextvars。"""
    _session_ctx.reset(db_token)
    _user_ctx.reset(user_token)
