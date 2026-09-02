"""MCP 日志中间件 DB 会话管理测试 — 错误结果回滚、正常结果提交。

背景：工具函数会捕获业务异常返回错误文案 ToolResult（对中间件是正常返回），
中间件曾无条件 commit，把失败操作中已入会话的写操作（如结束工序 403 前
add 的字段值行）提交落库。现在 is_error=True 的结果必须 rollback。
"""

from typing import Any

import mcp.types as mt
import pytest
from fastmcp.server.middleware.middleware import MiddlewareContext
from fastmcp.tools.base import ToolResult
from sqlalchemy.ext.asyncio import AsyncSession

import app.platform.mcp.logging_middleware as mw
from app.platform.mcp.logging_middleware import MCPToolLoggingMiddleware


def _make_context() -> MiddlewareContext[mt.CallToolRequestParams]:
    return MiddlewareContext(
        message=mt.CallToolRequestParams(name="dummy_tool", arguments={}),
    )


@pytest.fixture
def _spy_session(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, list[int]]:
    """中间件使用测试会话，并记录 commit/rollback 调用（close 屏蔽防关闭夹具会话）。"""
    calls: dict[str, list[int]] = {"commit": [], "rollback": []}
    orig_commit = db_session.commit
    orig_rollback = db_session.rollback

    def fake_factory() -> AsyncSession:
        # async_sessionmaker 同步调用返回会话，fake 需保持同签名
        return db_session

    async def spy_commit() -> None:
        calls["commit"].append(1)
        await orig_commit()

    async def spy_rollback() -> None:
        calls["rollback"].append(1)
        await orig_rollback()

    async def noop_close() -> None:
        pass

    monkeypatch.setattr(mw, "async_session_factory", fake_factory)
    monkeypatch.setattr(db_session, "commit", spy_commit)
    monkeypatch.setattr(db_session, "rollback", spy_rollback)
    monkeypatch.setattr(db_session, "close", noop_close)
    return calls


class TestMCPLoggingMiddlewareSession:
    async def test_error_result_rolls_back(
        self,
        db_session: AsyncSession,
        _spy_session: dict[str, list[int]],
    ) -> None:
        """is_error=True 的工具结果不提交，会话被回滚。"""

        async def call_next(_ctx: Any) -> ToolResult:
            return ToolResult(content="操作失败：xxx", is_error=True)

        result = await MCPToolLoggingMiddleware().on_call_tool(
            _make_context(), call_next
        )
        assert result.is_error is True
        assert _spy_session["commit"] == []
        assert len(_spy_session["rollback"]) >= 1

    async def test_success_result_commits(
        self,
        db_session: AsyncSession,
        _spy_session: dict[str, list[int]],
    ) -> None:
        """正常工具结果照常提交。"""

        async def call_next(_ctx: Any) -> ToolResult:
            return ToolResult(content="ok")

        result = await MCPToolLoggingMiddleware().on_call_tool(
            _make_context(), call_next
        )
        assert result.is_error is False
        assert len(_spy_session["commit"]) == 1

    async def test_raised_exception_triggers_rollback(
        self,
        db_session: AsyncSession,
        _spy_session: dict[str, list[int]],
    ) -> None:
        """工具直接抛异常（未捕获路径）同样回滚，异常向上传播。"""

        async def call_next(_ctx: Any) -> ToolResult:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await MCPToolLoggingMiddleware().on_call_tool(_make_context(), call_next)
        assert _spy_session["commit"] == []
