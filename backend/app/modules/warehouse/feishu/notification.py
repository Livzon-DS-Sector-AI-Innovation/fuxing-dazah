"""仓储模块专属飞书通知服务。

使用独立凭证（仓库管理机器人）发送文本/卡片消息，仿 safety/feishu/notification.py。
关键差异：支持 dry_run 注入（模块级开关 + 函数参数，参数优先）——dry_run=True 时
构建完整消息体但只记录日志不发送，返回模拟成功。S1 测试策略「发送类 dry-run」
（spec Testing Decisions）依赖此注入口。

与 safety 版的接口差异（供 gateway 对接）：
- send_card / send_card_to_user 接收**完整卡片 dict**（safety 版是 title/content 组合）；
  卡片构建由调用方（gateway/Runner）负责。
"""

import json
import logging
from typing import Any
from uuid import UUID

from app.modules.warehouse.feishu.client import (
    get_warehouse_feishu_client,
    get_warehouse_tenant_token,
)

logger = logging.getLogger(__name__)

# 模块级 dry_run 开关（默认关）；函数参数 dry_run 非 None 时优先
_dry_run: bool = False

# dry_run 时 send_card 返回的模拟 message_id（非 None 即"成功"语义）
DRY_RUN_MESSAGE_ID = "dry_run"


def set_dry_run(value: bool) -> None:
    """设置模块级 dry_run 开关（影响未显式传参的全部发送函数）。"""
    global _dry_run
    _dry_run = value


def _is_dry_run(dry_run: bool | None) -> bool:
    """函数参数优先于模块级开关。"""
    return _dry_run if dry_run is None else dry_run


def _json_dumps(obj: Any) -> str:
    """JSON 序列化，自动将 UUID 转为字符串。"""
    return json.dumps(obj, ensure_ascii=False, default=lambda o: str(o) if isinstance(o, UUID) else o)


def _build_create_payload(
    receive_id_type: str, receive_id: str, msg_type: str, content: str
) -> dict[str, str]:
    """构建飞书 im/v1 message create 的 payload dict（纯函数，测试直接断言）。"""
    return {
        "receive_id_type": receive_id_type,
        "receive_id": receive_id,
        "msg_type": msg_type,
        "content": content,
    }


async def _send_create(payload: dict[str, str]) -> str | None:
    """经仓储专属飞书应用发送消息，成功返回 message_id，失败返回 None（不抛异常）。"""
    try:
        client = await get_warehouse_feishu_client()
        token = await get_warehouse_tenant_token(client)

        from lark_oapi.api.im.v1 import (
            CreateMessageRequest,
            CreateMessageRequestBody,
        )

        req = (
            CreateMessageRequest.builder()
            .receive_id_type(payload["receive_id_type"])
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(payload["receive_id"])
                .msg_type(payload["msg_type"])
                .content(payload["content"])
                .build()
            )
            .build()
        )
        req.headers["Authorization"] = f"Bearer {token}"
        resp = await client.im.v1.message.acreate(req)
        if not resp.success():
            logger.error(
                "仓库飞书发送失败: msg_type=%s receive_id=%s code=%s msg=%s",
                payload["msg_type"], payload["receive_id"], resp.code, resp.msg,
            )
            return None
        message_id = resp.data.message_id if resp.data else None
        logger.info(
            "仓库飞书消息已发送: msg_type=%s receive_id=%s message_id=%s",
            payload["msg_type"], payload["receive_id"], message_id,
        )
        return message_id
    except Exception:
        logger.exception(
            "仓库飞书发送异常: msg_type=%s receive_id=%s",
            payload.get("msg_type"), payload.get("receive_id"),
        )
        return None


async def send_text(chat_id: str, content: str, dry_run: bool | None = None) -> bool:
    """使用仓储飞书应用发送文本消息到群聊。

    Args:
        chat_id: 飞书群聊 chat_id（如 "oc_xxx"）
        content: 文本内容
        dry_run: None=跟随模块级开关；True=只构建消息体并记录日志；False=真发送

    Returns:
        True 表示发送成功（dry_run 时返回模拟成功 True），False 表示失败
    """
    payload = _build_create_payload(
        "chat_id", chat_id, "text", _json_dumps({"text": content})
    )
    if _is_dry_run(dry_run):
        logger.info(
            "[dry_run] 仓库飞书文本(群): %s", _json_dumps(payload)[:500]
        )
        return True
    return await _send_create(payload) is not None


async def send_card(
    chat_id: str, card: dict[str, Any], dry_run: bool | None = None
) -> str | None:
    """使用仓储飞书应用发送卡片消息到群聊。

    Args:
        chat_id: 飞书群聊 chat_id（如 "oc_xxx"）
        card: 完整的飞书卡片 JSON dict（config/header/elements 由调用方构建）
        dry_run: None=跟随模块级开关；True=只构建消息体并记录日志；False=真发送

    Returns:
        成功返回飞书 message_id（如 "om_xxx"；dry_run 时返回 "dry_run" 占位），
        失败返回 None（不抛异常）
    """
    payload = _build_create_payload(
        "chat_id", chat_id, "interactive", _json_dumps(card)
    )
    if _is_dry_run(dry_run):
        logger.info(
            "[dry_run] 仓库飞书卡片(群): %s", _json_dumps(payload)[:500]
        )
        return DRY_RUN_MESSAGE_ID
    return await _send_create(payload)


async def send_card_to_user(
    open_id: str, card: dict[str, Any], dry_run: bool | None = None
) -> bool:
    """使用仓储飞书应用发送卡片消息给单个用户（私聊，按 open_id）。

    Args:
        open_id: 飞书用户 open_id（如 "ou_xxx"）
        card: 完整的飞书卡片 JSON dict
        dry_run: None=跟随模块级开关；True=只构建消息体并记录日志；False=真发送

    Returns:
        True 表示发送成功（dry_run 时返回模拟成功 True），False 表示失败
    """
    payload = _build_create_payload(
        "open_id", open_id, "interactive", _json_dumps(card)
    )
    if _is_dry_run(dry_run):
        logger.info(
            "[dry_run] 仓库飞书卡片(私聊): %s", _json_dumps(payload)[:500]
        )
        return True
    return await _send_create(payload) is not None
