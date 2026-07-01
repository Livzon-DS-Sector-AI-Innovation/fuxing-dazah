"""设备模块飞书事件处理器 — 巡检交互 + 验收卡片回调。

在 WebSocket 线程中同步调用，
通过 asyncio.run_coroutine_threadsafe 桥接到主 async event loop。
使用设备交互机器人凭证，通过 user_id 识别用户。
"""

import asyncio
import json
import logging
import uuid

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    P2CardActionTriggerV1,
    P2ImMessageReceiveV1,
)

logger = logging.getLogger(__name__)

_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """设置主 event loop 引用。"""
    global _main_loop
    _main_loop = loop


def build_equipment_event_handler() -> lark.EventDispatcherHandler:
    """构建设备模块飞书事件处理器。"""
    return (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(_on_message_receive)
        .register_p2_card_action_trigger_v1(_on_card_action)
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

    open_id = ""
    user_id = ""
    if sender and sender.sender_id:
        open_id = sender.sender_id.open_id or ""
        user_id = sender.sender_id.user_id or ""

    logger.info(
        "设备机器人收到消息: type=%s, user_id=%s, open_id=%s, "
        "chat_type=%s, message_id=%s",
        msg_type, user_id, open_id, chat_type, message_id,
    )

    if _main_loop is None:
        logger.error("主 event loop 未设置，无法处理消息")
        return

    future = asyncio.run_coroutine_threadsafe(
        _handle_message_async(
            msg_type=msg_type,
            message_id=message_id,
            chat_id=chat_id,
            chat_type=chat_type,
            open_id=open_id,
            user_id=user_id,
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
    open_id: str,
    user_id: str,
    content: str,
) -> None:
    """异步处理消息（在主 event loop 中运行）。"""
    if _main_loop is None:
        set_main_loop(asyncio.get_running_loop())

    # 消息去重
    from app.core.redis import redis_client

    dedup_key = f"feishu:msg:{message_id}"
    is_new = await redis_client.set(dedup_key, "1", ex=600, nx=True)
    if not is_new:
        logger.info("重复消息已忽略: message_id=%s", message_id)
        return

    if msg_type == "image":
        await _handle_image_message(
            user_id=user_id,
            open_id=open_id,
            message_id=message_id,
            chat_id=chat_id,
            chat_type=chat_type,
            content=content,
        )
    elif msg_type == "text":
        await _handle_text_message(
            open_id=open_id,
            chat_id=chat_id,
            chat_type=chat_type,
            content=content,
        )
    else:
        logger.info("忽略非图片/文本消息: type=%s", msg_type)


async def _handle_image_message(
    *,
    user_id: str,
    open_id: str,
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
        user_id=user_id,
        open_id=open_id,
        message_id=message_id,
        image_key=image_key,
        chat_id=chat_id,
        chat_type=chat_type,
    )


async def _handle_text_message(
    *,
    open_id: str,
    chat_id: str,
    chat_type: str,
    content: str,
) -> None:
    """处理文本消息 — 会话感知路由。"""
    try:
        content_data = json.loads(content)
        text = content_data.get("text", "").strip()
    except (json.JSONDecodeError, TypeError):
        return

    # 去掉 @机器人 的前缀
    if " " in text:
        text = text.split(" ", 1)[-1].strip()

    # 统一路由到新的命令处理系统
    from app.modules.equipment.service.inspection_feishu import (
        process_feishu_text,
    )

    await process_feishu_text(open_id, text)


def _on_card_action(data: P2CardActionTriggerV1) -> None:
    """卡片按钮点击事件（同步入口，在 WS 线程中调用）。"""
    event = data.event
    if not event:
        return

    action_value = getattr(event, "action_value", None) or ""
    open_id = ""
    user_id = ""
    if event.operator:
        open_id = event.operator.open_id or ""
        user_id = event.operator.user_id or ""

    logger.info(
        "卡片按钮点击: user_id=%s, value=%s", user_id, action_value,
    )

    if _main_loop is None:
        logger.error("主 event loop 未设置")
        return

    future = asyncio.run_coroutine_threadsafe(
        _handle_card_action_async(
            action_value=action_value,
            open_id=open_id,
            user_id=user_id,
        ),
        _main_loop,
    )
    try:
        future.result(timeout=30)
    except Exception:
        logger.exception("异步处理卡片回调超时或异常")


async def _handle_card_action_async(
    *,
    action_value: str,
    open_id: str,
    user_id: str,
) -> None:
    """处理验收卡片按钮点击。"""
    if _main_loop is None:
        set_main_loop(asyncio.get_running_loop())

    try:
        payload = json.loads(action_value)
    except (json.JSONDecodeError, TypeError):
        logger.error("无法解析卡片 action value: %s", action_value)
        return

    action = payload.get("action")
    work_order_id = payload.get("work_order_id")
    result = payload.get("result")

    if action != "verify" or not work_order_id or result not in ("合格", "不合格"):
        logger.error("无效的卡片 action: %s", payload)
        return

    from sqlalchemy import select as sa_select

    from app.core.database import async_session_factory
    from app.modules.equipment import repository as repo
    from app.modules.equipment.deps import EquipmentAccessContext
    from app.modules.equipment.feishu.notification import send_user_card
    from app.modules.equipment.schemas import WorkOrderVerify
    from app.modules.equipment.service.work_order import verify_work_order
    from app.platform.identity.models import User

    async with async_session_factory() as db:
        # 查找操作用户
        user = None
        if user_id:
            result_ = await db.execute(
                sa_select(User).where(
                    User.feishu_user_id == user_id,
                    User.is_deleted == False,  # noqa: E712
                )
            )
            user = result_.scalar_one_or_none()

        if not user:
            await send_user_card(
                open_id=open_id,
                title="❌ 未找到用户",
                receive_id_type="open_id",
                content="未找到与您的飞书账号关联的系统用户，无法执行验收操作。",
            )
            return

        wo = await repo.get_work_order_by_id(db, uuid.UUID(work_order_id))
        if not wo:
            await send_user_card(
                open_id=open_id,
                title="❌ 工单不存在",
                receive_id_type="open_id",
                content=f"工单 {work_order_id} 不存在或已删除。",
            )
            return

        if wo.status != "待验收":
            await send_user_card(
                open_id=open_id,
                title="⚠️ 无法验收",
                receive_id_type="open_id",
                content=f"工单 **{wo.work_order_no}** 当前状态为「{wo.status}」，"
                        "只有「待验收」的工单才能验收。",
            )
            return

        label = "验收通过" if result == "合格" else "退回"
        try:
            verify_data = WorkOrderVerify(
                result=result,  # type: ignore[arg-type]
                remark=f"通过飞书卡片{label}",
            )
            ctx = EquipmentAccessContext(user=user, data_scope="all")
            await verify_work_order(db, wo.id, ctx, verify_data)
            await db.commit()
        except Exception as e:
            logger.exception("飞书卡片验收失败: %s", e)
            await send_user_card(
                open_id=open_id,
                title="❌ 操作失败",
                receive_id_type="open_id",
                content=f"验收操作失败：{e}",
            )
            return

    await send_user_card(
        open_id=open_id,
        title=f"✅ {label}",
        receive_id_type="open_id",
        content=(
            f"工单 **{wo.work_order_no}**"
            f"（{wo.equipment.name if wo.equipment else ''}）\n"
            f"已{label}。"
        ),
    )
