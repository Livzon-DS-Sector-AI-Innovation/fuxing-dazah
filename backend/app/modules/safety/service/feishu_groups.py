"""飞书机器人所在群聊列表服务（5 分钟缓存）。

供「定时任务发送对象」编辑弹窗使用：只列出当前安全模块飞书应用可见的群聊，
外部 API 失败时回退缓存（无缓存则返回空列表 + warning）。
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_cache: dict[str, Any] = {
    "ts": 0.0,
    "items": [],
}
_CACHE_TTL = 5 * 60  # 5 分钟


async def _fetch_from_feishu() -> list[dict[str, Any]]:
    """调用 GET /open-apis/im/v1/chats 分页聚合机器人可见群聊。"""
    from lark_oapi.api.im.v1 import ListChatRequest

    from app.modules.safety.feishu.client import (
        get_safety_feishu_client,
        get_safety_tenant_token,
    )

    client = await get_safety_feishu_client()
    token = await get_safety_tenant_token(client)
    items: list[dict[str, Any]] = []
    page_token: str | None = None
    for _ in range(20):  # 防死循环，最多 20 页
        builder = (
            ListChatRequest.builder()
            .page_size(100)
        )
        if page_token:
            builder.page_token(page_token)
        req = builder.build()
        req.headers["Authorization"] = f"Bearer {token}"
        resp = await client.im.v1.chat.alist(req)
        if not resp.success():
            logger.error("飞书群聊列表失败: code=%s msg=%s", resp.code, resp.msg)
            raise RuntimeError(f"飞书群聊列表失败: {resp.code} {resp.msg}")
        data = resp.data
        for chat in (data.items or []):
            if chat.chat_id:
                items.append({
                    "chat_id": chat.chat_id,
                    "name": chat.name or "",
                    "description": chat.description or "",
                    "avatar": chat.avatar or "",
                })
        if not data.has_more or not data.page_token:
            break
        page_token = data.page_token
    return items


async def list_feishu_groups(force: bool = False) -> dict[str, Any]:
    """返回机器人所在群聊列表（命中缓存直接返回）。"""
    now = time.time()
    if not force and _cache["items"] and (now - _cache["ts"]) < _CACHE_TTL:
        return {
            "items": _cache["items"],
            "cached_at": _cache["ts"],
            "warning": None,
        }
    try:
        items = await _fetch_from_feishu()
        _cache["ts"] = now
        _cache["items"] = items
        return {"items": items, "cached_at": now, "warning": None}
    except Exception as exc:
        logger.exception("飞书群聊列表拉取失败")
        if _cache["items"]:
            return {
                "items": _cache["items"],
                "cached_at": _cache["ts"],
                "warning": f"飞书接口暂不可用，展示缓存数据（{exc}）",
            }
        return {"items": [], "cached_at": now, "warning": f"飞书群聊列表暂不可用（{exc}）"}
