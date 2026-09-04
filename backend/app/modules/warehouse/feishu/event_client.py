"""仓储模块专属飞书事件订阅客户端（WebSocket 长连接模式）。

使用仓储模块独立的飞书应用凭证（仓库管理机器人），与全局飞书事件订阅、
安全模块事件订阅完全隔离。基于原生 WebSocket + protobuf 协议，
照搬 safety/feishu/event_client.py 成熟模式——lark_oapi SDK 的 WS 客户端
使用模块级全局 loop 单实例（不支持多应用并行），本模块独立实现绕开该限制。
"""

import asyncio
import json
import logging
import ssl
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import websockets

from app.modules.warehouse.feishu.client import (
    get_warehouse_feishu_app_id,
    get_warehouse_feishu_app_secret,
)

logger = logging.getLogger(__name__)

# 事件处理器类型：接收 event dict；返回值仅 card.action.trigger 有意义（卡片更新 dict）
Handler = Callable[[dict[str, Any]], Any]

# 事件类型 → 处理器列表
_handlers: dict[str, list[Handler]] = {}
_stop: asyncio.Event | None = None

# 长连接重连：与 safety 模块一致，不设置重试上限，持续重连直到显式 stop
# 连接失败/断连后等待 10s 重试，由无限 while 循环驱动

# 飞书 endpoint
FEISHU_DOMAIN = "https://open.feishu.cn"
WS_ENDPOINT_URL = f"{FEISHU_DOMAIN}/callback/ws/endpoint"

# protobuf PING 间隔（秒），由服务端下发 ClientConfig.PingInterval 覆盖
_ping_interval: int = 120


def on_event(event_type: str) -> Callable[[Handler], Handler]:
    """装饰器：注册仓储模块事件处理器。"""
    def decorator(func: Handler) -> Handler:
        _handlers.setdefault(event_type, []).append(func)
        logger.info("注册仓库飞书事件: type=%s handler=%s", event_type, func.__name__)
        return func
    return decorator


async def _dispatch(event_type: str, event_data: dict[str, Any]) -> Any:
    """分发事件给注册的处理器，返回第一个处理器的返回值。"""
    handlers = _handlers.get(event_type, [])
    if handlers:
        logger.info("分发仓库飞书事件: type=%s", event_type)
        result = None
        for handler in handlers:
            try:
                result = await handler(event_data)
            except Exception:
                logger.exception("事件处理器异常: %s", handler.__name__)
        return result
    logger.warning(
        "仓库飞书事件未注册 event_type=%s (data_keys=%s)，请检查是否已添加 @on_event 处理器",
        event_type, list(event_data.keys())[:10],
    )
    return None


async def _get_ws_url_and_config() -> tuple[str | None, int]:
    """获取 WebSocket URL 并解析 service_id + PingInterval。

    返回 (url, service_id)。
    """
    app_id = get_warehouse_feishu_app_id()
    app_secret = get_warehouse_feishu_app_secret()
    if not app_id or not app_secret:
        logger.error("仓储模块飞书配置缺失，无法获取 WebSocket URL")
        return None, 0

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
                service_id_str = q.get("service_id", ["0"])[0]
                service_id = int(service_id_str) if service_id_str else 0
                # 读取服务端下发的 ping 间隔配置
                global _ping_interval
                client_config = data.get("data", {}).get("ClientConfig", {})
                if isinstance(client_config, dict):
                    interval = client_config.get("PingInterval", 0)
                    if interval > 0:
                        _ping_interval = interval
                logger.info(
                    "仓库飞书事件 WS URL 获取成功, service_id=%s, ping_interval=%s",
                    service_id, _ping_interval,
                )
                return url, service_id
            logger.error(
                "仓库飞书事件获取 WS URL 失败: code=%s msg=%s",
                data.get("code"), data.get("msg"),
            )
        else:
            logger.error("仓库飞书事件获取 WS URL HTTP 错误: %s", resp.status_code)
    return None, 0


# ── protobuf 帧构建 ──


def _build_ping_frame(service_id: int) -> bytes:
    """构建 protobuf PING 帧（携带 service_id，飞书据此路由事件）。"""
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
    ping_data: bytes = frame.SerializeToString()
    return ping_data


def _build_ack_frame(frame: Any, biz_rt: int) -> bytes:
    """构建 DATA 帧的 ACK 回复（飞书协议要求收到事件后必须回复 ACK）。

    注意：不覆盖 frame.payload —— 调用方（card.action.trigger 处理）可能
    已经将卡片更新内容写入 payload，覆盖会导致按钮状态无法变更。
    """
    from lark_oapi.ws.const import HEADER_BIZ_RT

    header = frame.headers.add()
    header.key = HEADER_BIZ_RT
    header.value = str(biz_rt)

    ack_data: bytes = frame.SerializeToString()
    return ack_data


async def _ping_loop(ws: Any, service_id: int) -> None:
    """定期发送 protobuf PING 帧保持连接和事件路由。"""
    stop = _stop
    if stop is None:
        return
    while not stop.is_set():
        try:
            ping_data = _build_ping_frame(service_id)
            await ws.send(ping_data)
            logger.debug("仓库飞书事件 PING 已发送 (service_id=%s)", service_id)
        except Exception as e:
            logger.warning("仓库飞书事件 PING 失败: %s", e)
            return
        try:
            await asyncio.wait_for(stop.wait(), timeout=_ping_interval)
            return
        except TimeoutError:
            pass


# ── 消息处理 ──


# 帧活动计数器（用于诊断连接是否存活）
_frame_count: dict[str, int] = {"received": 0, "control": 0, "data": 0, "event": 0, "error": 0}

# PONG 看门狗：记录最后一次收到 PONG 的时间，用于检测静默断连
_last_pong_at: float = 0.0  # monotonic seconds


async def _handle_binary_message(ws: Any, message: bytes) -> None:
    """处理 protobuf 帧（区分 CONTROL 和 DATA）。"""
    _frame_count["received"] += 1
    try:
        from lark_oapi.ws.client import _get_by_key
        from lark_oapi.ws.const import HEADER_TYPE
        from lark_oapi.ws.enum import FrameType, MessageType
        from lark_oapi.ws.pb.pbbp2_pb2 import Frame

        frame = Frame()
        frame.ParseFromString(message)

        ft = FrameType(frame.method)

        if ft == FrameType.CONTROL:
            _frame_count["control"] += 1
            try:
                type_val = _get_by_key(frame.headers, HEADER_TYPE)
                msg_type = MessageType(type_val)
                if msg_type == MessageType.PONG:
                    _last_pong_at = asyncio.get_running_loop().time()
                    logger.debug(
                        "仓库飞书事件 ← PONG (连接存活, 共收到 %d 帧)",
                        _frame_count["received"],
                    )
                else:
                    logger.info(
                        "仓库飞书事件 CONTROL 帧: %s (共 %d 帧)",
                        msg_type, _frame_count["received"],
                    )
            except Exception:
                logger.info(
                    "仓库飞书事件 CONTROL 帧(无 type header, 共 %d 帧)",
                    _frame_count["received"],
                )
            return

        if ft == FrameType.DATA:
            _frame_count["data"] += 1
            start_ms = int(round(time.time() * 1000))
            type_val = _get_by_key(frame.headers, HEADER_TYPE)
            msg_type = MessageType(type_val)

            if msg_type == MessageType.EVENT:
                _frame_count["event"] += 1
                event = json.loads(frame.payload.decode("utf-8"))
                logger.info(
                    "📨 仓库飞书事件收到(完整): %s",
                    json.dumps(event, ensure_ascii=False)[:800],
                )
                # ── card.action.trigger 必须同步返回卡片更新 ──
                event_type = event.get("header", {}).get("event_type", "")
                if event_type == "card.action.trigger":
                    try:
                        card_resp = await asyncio.wait_for(
                            _dispatch_event(event), timeout=2.9,
                        )
                    except TimeoutError:
                        logger.warning("卡片操作超时，返回通用 ACK")
                        card_resp = None
                    # ── 构建飞书 WS 协议要求的 Response 信封 ──
                    # lark_oapi 格式：{"code": 200, "data": "<base64 编码的卡片更新 JSON>"}
                    # 卡片内容必须 base64 编码后放在 data 字段，不能直接作为 payload
                    if card_resp and isinstance(card_resp, dict):
                        import base64 as _b64
                        card_json = json.dumps(card_resp, ensure_ascii=False)
                        resp = {
                            "code": 200,
                            "data": _b64.b64encode(card_json.encode("utf-8")).decode("ascii"),
                        }
                    else:
                        resp = {"code": 200}
                else:
                    # 异步分发事件，不阻塞 ACK（飞书要求 3 秒内回复）
                    asyncio.create_task(_dispatch_event(event))
                    resp = {"code": 200}
                frame.payload = json.dumps(resp, ensure_ascii=False).encode("utf-8")
            else:
                logger.info(
                    "仓库飞书事件 DATA 帧: type=%s (共 %d 帧)",
                    msg_type, _frame_count["received"],
                )

            # 发送 ACK（飞书要求 3 秒内回复，现在立即发送）
            end_ms = int(round(time.time() * 1000))
            ack_data = _build_ack_frame(frame, end_ms - start_ms)
            await ws.send(ack_data)

    except Exception as e:
        _frame_count["error"] += 1
        logger.warning("仓库飞书事件帧处理失败 (%d bytes): %s", len(message), e)


async def start_ws() -> None:
    """启动仓储模块飞书 WebSocket 连接。

    与 safety 模块一致：无限重连模式，连接断开后自动重试，不设重试上限。
    仅当显式调用 stop_ws() 时才会停止（main.py 按 WAREHOUSE_FEISHU_WS_ENABLED 门控）。
    """
    global _stop
    _stop = asyncio.Event()

    app_id = get_warehouse_feishu_app_id()
    app_secret = get_warehouse_feishu_app_secret()
    if not app_id or not app_secret:
        logger.warning(
            "仓储模块飞书配置缺失（WAREHOUSE_FEISHU_APP_ID / WAREHOUSE_FEISHU_APP_SECRET），"
            "跳过事件订阅"
        )
        return

    logger.info(
        "启动仓储模块飞书事件订阅 (app_id=%s, 无限重连模式)",
        app_id,
    )

    attempt = 0
    while not _stop.is_set():
        try:
            # 1. 获取 WebSocket URL + service_id
            ws_url, service_id = await _get_ws_url_and_config()
            if not ws_url:
                attempt += 1
                logger.error(
                    "仓库飞书事件无法获取 WebSocket URL，第 %d 次重试，10 秒后重连",
                    attempt,
                )
                await asyncio.sleep(10)
                continue

            # 2. 连接 WebSocket（禁用库自带 ping，使用 protobuf PING）
            ssl_context = ssl.create_default_context()
            async with websockets.connect(
                ws_url,
                ssl=ssl_context,
                max_size=2 ** 23,
                ping_interval=None,   # 禁用 WS 级 ping，使用 protobuf PING
                ping_timeout=None,
                close_timeout=5,
            ) as ws:
                logger.info("仓库飞书事件 WebSocket 已连接 (service_id=%s)", service_id)
                attempt = 0  # 连接成功，重置失败计数

                # 3. 启动 protobuf PING 心跳循环
                ping_task = asyncio.create_task(_ping_loop(ws, service_id))

                try:
                    # 4. 接收消息循环
                    while not _stop.is_set():
                        try:
                            message = await asyncio.wait_for(ws.recv(), timeout=180)
                        except TimeoutError:
                            # PONG 看门狗：若超过 300s 未收到 PONG，标记连接可能已僵死
                            now = asyncio.get_running_loop().time()
                            if _last_pong_at > 0 and (now - _last_pong_at) > 300:
                                logger.error(
                                    "⚠️ PONG 超时: 已 %.0fs 未收到 PONG，连接可能已僵死，"
                                    "将主动断开重连",
                                    now - _last_pong_at,
                                )
                                break  # 退出接收循环，触发重连
                            logger.debug("仓库飞书事件 WS recv 超时(180s)，继续等待...")
                            continue

                        if isinstance(message, bytes):
                            await _handle_binary_message(ws, message)
                        else:
                            # 文本消息（ping/pong JSON 等，极少见）
                            try:
                                event = json.loads(message)
                                msg_type = event.get("type", "")
                                if msg_type == "ping":
                                    logger.info("仓库飞书事件收到文本 ping，回复 pong")
                                    await ws.send(json.dumps({"type": "pong"}))
                                else:
                                    logger.info(
                                        "仓库飞书事件收到文本事件: type=%s",
                                        msg_type or event.get("header", {}).get(
                                            "event_type", "?"
                                        ),
                                    )
                                    await _dispatch_event(event)
                            except json.JSONDecodeError:
                                logger.debug(
                                    "仓库飞书事件收到非 JSON 文本消息: %s",
                                    str(message)[:100],
                                )
                finally:
                    ping_task.cancel()

        except asyncio.CancelledError:
            break
        except websockets.exceptions.ConnectionClosed as e:
            attempt += 1
            logger.warning(
                "仓库飞书事件 WebSocket 连接关闭: %s，第 %d 次重试，10 秒后重连",
                e, attempt,
            )
        except Exception:
            attempt += 1
            logger.exception(
                "仓库飞书事件 WebSocket 异常，第 %d 次重试，10 秒后重连",
                attempt,
            )

        # 无限重连模式：等待 10s 后自动重试（除非显式 stop）
        try:
            await asyncio.wait_for(_stop.wait(), timeout=10)
        except TimeoutError:
            pass

    logger.info("仓库飞书事件 WebSocket 客户端已停止")


async def _dispatch_event(event: dict[str, Any]) -> Any:
    """解析并分发单个事件，返回处理器的返回值（用于 card 响应）。"""
    # v2 格式: {"schema": "2.0", "header": {"event_type": "..."}, "event": {...}}
    header = event.get("header", {})
    event_type = header.get("event_type", "")

    if not event_type:
        # v1 格式: {"type": "event", "event": {"type": "...", ...}}
        inner = event.get("event", {})
        event_type = inner.get("type", event.get("type", ""))

    if event_type:
        event_data = event.get("event", event)
        return await _dispatch(event_type, event_data)
    else:
        logger.debug(
            "仓库飞书事件无法确定事件类型: %s",
            json.dumps(event, ensure_ascii=False)[:200],
        )
        return None


async def stop_ws() -> None:
    """停止仓储模块飞书 WebSocket 连接。"""
    global _stop
    if _stop:
        _stop.set()
