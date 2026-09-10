"""飞书 @ 提及标识解析（跨应用修正）。

背景：平台应用（``FEISHU_APP_ID``）与安全模块应用（``SAFETY_FEISHU_APP_ID``）
不是同一个应用，而飞书 ``open_id`` **按应用隔离**。``identity.users.feishu_open_id``
由平台应用同步，拿去给安全应用发消息 / 做卡片 @ 会失败：

    99992361 open_id cross app

因此卡片 @ 提及必须使用「安全应用作用域」的标识。本模块统一解析：

  ① 有邮箱 → ``contact/v3/users/batch_get_id``（``user_id_type=open_id``，≤50/批）
  ② 无邮箱 → ``contact/v3/users/{user_id}`` 反查 ``open_id``
  ③ 两者都没有 → 不返回该人（调用方退化为纯文本姓名）

结果按 ``user_id`` 做进程内缓存（默认 10 分钟），避免每张卡片都打接口。

卡片 @ 语法（官方 Markdown 模块：``<at id=open_id></at>``，应用机器人支持
open_id / user_id / union_id）：见 ``at_tag``。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from typing import Any

import httpx
from sqlalchemy import text

logger = logging.getLogger(__name__)

_CONTACT_BASE = "https://open.feishu.cn/open-apis/contact/v3"
_BATCH_LIMIT = 50
_CACHE_TTL_SECONDS = 600.0

# user_id → (过期时间戳, 安全应用 open_id)
_cache: dict[str, tuple[float, str]] = {}


def _cache_get(user_id: str) -> str | None:
    item = _cache.get(user_id)
    if item and item[0] > time.time():
        return item[1]
    return None


def _cache_put(user_id: str, open_id: str) -> None:
    _cache[user_id] = (time.time() + _CACHE_TTL_SECONDS, open_id)


def clear_cache() -> None:
    """清空缓存（测试/排障用）。"""
    _cache.clear()


async def _load_identity(names: list[str]) -> dict[str, dict[str, str]]:
    """姓名 → {user_id, email}（identity.users，只读）。"""
    if not names:
        return {}
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        rows = await session.execute(
            text(
                "SELECT name, feishu_user_id, email FROM identity.users "
                "WHERE name = ANY(:names) AND is_deleted = false"
            ),
            {"names": names},
        )
        return {
            r[0]: {"user_id": r[1] or "", "email": r[2] or ""}
            for r in rows.fetchall()
        }


async def _batch_get_id_by_email(
    token: str, emails: list[str]
) -> dict[str, str]:
    """邮箱 → 安全应用 open_id（batch_get_id，≤50/批）。"""
    out: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=30) as http:
        for i in range(0, len(emails), _BATCH_LIMIT):
            batch = emails[i : i + _BATCH_LIMIT]
            try:
                resp = await http.post(
                    f"{_CONTACT_BASE}/users/batch_get_id",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    params={"user_id_type": "open_id"},
                    json={"emails": batch},
                )
                data: dict[str, Any] = resp.json()
            except Exception:
                logger.warning("batch_get_id 请求失败", exc_info=True)
                continue
            if data.get("code") != 0:
                logger.warning(
                    "batch_get_id 失败: code=%s msg=%s",
                    data.get("code"), data.get("msg"),
                )
                continue
            for item in (data.get("data") or {}).get("user_list", []):
                email = item.get("email") or ""
                open_id = item.get("user_id") or ""
                if email and open_id:
                    out[email] = open_id
    return out


async def _get_user_open_id(token: str, user_id: str) -> str | None:
    """按 user_id 反查安全应用 open_id（无邮箱时的回退）。"""
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            resp = await http.get(
                f"{_CONTACT_BASE}/users/{user_id}",
                headers={"Authorization": f"Bearer {token}"},
                params={"user_id_type": "user_id"},
            )
            data: dict[str, Any] = resp.json()
    except Exception:
        logger.warning("user_id 反查 open_id 请求失败: %s", user_id, exc_info=True)
        return None
    if data.get("code") != 0:
        logger.warning(
            "user_id 反查 open_id 失败: user_id=%s code=%s msg=%s",
            user_id, data.get("code"), data.get("msg"),
        )
        return None
    return ((data.get("data") or {}).get("user") or {}).get("open_id") or None


async def resolve_open_ids(names: Iterable[str]) -> dict[str, str]:
    """姓名列表 → {姓名: 安全应用 open_id}。

    解析不到的人**不出现在返回值里**，调用方应退化为纯文本姓名。
    """
    wanted = [n for n in {str(x).strip() for x in names} if n]
    if not wanted:
        return {}

    identity = await _load_identity(wanted)

    # 先命中缓存
    out: dict[str, str] = {}
    pending: list[tuple[str, str, str]] = []  # (name, user_id, email)
    for name in wanted:
        info = identity.get(name)
        if not info:
            logger.warning("resolve_open_ids: identity.users 未找到 %r", name)
            continue
        cached = _cache_get(info["user_id"]) if info["user_id"] else None
        if cached:
            out[name] = cached
        else:
            pending.append((name, info["user_id"], info["email"]))

    if not pending:
        return out

    from app.modules.safety.feishu.client import get_safety_tenant_token

    try:
        token = await get_safety_tenant_token()
    except Exception:
        logger.warning("获取安全应用 token 失败，@ 提及退化为纯文本", exc_info=True)
        return out

    # ① 有邮箱的走批量接口
    emails = sorted({email for _, _, email in pending if email})
    email_to_open_id = await _batch_get_id_by_email(token, emails) if emails else {}

    # ② 无邮箱（或批量未命中）的按 user_id 反查
    for name, user_id, email in pending:
        open_id = email_to_open_id.get(email) if email else None
        if not open_id and user_id:
            open_id = await _get_user_open_id(token, user_id)
        if open_id:
            out[name] = open_id
            if user_id:
                _cache_put(user_id, open_id)
        else:
            logger.warning(
                "resolve_open_ids: 未能解析安全应用 open_id: name=%s user_id=%s",
                name, user_id or "-",
            )
    return out


def at_tag(name: str | None, open_id: str | None) -> str:
    """卡片 @ 提及：有安全应用 open_id 用 ``<at id=...></at>``，否则纯文本姓名。"""
    if not name:
        return ""
    if open_id:
        return f"<at id={open_id}></at>"
    return name


__all__ = ["at_tag", "clear_cache", "resolve_open_ids"]
