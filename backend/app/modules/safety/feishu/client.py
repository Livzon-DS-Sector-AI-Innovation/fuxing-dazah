"""安全模块专属飞书客户端。

使用独立凭证 SAFETY_FEISHU_APP_ID / SAFETY_FEISHU_APP_SECRET，
与全局飞书集成完全隔离。
"""

import asyncio
import json as _json
import logging
import os
import time
from typing import Any

import lark_oapi as lark

from app.modules.safety.env_loader import load_safety_env

logger = logging.getLogger(__name__)

# 加载 .env.{APP_ENV}（全模块统一入口，幂等；详见 env_loader.py）
load_safety_env()

# 安全模块独立的应用凭证（从环境变量读取，不经过全局 config）
SAFETY_FEISHU_APP_ID = os.getenv("SAFETY_FEISHU_APP_ID", "")
SAFETY_FEISHU_APP_SECRET = os.getenv("SAFETY_FEISHU_APP_SECRET", "")

# ── tenant_access_token 进程内缓存（A6② 效率止血）──────────────────────────
# 飞书内联 tenant token 默认有效期 7200s；缓存到期前提前刷新，避免临界失效。
# margin = min(300s, expire 的 10%)：短 token 按 10% 提前、长 token 封顶 300s。
_DEFAULT_TOKEN_EXPIRE_SECONDS = 7200.0
_TOKEN_REFRESH_MARGIN_MAX_SECONDS = 300.0
_TOKEN_REFRESH_MARGIN_RATIO = 0.1

# 进程内缓存：(token, 提前刷新时间点，monotonic 秒)
_token_cache: tuple[str, float] | None = None
# 单飞锁：按当前事件循环惰性创建——asyncio.Lock 首次使用后绑定 loop，
# 不能跨 loop 复用（pytest 每个用例新 loop），故换 loop 重建而不是全局单锁。
_token_lock: asyncio.Lock | None = None
_token_lock_loop: asyncio.AbstractEventLoop | None = None


async def get_safety_feishu_client() -> lark.Client:
    """获取安全模块专属的飞书客户端。"""
    if not SAFETY_FEISHU_APP_ID or not SAFETY_FEISHU_APP_SECRET:
        raise RuntimeError(
            "安全模块飞书配置缺失：请设置 SAFETY_FEISHU_APP_ID 和 SAFETY_FEISHU_APP_SECRET 环境变量"
        )
    return (
        lark.Client.builder()
        .app_id(SAFETY_FEISHU_APP_ID)
        .app_secret(SAFETY_FEISHU_APP_SECRET)
        .domain(lark.FEISHU_DOMAIN)
        .app_type(lark.AppType.SELF)
        .build()
    )


def _now() -> float:
    """单调时钟接缝（缓存提前刷新判定）；测试可 monkeypatch 推进假时钟。"""
    return time.monotonic()


def _refresh_at(expire_seconds: float) -> float:
    """计算提前刷新时间点（monotonic）：expire - min(300s, expire 的 10%)。"""
    margin = min(
        _TOKEN_REFRESH_MARGIN_MAX_SECONDS,
        expire_seconds * _TOKEN_REFRESH_MARGIN_RATIO,
    )
    return _now() + max(expire_seconds - margin, 0.0)


def _parse_expire_seconds(raw: Any) -> float:
    """解析响应 ``expire``（秒）；缺失/非法/非正数回退默认 7200s。"""
    try:
        expire = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_TOKEN_EXPIRE_SECONDS
    return expire if expire > 0 else _DEFAULT_TOKEN_EXPIRE_SECONDS


def _cached_token() -> str | None:
    """缓存命中（未到提前刷新点）返回 token，否则返回 None。"""
    cached = _token_cache
    if cached is not None and _now() < cached[1]:
        return cached[0]
    return None


def _store_token(token: str, expire_seconds: float) -> None:
    global _token_cache
    _token_cache = (token, _refresh_at(expire_seconds))


def _get_token_lock() -> asyncio.Lock:
    """取当前事件循环专属的单飞锁（换 loop 重建，避免跨 loop 绑定报错）。"""
    global _token_lock, _token_lock_loop
    loop = asyncio.get_running_loop()
    if _token_lock is None or _token_lock_loop is not loop:
        _token_lock = asyncio.Lock()
        _token_lock_loop = loop
    return _token_lock


def invalidate_safety_tenant_token() -> None:
    """清空进程内 tenant_access_token 缓存（token 失效 / 需强制重取时调用）。"""
    global _token_cache
    _token_cache = None
    logger.debug("安全模块飞书 tenant token 缓存已清空")


async def _fetch_safety_tenant_token(
    client: lark.Client | None = None,
) -> tuple[str, float]:
    """请求飞书 tenant_access_token（唯一外部边界），失败抛 RuntimeError。"""
    from lark_oapi.api.auth.v3 import (
        InternalTenantAccessTokenRequest,
        InternalTenantAccessTokenRequestBody,
    )

    if client is None:
        client = await get_safety_feishu_client()

    req = (
        InternalTenantAccessTokenRequest.builder()
        .request_body(
            InternalTenantAccessTokenRequestBody.builder()
            .app_id(SAFETY_FEISHU_APP_ID)
            .app_secret(SAFETY_FEISHU_APP_SECRET)
            .build()
        )
        .build()
    )
    resp = await client.auth.v3.tenant_access_token.ainternal(req)
    if not resp.success():
        raise RuntimeError(
            f"获取安全模块飞书 tenant token 失败: code={resp.code}, msg={resp.msg}"
        )
    if resp.raw and resp.raw.content:
        data = _json.loads(resp.raw.content.decode("utf-8"))
        token = str(data.get("tenant_access_token") or "")
        expire_seconds = _parse_expire_seconds(data.get("expire"))
        logger.debug("安全模块飞书 tenant token 获取成功: expire=%ss", expire_seconds)
        return token, expire_seconds
    raise RuntimeError("安全模块飞书 tenant token 响应为空")


async def get_safety_tenant_token(client: lark.Client | None = None) -> str:
    """获取安全模块飞书应用的 tenant_access_token（进程内缓存 + 单飞）。

    缓存按响应 ``expire`` 提前刷新（margin = min(300s, expire 的 10%)，
    拿不到 expire 默认 7200s）；``invalidate_safety_tenant_token()`` 可强制
    下次重取。并发穿透由单飞锁挡住：同一时刻最多一次底层 token 请求。

    获取失败仍抛 RuntimeError，失败结果不缓存（下次调用会重新尝试）。
    """
    cached = _cached_token()
    if cached is not None:
        return cached

    async with _get_token_lock():
        cached = _cached_token()
        if cached is not None:
            return cached
        token, expire_seconds = await _fetch_safety_tenant_token(client)
        if token:
            _store_token(token, expire_seconds)
        else:
            logger.warning("安全模块飞书 tenant token 响应缺少 token，暂不缓存")
        return token


async def download_message_image(
    message_id: str,
    file_key: str,
    client: lark.Client | None = None,
) -> bytes:
    """下载飞书消息中的图片（GET /im/v1/messages/:message_id/resources/:file_key）。

    供安全助手识图链路使用：把对话里用户发的图片取回字节，
    作为多模态消息内容传给 Agent 模型。失败抛 RuntimeError。
    """
    # 坑1：当前 lark-oapi 版本无 A 前缀异步 request 类，同步命名的
    # GetMessageResourceRequest 同样用于 aget，type 直接挂在 builder 上。
    # 坑2：必须走 message_resource 域而非 message 域——后者硬编码
    # str(resp.content, UTF_8) 解 JSON，对图片二进制（JPEG FF D8 FF 开头）
    # 直接 UnicodeDecodeError；message_resource 才有 BytesIO 分支。
    from lark_oapi.api.im.v1 import GetMessageResourceRequest

    if client is None:
        client = await get_safety_feishu_client()

    req = (
        GetMessageResourceRequest.builder()
        .message_id(message_id)
        .file_key(file_key)
        .type("image")
        .build()
    )
    resp = await client.im.v1.message_resource.aget(req)
    if not resp.success():
        raise RuntimeError(
            f"下载飞书图片失败: code={resp.code}, msg={resp.msg}, file_key={file_key[:16]}"
        )
    if not resp.file:
        raise RuntimeError("下载飞书图片失败: 响应为空")
    # resp.file 是 BytesIO（IO[Any]），读成 bytes 才能进多模态消息
    return resp.file.read()


def sniff_image_mime(data: bytes) -> str:
    """按魔数嗅探图片格式，避免把 JPEG 等误标成 image/png。"""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"GIF8":
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:2] == b"BM":
        return "image/bmp"
    return "image/png"  # 兜底：飞书消息图片常见 png
