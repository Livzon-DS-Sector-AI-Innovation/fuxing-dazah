"""飞书事件处理器 — 全局飞书应用。

事件处理器在 WebSocket 线程中同步调用，
通过 asyncio.run_coroutine_threadsafe 桥接到主 async event loop。

事件到业务模块的分发全部采用注册制：
- 卡片按钮回调按 action 查表分发（register_card_action_handler）
- 多维表格事件广播给所有已注册 handler（register_bitable_record_handler），
  各 handler 内部自行过滤归属
平台层不内含任何业务逻辑。
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import lark_oapi as lark
from lark_oapi.api.drive.v1 import P2DriveFileBitableRecordChangedV1
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTrigger

logger = logging.getLogger(__name__)

_main_loop: asyncio.AbstractEventLoop | None = None

CardActionHandler = Callable[[dict[str, Any], str], Awaitable[None]]
BitableRecordHandler = Callable[
    [str, str, list[dict[str, Any]]], Awaitable[None],
]


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """设置主 event loop 引用，供异步桥接使用。"""
    global _main_loop
    _main_loop = loop


def build_event_handler() -> lark.EventDispatcherHandler:
    """构建飞书事件处理器，注册所有事件监听。"""
    return (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(_on_message_receive)
        .register_p2_card_action_trigger(_on_card_action)  # pyright: ignore[reportArgumentType]
        .register_p2_drive_file_bitable_record_changed_v1(_on_bitable_record_changed)
        .build()
    )


def _on_message_receive(data: P2ImMessageReceiveV1) -> None:
    """消息接收事件处理（同步入口，在 WS 线程中调用）。"""
    event = data.event
    if not event or not event.message:
        return

    message = event.message
    sender = event.sender
    msg_type = message.message_type or ""
    message_id = message.message_id or ""
    chat_type = message.chat_type or ""
    sender_id = ""

    if sender and sender.sender_id:
        sender_id = sender.sender_id.open_id or ""

    logger.info(
        "全局飞书收到消息: type=%s, sender=%s, chat_type=%s, message_id=%s",
        msg_type, sender_id, chat_type, message_id,
    )

    if _main_loop is None:
        logger.error("主 event loop 未设置，无法处理消息")
        return

    future = asyncio.run_coroutine_threadsafe(
        _handle_message_async(
            msg_type=msg_type,
            message_id=message_id,
            content=message.content or "{}",
        ),
        _main_loop,
    )
    try:
        future.result(timeout=120)
    except Exception:
        logger.exception("异步处理消息超时或异常")


async def _handle_message_async(
    *,
    msg_type: str,
    message_id: str,
    content: str,
) -> None:
    """异步处理消息（在主 event loop 中运行）。"""
    if _main_loop is None:
        set_main_loop(asyncio.get_running_loop())

    # 消息去重
    from app.core.redis import redis_client

    dedup_key = f"feishu:msg:{message_id}"
    is_new = await redis_client.set(dedup_key, "1", ex=120, nx=True)
    if not is_new:
        logger.info("重复消息已忽略: message_id=%s", message_id)
        return

    logger.info("全局飞书消息已记录: type=%s, message_id=%s", msg_type, message_id)


# ═══════════════════════════════════════════════════════════════
# 卡片按钮回调 — 注册制分发
# ═══════════════════════════════════════════════════════════════

_CARD_ACTION_HANDLERS: dict[str, CardActionHandler] = {}


def register_card_action_handler(
    action: str, handler: CardActionHandler,
) -> None:
    """业务模块注册卡片 action 的处理器。

    应用启动时调用（见 main.py 接线），飞书卡片按钮点击后
    按 payload["action"] 查表分发。重复注册视为配置错误。
    """
    if action in _CARD_ACTION_HANDLERS:
        raise ValueError(f"Card action '{action}' is already registered")
    _CARD_ACTION_HANDLERS[action] = handler


def _on_card_action(data: P2CardActionTrigger) -> None:
    """卡片按钮点击事件（同步入口，在 WS 线程中调用）。"""
    event = data.event
    if not event:
        return

    # 新版 SDK: action.value 已经是 dict，无需手动解析 JSON
    action_value = (event.action.value if event.action else {}) or {}
    user_id = ""
    if event.operator:
        user_id = event.operator.user_id or ""

    logger.info("卡片按钮点击: user_id=%s, value=%s", user_id, action_value)

    if _main_loop is None:
        logger.error("主 event loop 未设置，无法处理卡片回调")
        return

    future = asyncio.run_coroutine_threadsafe(
        _handle_card_action_async(action_value=action_value, user_id=user_id),
        _main_loop,
    )
    try:
        future.result(timeout=30)
    except Exception:
        logger.exception("异步处理卡片回调超时或异常")


async def _handle_card_action_async(
    *,
    action_value: dict[str, Any],
    user_id: str,
) -> None:
    """按注册表分发卡片按钮点击给业务模块。"""
    if _main_loop is None:
        set_main_loop(asyncio.get_running_loop())

    # 新版 SDK 已预解析 action value 为 dict
    payload = action_value or {}
    action = payload.get("action")
    if not action:
        logger.error("卡片回调缺少 action: %s", payload)
        return

    handler = _CARD_ACTION_HANDLERS.get(action)
    if handler is None:
        logger.error("未注册的卡片 action: %s", payload)
        return

    await handler(payload, user_id)


# ═══════════════════════════════════════════════════════════════
# 多维表格记录变更 — 广播注册制
# ═══════════════════════════════════════════════════════════════

_BITABLE_RECORD_HANDLERS: list[BitableRecordHandler] = []


def register_bitable_record_handler(handler: BitableRecordHandler) -> None:
    """业务模块注册多维表格事件处理器。

    每个事件广播给所有已注册 handler（多模块共享全局订阅），
    各 handler 按 file_token/table_id 自行过滤归属。
    应用启动时调用（见 main.py 接线），重复注册视为配置错误。
    """
    if handler in _BITABLE_RECORD_HANDLERS:
        raise ValueError("Bitable record handler is already registered")
    _BITABLE_RECORD_HANDLERS.append(handler)


def _on_bitable_record_changed(data: P2DriveFileBitableRecordChangedV1) -> None:
    """多维表格记录变更事件（同步入口，在 WS 线程中调用）。"""
    event = data.event
    if not event:
        return

    action_list = [
        {
            "action": a.action,
            "record_id": a.record_id,
            "after_value": {f.field_id: f.field_value for f in a.after_value or []},
            "before_value": {f.field_id: f.field_value for f in a.before_value or []},
        }
        for a in (event.action_list or [])
    ]
    if not action_list:
        return

    logger.info(
        "多维表格事件: file_token=%s table_id=%s actions=%d",
        event.file_token, event.table_id, len(action_list),
    )

    if _main_loop is None:
        logger.error("主 event loop 未设置，无法处理多维表格事件")
        return

    future = asyncio.run_coroutine_threadsafe(
        _handle_bitable_record_changed_async(
            file_token=event.file_token or "",
            table_id=event.table_id or "",
            action_list=action_list,
        ),
        _main_loop,
    )
    try:
        future.result(timeout=120)
    except Exception:
        logger.exception("异步处理多维表格事件超时或异常")


async def _handle_bitable_record_changed_async(
    *,
    file_token: str,
    table_id: str,
    action_list: list[dict[str, Any]],
) -> None:
    """多维表格事件异步处理（在主 event loop 中运行，广播给已注册 handler）。"""
    if _main_loop is None:
        set_main_loop(asyncio.get_running_loop())

    if not _BITABLE_RECORD_HANDLERS:
        logger.warning("多维表格事件未注册处理器: file_token=%s", file_token)
        return

    for handler in _BITABLE_RECORD_HANDLERS:
        try:
            await handler(file_token, table_id, action_list)
        except Exception:
            logger.exception(
                "多维表格事件处理器异常: file_token=%s", file_token,
            )
