"""2-E 暴露侧验收：/mcp/safety 只读端点（ASGI 级，配方抄仓储 test_live_mcp_endpoint）。

分层：真实 ``app``（main.py 挂载 /mcp/safety + 真实 MCPAuthMiddleware）验证
认证拒绝；同配方子应用 + 测试 key 完成 JSON-RPC 握手，验证 tools/list 恰好
5 个只读工具、tools/call 走本地库冒烟。lifespan 须与测试同 task 进出。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from starlette.middleware import Middleware

import app.modules.safety.mcp_tools  # noqa: F401 — 触发 @mcp.tool() 注册
from app.main import app
from app.platform.mcp.middleware import MCPAuthMiddleware
from app.platform.mcp.server import get_mcp_app, get_module_mcp

TEST_API_KEY = "safety-mcp-test-key-p2"
EXPECTED_TOOLS = {
    "query_hazards",
    "query_hazard_stats",
    "query_chemical_inventory",
    "query_special_op_records",
    "query_latest_regulations",
}
WRITE_TOOL_PREFIXES = ("submit", "create", "update", "delete", "send", "draft",
                       "generate", "poll", "run_", "confirm", "office")


def _headers(api_key: str | None = None, **extra: str) -> dict[str, str]:
    h = {"Accept": "application/json, text/event-stream"}
    if api_key:
        h["api-key"] = api_key
    h.update(extra)
    return h


def _parse_rpc(resp: httpx.Response) -> dict[str, Any]:
    if "text/event-stream" in resp.headers.get("content-type", ""):
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                payload = line[len("data:"):].strip()
                if payload:
                    msg = json.loads(payload)
                    if "result" in msg or "error" in msg:
                        return msg
        raise AssertionError(f"SSE 响应中无 JSON-RPC 消息: {resp.text[:300]!r}")
    return resp.json()


async def _rpc(
    ac: httpx.AsyncClient, headers: dict[str, str], method: str,
    params: dict[str, Any] | None = None, req_id: int | None = None,
) -> httpx.Response:
    body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        body["params"] = params
    if req_id is not None:
        body["id"] = req_id
    return await ac.post("/mcp", json=body, headers=headers, timeout=120.0)


async def _handshake(ac: httpx.AsyncClient) -> dict[str, str]:
    r = await _rpc(
        ac, _headers(TEST_API_KEY), "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "pytest-safety-mcp", "version": "0.0.0"},
        },
        req_id=1,
    )
    assert r.status_code == 200, r.text
    msg = _parse_rpc(r)
    assert "result" in msg, f"initialize 失败: {msg}"
    session_id = r.headers.get("mcp-session-id")
    assert session_id, f"initialize 未返回 mcp-session-id: {dict(r.headers)}"
    r = await _rpc(
        ac, _headers(TEST_API_KEY, **{"mcp-session-id": session_id}),
        "notifications/initialized",
    )
    assert r.status_code == 202
    return {
        "api-key": TEST_API_KEY,
        "mcp-session-id": session_id,
        "Accept": "application/json, text/event-stream",
    }


@asynccontextmanager
async def _mcp_session() -> AsyncIterator[tuple[httpx.AsyncClient, dict[str, str]]]:
    asgi = get_mcp_app(
        get_module_mcp("safety"),
        path="/mcp",
        middleware=[Middleware(MCPAuthMiddleware, valid_keys={TEST_API_KEY})],
    )
    async with asgi.lifespan(asgi):
        transport = httpx.ASGITransport(app=asgi)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            headers = await _handshake(ac)
            yield ac, headers


async def _list_tool_names(ac: httpx.AsyncClient, headers: dict[str, str]) -> set[str]:
    r = await _rpc(ac, headers, "tools/list", req_id=2)
    assert r.status_code == 200, r.text
    msg = _parse_rpc(r)
    assert "result" in msg, f"tools/list 失败: {msg}"
    return {t["name"] for t in msg["result"]["tools"]}


# ── 1. 认证：无 key / 错 key 拒绝 ────────────────────────────────


async def test_unauthorized_rejected() -> None:
    """真实挂载 app：无 api-key 与错 api-key 均 401。"""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/mcp/safety/",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers=_headers(),
        )
        assert r.status_code == 401, f"无 key 应 401，实际 {r.status_code}: {r.text[:200]}"
        assert r.json()["error"]["code"] == -32001

        r = await ac.post(
            "/mcp/safety/",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers=_headers(f"wrong-key-{uuid.uuid4().hex}"),
        )
        assert r.status_code == 401


# ── 2. tools/list：恰好 5 个只读工具 ─────────────────────────────


async def test_tools_listed_exactly_five() -> None:
    async with _mcp_session() as (ac, headers):
        names = await _list_tool_names(ac, headers)
        assert names == EXPECTED_TOOLS, f"工具清单偏差: {sorted(names)}"


# ── 3. 只读边界：无写入类工具（结构性排除）───────────────────────


async def test_write_tools_not_exposed() -> None:
    async with _mcp_session() as (ac, headers):
        names = await _list_tool_names(ac, headers)
        leaked = sorted(n for n in names if n.lower().startswith(WRITE_TOOL_PREFIXES))
        assert not leaked, f"只读端点暴露了写入类工具: {leaked}"
        assert names == EXPECTED_TOOLS


# ── 4. tools/call 冒烟：本地库查询成功返回结构化结果 ─────────────


async def test_query_chemical_inventory_via_mcp() -> None:
    """tools/call query_chemical_inventory（本地同步库）非错误返回。"""
    async with _mcp_session() as (ac, headers):
        r = await _rpc(
            ac, headers, "tools/call",
            {"name": "query_chemical_inventory", "arguments": {"limit": 5}},
            req_id=3,
        )
        assert r.status_code == 200, r.text
        msg = _parse_rpc(r)
        assert "result" in msg, f"tools/call 失败: {msg}"
        result = msg["result"]
        assert result.get("isError") is not True, f"工具报错: {result}"
        structured = result.get("structuredContent") or {}
        assert "total" in structured, f"structuredContent 应含 total: {structured}"
