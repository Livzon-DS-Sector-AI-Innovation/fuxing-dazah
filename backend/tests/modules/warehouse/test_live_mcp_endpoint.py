"""S3 ticket 03 验收：/mcp/warehouse 只读端点（ASGI 级，live Base）。

分层策略（MCP_AGENT_API_KEYS 在 main.py 导入时冻结，env 未配置即全拒）：
- 认证拒绝层：真实 ``app``（main.py 实际挂载 /mcp/warehouse，真实
  MCPAuthMiddleware + MCP_AGENT_API_KEYS），无 key / 错 key → 401。
  无需 lifespan——认证在会话管理器之前短路（挂载根 307 尾斜杠重定向，
  直接请求 /mcp/warehouse/）。
- 协议与工具层：与 main.py 同配方（get_mcp_app + MCPAuthMiddleware）注入
  测试 key 构建子应用 ASGI，在测试协程内进出 lifespan（启动 streamable
  会话管理器；anyio cancel scope 要求同 task 进出，不能用 async generator
  fixture），httpx ASGITransport 完成 JSON-RPC 握手：
  initialize → notifications/initialized → tools/list → tools/call。
  tools/call query_stock 真查测试版 Base（与 warehouse live 测试同一数据源）。

注意：MCPAuthMiddleware 只拦 scope path 以 /mcp 开头的请求，独立（非挂载）
子应用须以 path="/mcp" 构建、请求打 /mcp 才会经过认证——与挂载场景下
Starlette Mount 保留完整 path 的行为一致。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from starlette.middleware import Middleware

import app.modules.warehouse.mcp_tools  # noqa: F401 — 触发 @mcp.tool() 注册
from app.main import app
from app.platform.mcp.middleware import MCPAuthMiddleware
from app.platform.mcp.server import get_mcp_app, get_module_mcp

TEST_API_KEY = "wh-mcp-test-key-ticket03"
EXPECTED_TOOLS = {"query_stock", "query_material", "query_movements", "query_report"}
WRITE_TOOL_PREFIXES = ("submit", "create", "update", "delete", "send", "draft")


# ── JSON-RPC over streamable HTTP 辅助 ──────────────────────────


def _headers(api_key: str | None = None, **extra: str) -> dict[str, str]:
    h = {"Accept": "application/json, text/event-stream"}
    if api_key:
        h["api-key"] = api_key
    h.update(extra)
    return h


def _parse_rpc(resp: httpx.Response) -> dict[str, Any]:
    """JSON 或 SSE（data: 行）响应 → JSON-RPC 消息（取首个 result/error）。"""
    if "text/event-stream" in resp.headers.get("content-type", ""):
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                payload = line[len("data:") :].strip()
                if payload:
                    msg = json.loads(payload)
                    if "result" in msg or "error" in msg:
                        return msg
        raise AssertionError(f"SSE 响应中无 JSON-RPC 消息: {resp.text[:300]!r}")
    return resp.json()


async def _rpc(
    ac: httpx.AsyncClient,
    headers: dict[str, str],
    method: str,
    params: dict[str, Any] | None = None,
    req_id: int | None = None,
) -> httpx.Response:
    body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        body["params"] = params
    if req_id is not None:
        body["id"] = req_id
    return await ac.post("/mcp", json=body, headers=headers, timeout=120.0)


async def _handshake(ac: httpx.AsyncClient) -> dict[str, str]:
    """initialize → notifications/initialized，返回后续请求所需 headers。"""
    r = await _rpc(
        ac,
        _headers(TEST_API_KEY),
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "pytest-warehouse-mcp", "version": "0.0.0"},
        },
        req_id=1,
    )
    assert r.status_code == 200, r.text
    msg = _parse_rpc(r)
    assert "result" in msg, f"initialize 失败: {msg}"
    version = msg["result"]["protocolVersion"]
    session_id = r.headers.get("mcp-session-id")
    assert session_id, f"initialize 未返回 mcp-session-id: {dict(r.headers)}"

    r = await _rpc(
        ac,
        _headers(TEST_API_KEY, **{"mcp-session-id": session_id}),
        "notifications/initialized",
    )
    assert r.status_code == 202, f"initialized 通知应 202，实际 {r.status_code}"
    return {
        "api-key": TEST_API_KEY,
        "mcp-session-id": session_id,
        "mcp-protocol-version": version,
        "Accept": "application/json, text/event-stream",
    }


async def _list_tool_names(ac: httpx.AsyncClient, headers: dict[str, str]) -> set[str]:
    r = await _rpc(ac, headers, "tools/list", req_id=2)
    assert r.status_code == 200, r.text
    msg = _parse_rpc(r)
    assert "result" in msg, f"tools/list 失败: {msg}"
    return {t["name"] for t in msg["result"]["tools"]}


# ── 会话作用域（lifespan 须与测试同 task 进出，见模块 docstring）──


@asynccontextmanager
async def _mcp_session() -> AsyncIterator[tuple[httpx.AsyncClient, dict[str, str]]]:
    """同配方子应用 + 完成握手：yield (client, 后续请求 headers)。"""
    asgi = get_mcp_app(
        get_module_mcp("warehouse"),
        path="/mcp",
        middleware=[Middleware(MCPAuthMiddleware, valid_keys={TEST_API_KEY})],
    )
    async with asgi.lifespan(asgi):
        transport = httpx.ASGITransport(app=asgi)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            headers = await _handshake(ac)
            yield ac, headers


# ── 1. 认证：无 key / 错 key 拒绝 ────────────────────────────────


async def test_unauthorized_rejected() -> None:
    """真实挂载 app：无 api-key 与错 api-key 均 401（认证在会话管理器前短路）。"""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        # 无 key（挂载根需尾斜杠直达 streamable 端点，否则 307 重定向）
        r = await ac.post(
            "/mcp/warehouse/",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers=_headers(),
        )
        assert r.status_code == 401, (
            f"无 key 应 401，实际 {r.status_code}: {r.text[:200]}"
        )
        body = r.json()
        assert body["error"]["code"] == -32001, body

        # 错 key（随机串，确保不在任何配置的 valid_keys 中）
        r = await ac.post(
            "/mcp/warehouse/",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers=_headers(f"wrong-key-{uuid.uuid4().hex}"),
        )
        assert r.status_code == 401, (
            f"错 key 应 401，实际 {r.status_code}: {r.text[:200]}"
        )


async def test_middleware_active_on_standalone_asgi() -> None:
    """同配方子应用（path=/mcp）：无 key 同样 401，证明中间件在协议链路生效。"""
    async with _mcp_session() as (ac, _headers_done):
        r = await _rpc(ac, _headers(), "tools/list", req_id=1)
        assert r.status_code == 401, (
            f"无 key 应 401，实际 {r.status_code}: {r.text[:200]}"
        )


# ── 2. tools/list：恰好 4 个只读工具 ─────────────────────────────


async def test_tools_listed() -> None:
    """有效 key 经 MCP 协议 tools/list：工具集合 == 预期 4 个（无多余）。"""
    async with _mcp_session() as (ac, headers):
        names = await _list_tool_names(ac, headers)
        assert names == EXPECTED_TOOLS, f"工具清单偏差: {sorted(names)}"


# ── 3. tools/call：query_stock 真查 live Base ────────────────────


async def test_query_stock_via_mcp() -> None:
    """tools/call query_stock(keyword=硫酸) 返回真实库存数据（live Base）。"""
    async with _mcp_session() as (ac, headers):
        r = await _rpc(
            ac,
            headers,
            "tools/call",
            {"name": "query_stock", "arguments": {"keyword": "硫酸"}},
            req_id=3,
        )
        assert r.status_code == 200, r.text
        msg = _parse_rpc(r)
        assert "result" in msg, f"tools/call 失败: {msg}"
        result = msg["result"]
        assert result.get("isError") is not True, f"工具报错: {result}"

        text = result["content"][0]["text"]
        assert "硫酸" in text, f"结果应含真实物料数据: {text[:200]!r}"
        assert "剩余数量" in text and "QA放行" in text, (
            f"应含库存明细列: {text[:200]!r}"
        )

        structured = result.get("structuredContent") or {}
        assert structured.get("total", 0) > 0, (
            f"live Base 应有硫酸库存: {structured.get('total')}"
        )
        assert structured.get("records"), "structuredContent 应含明细记录"


# ── 4. 只读边界：无写入工具 ──────────────────────────────────────


async def test_write_tools_not_exposed() -> None:
    """工具名不得含 submit/create/update/delete 等写入前缀（HITL 边界）。"""
    async with _mcp_session() as (ac, headers):
        names = await _list_tool_names(ac, headers)
        leaked = sorted(n for n in names if n.lower().startswith(WRITE_TOOL_PREFIXES))
        assert not leaked, f"只读端点暴露了写入类工具: {leaked}"
        # 双保险：清单与预期只读集合完全一致
        assert names == EXPECTED_TOOLS
