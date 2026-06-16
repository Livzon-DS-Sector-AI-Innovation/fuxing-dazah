"""设备模块飞书 WebSocket 客户端 — 原生 WebSocket 实现。

使用 raw websockets 连接飞书长连接，避免 lark-oapi SDK 的全局 loop 冲突。
完整实现飞书 WS 协议：protobuf PING 心跳 + DATA 帧 ACK 回复。
"""

import asyncio
import json
import logging
import ssl
from urllib.parse import parse_qs, urlparse

import httpx
import websockets

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

FEISHU_DOMAIN = "https://open.feishu.cn"
WS_ENDPOINT_URL = f"{FEISHU_DOMAIN}/callback/ws/endpoint"

_stop: asyncio.Event | None = None
_ping_interval: int = 120


async def _get_ws_url_and_config() -> tuple[str | None, str]:
    """获取 WS URL 并解析 service_id。返回 (url, service_id)。"""
    app_id = settings.EQUIPMENT_FEISHU_APP_ID
    app_secret = settings.EQUIPMENT_FEISHU_APP_SECRET

    if not app_id or not app_secret:
        logger.error("设备机器人 APP_ID/APP_SECRET 未配置")
        return None, ""

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            WS_ENDPOINT_URL,
            json={"AppID": app_id, "AppSecret": app_secret},
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 0:
                url = data.get("data", {}).get("URL", "")
                # 从 URL 参数中提取 service_id
                q = parse_qs(urlparse(url).query)
                service_id = q.get("service_id", ["0"])[0]
                # 读取 server 下发的 ping 间隔配置
                client_config = data.get("data", {}).get("ClientConfig", {})
                global _ping_interval
                if isinstance(client_config, dict):
                    interval = client_config.get("PingInterval", 0)
                    if interval > 0:
                        _ping_interval = interval
                logger.info(
                    "设备机器人 WS URL 获取成功, service_id=%s, "
                    "ping_interval=%s",
                    service_id, _ping_interval,
                )
                return url, service_id
            logger.error(
                "设备机器人获取 WS URL 失败: code=%s msg=%s",
                data.get("code"), data.get("msg"),
            )
        else:
            logger.error(
                "设备机器人获取 WS URL HTTP 错误: %s", resp.status_code,
            )
    return None, ""


def _build_ping_frame(service_id: int) -> bytes:
    """构建 protobuf PING 帧。"""
    from lark_oapi.ws.const import HEADER_TYPE
    from lark_oapi.ws.enum import FrameType, MessageType
    from lark_oapi.ws.pb.pbbp2_pb2 import Frame

    frame = Frame()
    header = frame.headers.add()
    header.key = HEADER_TYPE
    header.value = MessageType.PING.value
    frame.service = service_id
    frame.method = FrameType.CONTROL.value
    frame.SeqID = 0
    frame.LogID = 0
    return frame.SerializeToString()


async def _ping_loop(ws, service_id: int) -> None:
    """定期发送 protobuf PING 帧保持连接。"""
    while not _stop.is_set():
        try:
            ping_data = _build_ping_frame(service_id)
            await ws.send(ping_data)
            logger.debug("设备机器人 PING 已发送")
        except Exception as e:
            logger.warning("设备机器人 PING 失败: %s", e)
            return
        try:
            await asyncio.wait_for(_stop.wait(), timeout=_ping_interval)
            return
        except TimeoutError:
            pass


def _build_ack_frame(frame, biz_rt: int) -> bytes:
    """构建 DATA 帧的 ACK 回复。"""
    from lark_oapi.ws.const import HEADER_BIZ_RT

    header = frame.headers.add()
    header.key = HEADER_BIZ_RT
    header.value = str(biz_rt)

    ack_resp = json.dumps({"code": 200})
    frame.payload = ack_resp.encode("utf-8")
    return frame.SerializeToString()


async def start_equipment_ws() -> None:
    """启动设备模块飞书 WebSocket 连接（asyncio task）。"""
    global _stop
    _stop = asyncio.Event()

    if not settings.EQUIPMENT_FEISHU_WS_ENABLED:
        logger.info("设备机器人 WS 已禁用 (EQUIPMENT_FEISHU_WS_ENABLED=false)，跳过")
        return

    app_id = settings.EQUIPMENT_FEISHU_APP_ID
    app_secret = settings.EQUIPMENT_FEISHU_APP_SECRET

    if not app_id or not app_secret:
        logger.warning("设备机器人凭证未配置，跳过 WebSocket 启动")
        return

    logger.info("启动设备模块飞书 WebSocket (app_id=%s)", app_id)

    while not _stop.is_set():
        try:
            ws_url, service_id_str = await _get_ws_url_and_config()
            if not ws_url:
                logger.error("设备机器人无法获取 WS URL，10 秒后重试")
                await asyncio.sleep(10)
                continue

            service_id = int(service_id_str) if service_id_str else 0
            ssl_context = ssl.create_default_context()

            async with websockets.connect(
                ws_url,
                ssl=ssl_context,
                max_size=2 ** 23,
                ping_interval=None,  # 用 protobuf PING 代替 WS ping
                ping_timeout=None,
                close_timeout=5,
            ) as ws:
                logger.info("设备机器人 WebSocket 已连接")

                # 启动 protobuf PING 心跳
                ping_task = asyncio.create_task(
                    _ping_loop(ws, service_id),
                )

                try:
                    while not _stop.is_set():
                        try:
                            message = await asyncio.wait_for(
                                ws.recv(), timeout=180,
                            )
                        except TimeoutError:
                            continue

                        if isinstance(message, bytes):
                            await _handle_binary_message(ws, message)
                finally:
                    ping_task.cancel()

        except asyncio.CancelledError:
            break
        except websockets.exceptions.ConnectionClosed as e:
            logger.warning(
                "设备机器人 WebSocket 连接关闭: %s，5 秒后重连", e,
            )
            await asyncio.sleep(5)
        except Exception:
            logger.exception("设备机器人 WebSocket 异常，10 秒后重连")
            await asyncio.sleep(10)

        try:
            await asyncio.wait_for(_stop.wait(), timeout=5)
        except TimeoutError:
            pass

    logger.info("设备机器人 WebSocket 客户端已停止")


async def _handle_binary_message(ws, message: bytes) -> None:
    """处理 protobuf 帧（区分 CONTROL 和 DATA）。"""
    try:
        from lark_oapi.ws.client import _get_by_key
        from lark_oapi.ws.const import HEADER_TYPE
        from lark_oapi.ws.enum import FrameType, MessageType
        from lark_oapi.ws.pb.pbbp2_pb2 import Frame

        frame = Frame()
        frame.ParseFromString(message)

        ft = FrameType(frame.method)

        if ft == FrameType.CONTROL:
            # CONTROL 帧：PING/PONG，仅记录
            try:
                type_val = _get_by_key(frame.headers, HEADER_TYPE)
                logger.debug("设备机器人 CONTROL 帧: %s", type_val)
            except Exception:
                pass
            return

        if ft == FrameType.DATA:
            import time

            start_ms = int(round(time.time() * 1000))
            type_val = _get_by_key(frame.headers, HEADER_TYPE)
            msg_type = MessageType(type_val)

            if msg_type == MessageType.EVENT:
                event = json.loads(frame.payload.decode("utf-8"))
                await _dispatch_event(event)
            else:
                logger.info("设备机器人 DATA 帧: type=%s", msg_type)

            # 发送 ACK
            end_ms = int(round(time.time() * 1000))
            ack_data = _build_ack_frame(frame, end_ms - start_ms)
            await ws.send(ack_data)

    except Exception as e:
        logger.warning(
            "设备机器人帧处理失败 (%d bytes): %s",
            len(message), e,
        )


async def _dispatch_event(event: dict) -> None:
    """解析事件并分发给设备模块事件处理器。"""
    header = event.get("header", {})
    event_type = header.get("event_type", "")

    if not event_type:
        inner = event.get("event", {})
        event_type = inner.get("type", event.get("type", ""))

    if event_type == "im.message.receive_v1":
        event_data = event.get("event", event)
        await _handle_message_event(event_data)
    else:
        logger.info("设备机器人忽略事件: %s", event_type)


async def _handle_message_event(event_data: dict) -> None:
    """处理 im.message.receive_v1 事件。"""
    message = event_data.get("message", {})
    sender = event_data.get("sender", {})
    sender_id = sender.get("sender_id", {})

    msg_type = message.get("message_type", "")
    message_id = message.get("message_id", "")
    open_id = sender_id.get("open_id", "")
    user_id = sender_id.get("user_id", "")
    chat_id = message.get("chat_id", "")
    chat_type = message.get("chat_type", "")
    content = message.get("content", "{}")

    logger.info(
        "设备机器人收到消息: type=%s, user_id=%s, open_id=%s, "
        "message_id=%s",
        msg_type, user_id, open_id, message_id,
    )

    # 消息去重
    from app.core.redis import redis_client

    dedup_key = f"feishu:msg:{message_id}"
    is_new = await redis_client.set(dedup_key, "1", ex=120, nx=True)
    if not is_new:
        logger.info("重复消息已忽略: message_id=%s", message_id)
        return

    if msg_type == "image":
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
    elif msg_type == "text":
        await _handle_text_command(
            user_id=user_id,
            open_id=open_id,
            chat_id=chat_id,
            chat_type=chat_type,
            content=content,
        )
    else:
        logger.info("忽略非图片/文本消息: type=%s", msg_type)


async def _handle_text_command(
    *,
    user_id: str,
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

    # 群聊中 @机器人 时，文本前缀为 @mention（如 "@_user_1" 或 "@设备助手"），需要去掉
    if text.startswith("@") and " " in text:
        text = text.split(" ", 1)[-1].strip()

    from app.modules.equipment.service.inspection_session import get_session

    session = await get_session(open_id)

    if session:
        if text in ("提交", "确认", "确认提交"):
            from app.modules.equipment.service.inspection_feishu import (
                submit_pending_results,
            )

            await submit_pending_results(open_id)
        elif text in ("取消", "放弃", "取消提交"):
            from app.modules.equipment.service.inspection_feishu import (
                cancel_pending_session,
            )

            await cancel_pending_session(open_id)
        else:
            from app.modules.equipment.service.inspection_feishu import (
                process_correction,
            )

            await process_correction(open_id, text)
    else:
        from app.modules.equipment.feishu.notification import send_user_card

        if text in ("帮助", "help", "?", "？"):
            await send_user_card(
                open_id=open_id,
                title="🤖 设备助手使用说明",
                receive_id_type="open_id",
                content=(
                    "**巡检功能**\n"
                    "直接发送巡检照片，系统自动 AI 分析。\n"
                    "分析完成后回复「提交」保存结果。\n\n"
                    "**工单功能**\n"
                    "发送「工单」或「我的工单」查看您的工单列表\n"
                    "发送「完成 工单号」提交完成执行中的工单\n"
                    "发送「完成 工单号 描述」可同时填写维修过程\n\n"
                    "**示例**\n"
                    "`完成 WO-20260615-0001`\n"
                    "`完成 WO-20260615-0001 更换了密封圈`"
                ),
            )
        elif text in ("工单", "我的工单"):
            from app.modules.equipment.service.work_order_feishu import (
                list_user_work_orders,
            )

            await list_user_work_orders(user_id=user_id, open_id=open_id)
        elif text.startswith("完成"):
            rest = text[2:].strip()
            if not rest:
                await send_user_card(
                    open_id=open_id,
                    title="💡 提示",
                    receive_id_type="open_id",
                    content="请输入工单号，例如：`完成 WO-20260615-0001`",
                )
                return

            parts = rest.split(" ", 1)
            wo_no = parts[0]
            detail = parts[1] if len(parts) > 1 else None

            from app.modules.equipment.service.work_order_feishu import (
                complete_work_order_by_no,
            )

            await complete_work_order_by_no(
                user_id=user_id,
                open_id=open_id,
                work_order_no=wo_no,
                repair_detail=detail,
            )
        else:
            await send_user_card(
                open_id=open_id,
                title="💡 提示",
                receive_id_type="open_id",
                content=(
                    "发送巡检照片可直接 AI 分析。\n"
                    "发送「工单」查看您的工单。\n"
                    "发送「帮助」查看完整使用说明。"
                ),
            )


async def stop_equipment_ws() -> None:
    """停止设备模块 WebSocket 连接。"""
    global _stop
    if _stop:
        _stop.set()
