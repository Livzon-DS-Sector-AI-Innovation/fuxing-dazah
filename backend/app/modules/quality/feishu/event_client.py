"""质量模块飞书事件订阅客户端（WebSocket 长连接模式，内网友好）。

独立应用凭证，与全局飞书事件订阅隔离；参照 safety 模块成熟实现。
处理事件：im.message.receive_v1（对话式填报指令）、card.action.trigger（卡片表单，二期）。
"""

import asyncio
import json
import logging
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import websockets

from app.modules.quality.feishu.client import (
    QUALITY_FEISHU_APP_ID,
    QUALITY_FEISHU_APP_SECRET,
    feishu_configured,
)

logger = logging.getLogger(__name__)

_handlers: dict[str, list] = {}
_stop: asyncio.Event | None = None
_ws_task: asyncio.Task | None = None

FEISHU_DOMAIN = "https://open.feishu.cn"
WS_ENDPOINT_URL = f"{FEISHU_DOMAIN}/callback/ws/endpoint"
_ping_interval: int = 120


def on_event(event_type: str):
    """装饰器：注册质量模块飞书事件处理器。"""

    def decorator(func):
        _handlers.setdefault(event_type, []).append(func)
        logger.info("注册质量飞书事件: type=%s handler=%s", event_type, func.__name__)
        return func
    return decorator


async def _dispatch(event_type: str, event_data: dict[str, Any]) -> Any:
    handlers = _handlers.get(event_type, [])
    for handler in handlers:
        try:
            return await handler(event_data)
        except Exception:
            logger.exception("质量飞书事件处理器异常: %s", handler.__name__)
    return None


async def _get_ws_url() -> tuple[str | None, int]:
    """获取 WebSocket URL 与 service_id。"""
    if not feishu_configured():
        logger.error("质量模块飞书配置缺失，无法获取 WS URL")
        return None, 0
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            WS_ENDPOINT_URL,
            json={"AppID": QUALITY_FEISHU_APP_ID, "AppSecret": QUALITY_FEISHU_APP_SECRET},
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 0:
                url = data.get("data", {}).get("URL", "")
                q = parse_qs(urlparse(url).query)
                service_id = int(q.get("service_id", ["0"])[0])
                global _ping_interval
                cfg = data.get("data", {}).get("ClientConfig", {})
                if isinstance(cfg, dict) and cfg.get("PingInterval", 0) > 0:
                    _ping_interval = cfg["PingInterval"]
                logger.info("质量飞书 WS URL 获取成功 service_id=%s", service_id)
                return url, service_id
            logger.error("质量飞书获取 WS URL 失败: code=%s msg=%s", data.get("code"), data.get("msg"))
        else:
            logger.error("质量飞书获取 WS URL HTTP 错误: %s", resp.status_code)
    return None, 0


def _build_ping_frame(service_id: int) -> bytes:
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
    while not _stop.is_set():
        try:
            await ws.send(_build_ping_frame(service_id))
        except Exception as e:
            logger.warning("质量飞书 PING 失败: %s", e)
            return
        try:
            await asyncio.wait_for(_stop.wait(), timeout=_ping_interval)
            return
        except TimeoutError:
            pass


async def _handle_binary_message(ws, message: bytes) -> None:
    from lark_oapi.ws.client import _get_by_key
    from lark_oapi.ws.const import HEADER_BIZ_RT, HEADER_TYPE
    from lark_oapi.ws.enum import FrameType, MessageType
    from lark_oapi.ws.pb.pbbp2_pb2 import Frame

    try:
        frame = Frame()
        frame.ParseFromString(message)
        ft = FrameType(frame.method)
        if ft == FrameType.CONTROL:
            return
        if ft == FrameType.DATA:
            type_val = _get_by_key(frame.headers, HEADER_TYPE)
            msg_type = MessageType(type_val)
            if msg_type != MessageType.EVENT:
                return
            event = json.loads(frame.payload.decode("utf-8"))
            event_type = event.get("header", {}).get("event_type", "")
            logger.info("📨 质量飞书收到事件: %s", event_type)
            start_ms = int(round(time.time() * 1000))
            if event_type == "card.action.trigger":
                # 卡片回调必须 3 秒内同步返回响应（可带 base64 卡片更新，无更新返回 {"code": 200}）
                try:
                    card_resp = await asyncio.wait_for(_dispatch(event_type, event), timeout=2.9)
                except TimeoutError:
                    logger.warning("质量飞书卡片回调超时，返回通用响应")
                    card_resp = None
                if card_resp and isinstance(card_resp, dict):
                    import base64 as _b64
                    card_json = json.dumps(card_resp, ensure_ascii=False)
                    resp = {"code": 200, "data": _b64.b64encode(card_json.encode("utf-8")).decode("ascii")}
                else:
                    resp = {"code": 200}
                frame.payload = json.dumps(resp, ensure_ascii=False).encode("utf-8")
            else:
                # 其他事件异步分发，立即 ACK（飞书要求 3 秒内回复）
                asyncio.create_task(_dispatch(event_type, event))
                frame.payload = json.dumps({"code": 200}, ensure_ascii=False).encode("utf-8")
            # 回复 ACK：biz_rt 为本地处理耗时（照 safety 实现，不读入站帧 header）
            end_ms = int(round(time.time() * 1000))
            header = frame.headers.add()
            header.key = HEADER_BIZ_RT
            header.value = str(end_ms - start_ms)
            await ws.send(frame.SerializeToString())
    except Exception:
        logger.exception("质量飞书帧处理异常")


async def _run_ws() -> None:
    while not _stop.is_set():
        url, service_id = await _get_ws_url()
        if not url:
            await asyncio.sleep(10)
            continue
        try:
            async with websockets.connect(url, ssl=True, ping_interval=None) as ws:
                logger.info("质量飞书 WS 已连接 service_id=%s", service_id)
                ping_task = asyncio.create_task(_ping_loop(ws, service_id))
                try:
                    async for message in ws:
                        if isinstance(message, bytes):
                            await _handle_binary_message(ws, message)
                finally:
                    ping_task.cancel()
        except Exception as e:
            logger.warning("质量飞书 WS 断开: %s，10s 后重连", e)
        await asyncio.sleep(10)


async def start_ws() -> None:
    global _stop, _ws_task
    if _ws_task and not _ws_task.done():
        return
    _stop = asyncio.Event()
    _ws_task = asyncio.create_task(_run_ws())


async def stop_ws() -> None:
    global _stop, _ws_task
    if _stop:
        _stop.set()
    if _ws_task:
        _ws_task.cancel()
        try:
            await _ws_task
        except asyncio.CancelledError:
            pass
        _ws_task = None
