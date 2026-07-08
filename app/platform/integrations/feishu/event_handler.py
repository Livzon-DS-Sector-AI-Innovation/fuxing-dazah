"""飞书事件处理器 — 全局飞书应用。

事件处理器在 WebSocket 线程中同步调用，
通过 asyncio.run_coroutine_threadsafe 桥接到主 async event loop。

已合并设备模块巡检交互和验收卡片回调处理。
"""

import asyncio
import logging

import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTrigger

logger = logging.getLogger(__name__)

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
        .register_p2_card_action_trigger(_on_card_action)
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
# 卡片按钮回调（验收通过 / 退回）
# ═══════════════════════════════════════════════════════════════


def _on_card_action(data: P2CardActionTrigger) -> None:
    """卡片按钮点击事件（同步入口，在 WS 线程中调用）。"""
    event = data.event
    if not event:
        return

    # 新版 SDK: action.value 已经是 dict，无需手动解析 JSON
    action_value = event.action.value if event.action else {}
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
    action_value: dict,
    user_id: str,
) -> None:
    """处理验收卡片按钮点击。"""
    import uuid as _uuid

    from sqlalchemy import select as sa_select

    from app.core.database import async_session_factory
    from app.modules.equipment.deps import EquipmentAccessContext
    from app.modules.equipment.schemas.work_order import WorkOrderVerify
    from app.modules.equipment.service.work_order import verify_work_order
    from app.platform.identity.models import User
    from app.platform.integrations.feishu.notification import send_user_card

    if _main_loop is None:
        set_main_loop(asyncio.get_running_loop())

    # 新版 SDK 已预解析 action value 为 dict
    payload = action_value or {}
    action = payload.get("action")
    work_order_id = payload.get("work_order_id")

    if action == "approve":
        result = "合格"
    elif action == "reject":
        result = "不合格"
    else:
        logger.error("无效的卡片 action: %s", payload)
        return

    if not work_order_id:
        logger.error("卡片回调缺少 work_order_id: %s", payload)
        return

    async with async_session_factory() as db:
        # 查找操作用户
        user = None
        if user_id:
            user_result = await db.execute(
                sa_select(User).where(
                    User.feishu_user_id == user_id,
                    User.is_deleted == False,  # noqa: E712
                )
            )
            user = user_result.scalar_one_or_none()

        if not user:
            logger.warning("卡片回调：未找到飞书用户 %s", user_id)
            return

        # 查找工单
        from app.modules.equipment import repository as equip_repo

        wo = await equip_repo.get_work_order_by_id(db, _uuid.UUID(work_order_id))
        if not wo:
            await send_user_card(
                open_id=user.feishu_user_id,
                title="❌ 工单不存在",
                receive_id_type="user_id",
                content=f"工单 {work_order_id} 不存在或已删除。",
            )
            return

        if wo.status != "待验收":
            await send_user_card(
                open_id=user.feishu_user_id,
                title="⚠️ 无法验收",
                receive_id_type="user_id",
                content=(
                    f"工单 **{wo.work_order_no}** 当前状态为「{wo.status}」，"
                    "只有「待验收」的工单才能验收。"
                ),
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
                open_id=user.feishu_user_id,
                title="❌ 操作失败",
                receive_id_type="user_id",
                content=f"验收操作失败：{e}",
            )
            return

        # ponytail: 操作反馈，只发关键信息
        eq_name = wo.equipment.name if wo.equipment else ""
        await send_user_card(
            open_id=user.feishu_user_id,
            title=f"✅ {label}",
            receive_id_type="user_id",
            content=(
                f"工单 **{wo.work_order_no}**（{eq_name}）\n"
                f"已{label}"
            ),
        )
