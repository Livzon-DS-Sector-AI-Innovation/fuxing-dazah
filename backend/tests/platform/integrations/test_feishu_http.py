"""飞书 HTTP 层：传输异常重试 + 连接池僵死自愈测试（不真连飞书）。"""

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.platform.integrations.feishu import http as feishu_http


def _mock_client(handler) -> httpx.AsyncClient:
    """构建 MockTransport 客户端（替换共享连接池）。"""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_transport_error_resets_pool_and_retries() -> None:
    """传输层异常（连接池僵死典型症状）：重建连接池后重试成功。"""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("connection pool stale", request=request)
        return httpx.Response(200, json={"code": 0, "data": {}})

    client = _mock_client(handler)
    with (
        patch.object(feishu_http, "_get_http_client", return_value=client),
        patch.object(
            feishu_http, "_reset_http_client",
            wraps=feishu_http._reset_http_client,
        ) as reset_mock,
        patch.object(feishu_http.asyncio, "sleep", new=AsyncMock()),
    ):
        data = await feishu_http.feishu_request(
            "GET", "https://open.feishu.cn/open-apis/test", attempts=3,
        )
    assert data == {"code": 0, "data": {}}
    assert calls["n"] == 2          # 第 1 次传输失败，第 2 次成功
    assert reset_mock.call_count == 1  # 传输异常触发连接池重建
    await client.aclose()


@pytest.mark.asyncio
async def test_reset_http_client_drops_cached_client() -> None:
    """_reset_http_client 丢弃当前事件循环的缓存客户端，下次请求重建。"""
    loop = asyncio.get_running_loop()
    stale = httpx.AsyncClient()
    feishu_http._client_cache[loop] = stale
    try:
        feishu_http._reset_http_client()
        assert loop not in feishu_http._client_cache
        fresh = feishu_http._get_http_client()
        assert fresh is not stale
        await fresh.aclose()
    finally:
        feishu_http._client_cache.pop(loop, None)
        if not stale.is_closed:
            await stale.aclose()


@pytest.mark.asyncio
async def test_exhausted_retries_raises_last_transport_error() -> None:
    """持续传输失败：按 attempts 次重试后抛 FeishuAPIError（链上保留原始异常）。"""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("still down", request=request)

    client = _mock_client(handler)
    with (
        patch.object(feishu_http, "_get_http_client", return_value=client),
        patch.object(feishu_http.asyncio, "sleep", new=AsyncMock()),
    ):
        with pytest.raises(feishu_http.FeishuAPIError, match="ConnectError") as ei:
            await feishu_http.feishu_request(
                "GET", "https://open.feishu.cn/open-apis/test",
                attempts=2, check_code=False,
            )
    assert calls["n"] == 2
    assert isinstance(ei.value.__cause__, httpx.ConnectError)
    await client.aclose()
