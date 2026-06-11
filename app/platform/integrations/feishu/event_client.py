"""飞书事件订阅客户端（WebSocket 长连接模式）。

不依赖 lark_oapi SDK 的 WsClient，直接使用 raw WebSocket 连接。
原因：SDK 使用 protobuf 二进制协议，自定义事件分发器无法可靠接收事件。
"""

import asyncio
import json
import logging
import ssl
from typing import Any

import httpx
import websockets

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# 事件类型 → 处理器列表
_handlers: dict[str, list] = {}
_stop: asyncio.Event | None = None

# 飞书 endpoint
FEISHU_DOMAIN = "https://open.feishu.cn"
WS_ENDPOINT_URL = f"{FEISHU_DOMAIN}/callback/ws/endpoint"


def on_event(event_type: str):
    """装饰器：注册事件处理器。"""
    def decorator(func):
        _handlers.setdefault(event_type, []).append(func)
        logger.info("注册飞书事件: type=%s handler=%s", event_type, func.__name__)
        return func
    return decorator


async def _dispatch(event_type: str, event_data: dict[str, Any]) -> None:
    """分发事件给注册的处理器。"""
    handlers = _handlers.get(event_type, [])
    if handlers:
        logger.info("分发飞书事件: type=%s", event_type)
        for handler in handlers:
            try:
                await handler(event_data)
            except Exception:
                logger.exception("事件处理器异常: %s", handler.__name__)


async def _get_ws_url(app_id: str, app_secret: str) -> str | None:
    """获取 WebSocket 连接 URL。"""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            WS_ENDPOINT_URL,
            json={"AppID": app_id, "AppSecret": app_secret},
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 0:
                url = data.get("data", {}).get("URL")
                logger.info("获取 WebSocket URL 成功: %s", url[:80] if url else "empty")
                return url
            else:
                logger.error("获取 WebSocket URL 失败: code=%s msg=%s", data.get("code"), data.get("msg"))
        else:
            logger.error("获取 WebSocket URL HTTP 错误: %s", resp.status_code)
    return None


async def start_ws() -> None:
    """启动飞书 WebSocket 连接。"""
    global _stop
    _stop = asyncio.Event()

    settings = get_settings()

    if not settings.FEISHU_APP_ID or not settings.FEISHU_APP_SECRET:
        logger.warning("飞书配置缺失，跳过事件订阅")
        return

    logger.info("启动飞书事件订阅 (app_id=%s)", settings.FEISHU_APP_ID)

    while not _stop.is_set():
        try:
            # 1. 获取 WebSocket URL
            ws_url = await _get_ws_url(settings.FEISHU_APP_ID, settings.FEISHU_APP_SECRET)
            if not ws_url:
                logger.error("无法获取 WebSocket URL，10 秒后重试")
                await asyncio.sleep(10)
                continue

            # 2. 连接 WebSocket
            ssl_context = ssl.create_default_context()
            async with websockets.connect(
                ws_url,
                ssl=ssl_context,
                max_size=2 ** 23,
                ping_interval=60,
                ping_timeout=10,
                close_timeout=5,
            ) as ws:
                logger.info("飞书 WebSocket 已连接: %s", ws_url[:80])

                # 3. 接收消息循环
                while not _stop.is_set():
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=120)
                    except asyncio.TimeoutError:
                        continue

                    # 处理消息
                    if isinstance(message, bytes):
                        # protobuf 二进制帧 → 用 lark_oapi Frame 解析
                        try:
                            from lark_oapi.ws.pb.pbbp2_pb2 import Frame
                            from lark_oapi.ws.client import MessageType, HEADER_TYPE, _get_by_key

                            frame = Frame()
                            frame.ParseFromString(message)

                            hs = frame.headers
                            type_val = _get_by_key(hs, HEADER_TYPE) if hs else ""
                            try:
                                msg_type = MessageType(type_val)
                            except Exception:
                                msg_type = None

                            if msg_type == MessageType.EVENT:
                                # 事件帧 → 解析 JSON payload
                                event = json.loads(frame.payload.decode("utf-8"))
                                # 临时完整打印事件用于调试
                                logger.info("📨 收到飞书事件(完整): %s", json.dumps(event, ensure_ascii=False)[:800])
                                await _dispatch_event(event)
                            else:
                                logger.debug("收到非事件帧: type=%s", msg_type)
                        except Exception as e:
                            logger.debug("protobuf 解析失败 (%d bytes): %s", len(message), e)
                    else:
                        # 文本消息（ping/pong 等）
                        try:
                            event = json.loads(message)
                            msg_type = event.get("type", "")
                            if msg_type == "ping":
                                await ws.send(json.dumps({"type": "pong"}))
                            else:
                                await _dispatch_event(event)
                        except json.JSONDecodeError:
                            logger.debug("收到非 JSON 文本消息")

        except asyncio.CancelledError:
            break
        except websockets.exceptions.ConnectionClosed as e:
            logger.warning("WebSocket 连接关闭: %s，5 秒后重连", e)
        except Exception:
            logger.exception("WebSocket 异常，10 秒后重连")

        try:
            await asyncio.wait_for(_stop.wait(), timeout=10)
        except asyncio.TimeoutError:
            pass

    logger.info("飞书 WebSocket 客户端已停止")


async def _dispatch_event(event: dict[str, Any]) -> None:
    """解析并分发单个事件。"""
    # v2 格式: {"schema": "2.0", "header": {"event_type": "..."}, "event": {...}}
    header = event.get("header", {})
    event_type = header.get("event_type", "")

    if not event_type:
        # v1 格式: {"type": "event", "event": {"type": "...", ...}}
        inner = event.get("event", {})
        event_type = inner.get("type", event.get("type", ""))

    if event_type:
        event_data = event.get("event", event)
        await _dispatch(event_type, event_data)
    else:
        logger.debug("无法确定事件类型: %s", json.dumps(event, ensure_ascii=False)[:200])


async def stop_ws() -> None:
    """停止 WebSocket 连接。"""
    global _stop
    if _stop:
        _stop.set()
