"""飞书 OpenAPI 通用 HTTP 层（平台集成能力）。

统一提供业务模块所需的飞书调用基础能力：
- tenant_access_token 按应用凭证缓存（约 100 分钟，飞书有效期 2 小时）
- 请求重试（传输异常 / 非 JSON 响应 / 429 / 5xx 统一重试一次）
- 业务码（code）校验，失败抛 FeishuAPIError
- AsyncClient 按事件循环复用（连接保活，避免每请求一次 TLS 握手）
- 二进制下载（图片等签名 URL 转存）

业务模块（如 hr/title_review）通过本模块的 adapter 调用飞书，
不直接散落 httpx HTTP 请求。
"""

import asyncio
import json
import logging
import time
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

TOKEN_BASE = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"

# token 缓存：f"{app_id}:{app_secret}" -> (token, 过期时间戳)
_token_cache: dict[str, tuple[str, float]] = {}
# AsyncClient 缓存：按事件循环复用连接池
_client_cache: dict[asyncio.AbstractEventLoop, httpx.AsyncClient] = {}


class FeishuAPIError(Exception):
    """飞书 OpenAPI 调用失败（网络层或业务码失败）。"""


def _get_http_client() -> httpx.AsyncClient:
    """按当前事件循环获取共享 AsyncClient（连接保活）。

    无运行中事件循环时（不应发生在服务内）回退为一次性客户端。
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return httpx.AsyncClient()
    client = _client_cache.get(loop)
    if client is None or client.is_closed:
        client = httpx.AsyncClient()
        _client_cache[loop] = client
    return client


async def get_tenant_token(
    app_id: str | None = None, app_secret: str | None = None
) -> str:
    """获取 tenant_access_token（按应用凭证缓存；缺省用全局 FEISHU_* 应用）。"""
    settings = get_settings()
    app_id = app_id or settings.FEISHU_APP_ID
    app_secret = app_secret or settings.FEISHU_APP_SECRET
    cache_key = f"{app_id}:{app_secret}"
    cached = _token_cache.get(cache_key)
    if cached and time.time() < cached[1]:
        return cached[0]
    data = await feishu_request(
        "POST",
        TOKEN_BASE,
        json_body={"app_id": app_id, "app_secret": app_secret},
        timeout=15,
        check_code=False,
    )
    token = data.get("tenant_access_token", "")
    if not token:
        raise FeishuAPIError("获取飞书token失败: " + json.dumps(data))
    _token_cache[cache_key] = (str(token), time.time() + 100 * 60)
    return str(token)


async def feishu_request(
    method: str,
    url: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    attempts: int = 2,
    timeout: float = 30,
    check_code: bool = True,
) -> dict[str, Any]:
    """带重试的飞书 JSON 请求：传输/解析/限流统一重试，业务码失败抛 FeishuAPIError。

    - 429/5xx：按传输失败重试
    - 非 JSON 响应体（网关 HTML 等）：解析异常同样重试
    - check_code=True 时校验返回体 code==0，否则抛 FeishuAPIError
    """
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            http = _get_http_client()
            resp = await http.request(
                method, url, json=json_body, params=params, headers=headers,
                timeout=timeout,
            )
            if resp.status_code == 429 or resp.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"HTTP {resp.status_code}", request=resp.request, response=resp
                )
            data: dict[str, Any] = resp.json()
        except Exception as exc:  # noqa: BLE001 — 传输/解析/限流统一重试
            last_exc = exc
            if attempt < attempts - 1:
                logger.warning("飞书请求失败重试: %s %s %s", method, url, type(exc).__name__)
                await asyncio.sleep(1)
            continue
        if check_code and data.get("code") != 0:
            raise FeishuAPIError(
                f"飞书 API 失败: {method} {url} code={data.get('code')} msg={data.get('msg')}"
            )
        return data
    raise FeishuAPIError(
        f"飞书请求网络异常: {method} {url} {type(last_exc).__name__}"
    ) from last_exc


async def download(url: str, *, timeout: float = 30) -> bytes:
    """下载二进制内容（图片等签名 URL 转存）。"""
    try:
        http = _get_http_client()
        resp = await http.get(url, follow_redirects=True, timeout=timeout)
        resp.raise_for_status()
        return resp.content
    except httpx.HTTPError as exc:
        raise FeishuAPIError(f"下载失败: {url} {type(exc).__name__}") from exc
