"""飞书事件处理器 — 接收消息和卡片回调。

事件处理器在 WebSocket 线程中同步调用，
通过 asyncio.run_coroutine_threadsafe 桥接到主 async event loop。
"""

import asyncio
import json
import logging

import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

logger = logging.getLogger(__name__)

# 主 event loop 引用，由 inspection_feishu 模块在首次调用时设置
_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """设置主 event loop 引用，供异步桥接使用。"""
    global _main_loop
    _main_loop = loop


def build_event_handler() -> lark.EventDispatcherHandler:
    """构建飞书事件处理器，注册所有事件监听。"""
    return (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(_on_message_receive)
        .build()
    )


def _on_message_receive(data: P2ImMessageReceiveV1) -> None:
    """消息接收事件处理（同步入口，在 WS 线程中调用）。"""
    event = data.event
    if not event or not event.message:
        return

    message = event.message
    sender = event.sender
    msg_type = message.message_type
    message_id = message.message_id
    chat_id = message.chat_id or ""
    chat_type = message.chat_type or ""
    sender_id = ""

    if sender and sender.sender_id:
        sender_id = sender.sender_id.open_id or ""

    logger.info(
        "收到飞书消息: type=%s, sender=%s, chat_type=%s, message_id=%s",
        msg_type, sender_id, chat_type, message_id,
    )

    # 桥接到主 async loop
    if _main_loop is None:
        logger.error("主 event loop 未设置，无法处理消息")
        return

    future = asyncio.run_coroutine_threadsafe(
        _handle_message_async(
            msg_type=msg_type,
            message_id=message_id,
            chat_id=chat_id,
            chat_type=chat_type,
            sender_open_id=sender_id,
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
    chat_id: str,
    chat_type: str,
    sender_open_id: str,
    content: str,
) -> None:
    """异步处理消息（在主 event loop 中运行）。"""
    # 设置主 loop 引用（首次调用时）
    if _main_loop is None:
        set_main_loop(asyncio.get_running_loop())

    if msg_type == "image":
        await _handle_image_message(
            sender_open_id=sender_open_id,
            message_id=message_id,
            chat_id=chat_id,
            chat_type=chat_type,
            content=content,
        )
    elif msg_type == "text":
        await _handle_text_message(
            sender_open_id=sender_open_id,
            chat_id=chat_id,
            chat_type=chat_type,
            content=content,
        )
    else:
        logger.info("忽略非图片/文本消息: type=%s", msg_type)


async def _handle_image_message(
    *,
    sender_open_id: str,
    message_id: str,
    chat_id: str,
    chat_type: str,
    content: str,
) -> None:
    """处理图片消息 → AI 分析巡检照片。"""
    try:
        content_data = json.loads(content)
        image_key = content_data.get("image_key", "")
    except (json.JSONDecodeError, TypeError):
        logger.error("无法解析图片消息内容: %s", content)
        return

    if not image_key:
        logger.error("图片消息缺少 image_key")
        return

    from app.modules.equipment.service.inspection_feishu import (
        process_feishu_image,
    )

    await process_feishu_image(
        open_id=sender_open_id,
        message_id=message_id,
        image_key=image_key,
        chat_id=chat_id,
        chat_type=chat_type,
    )


async def _handle_text_message(
    *,
    sender_open_id: str,
    chat_id: str,
    chat_type: str,
    content: str,
) -> None:
    """处理文本消息 — 简单命令响应。"""
    try:
        content_data = json.loads(content)
        text = content_data.get("text", "").strip()
    except (json.JSONDecodeError, TypeError):
        return

    # 去掉 @机器人 的前缀
    if " " in text:
        text = text.split(" ", 1)[-1].strip()

    from app.platform.integrations.feishu.notification import send_user_card

    if text in ("帮助", "help", "?", "？"):
        await send_user_card(
            open_id=sender_open_id,
            title="🤖 巡检助手使用说明",
            content=(
                "**发送巡检照片**\n"
                "直接拍照或发送图片给机器人，系统会自动识别并分析检查项。\n\n"
                "**注意事项**\n"
                "- 请先在系统中开始巡检任务（状态为「执行中」）\n"
                "- 照片应清晰拍摄设备仪表/标识\n"
                "- 每张照片会立即进行 AI 分析\n"
                "- 分析结果会回复到当前对话"
            ),
        )
    else:
        await send_user_card(
            open_id=sender_open_id,
            title="💡 提示",
            content="请直接发送巡检照片，我会自动分析。\n发送 **帮助** 查看使用说明。",
        )
