"""安全模块专属飞书事件订阅客户端（WebSocket 长连接模式）。

使用安全模块独立的飞书应用凭证，与全局飞书事件订阅完全隔离。
基于原生 WebSocket + protobuf 协议，参照设备模块成熟实现。
"""

import asyncio
import importlib
import json
import logging
import ssl
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import websockets

from app.modules.safety.feishu.client import (
    SAFETY_FEISHU_APP_ID,
    SAFETY_FEISHU_APP_SECRET,
)

logger = logging.getLogger(__name__)

# 事件类型 → 处理器列表
_handlers: dict[str, list] = {}
_stop: asyncio.Event | None = None
_ws_task: asyncio.Task | None = None

# 长连接重连：与设备模块一致，不设置重试上限，持续重连直到显式 stop
# 连接失败/断连后等待 10s 重试，由无限 while 循环驱动

# 飞书 endpoint
FEISHU_DOMAIN = "https://open.feishu.cn"
WS_ENDPOINT_URL = f"{FEISHU_DOMAIN}/callback/ws/endpoint"

# protobuf PING 间隔（秒），由服务端下发 ClientConfig.PingInterval 覆盖
_ping_interval: int = 120


def on_event(event_type: str):
    """装饰器：注册安全模块事件处理器。"""
    def decorator(func):
        _handlers.setdefault(event_type, []).append(func)
        logger.info("注册安全飞书事件: type=%s handler=%s", event_type, func.__name__)
        return func
    return decorator


# ── handler 失败重试与告警 ──
# 此前 _dispatch 对 handler 异常只 logger.exception（无重试、无告警），调度任务
# 有失败告警而事件链路没有，失败即静默丢事件。现加：有界重试（退避 1s/2s，
# 共 3 次尝试）→ 重试耗尽后节流告警管理员（同 handler 1 小时最多 1 条，事件
# 失败频率远高于调度任务，防刷屏）。
_HANDLER_RETRIES = 2
_RETRY_BACKOFF = (1.0, 2.0)
_ALERT_THROTTLE_SECONDS = 3600.0
_alert_throttled_at: dict[str, float] = {}


async def _alert_handler_failure(event_type: str, handler_name: str) -> None:
    """handler 重试耗尽后 DM 告警管理员（进程内节流，发送失败不抛）。"""
    now = time.monotonic()
    key = f"{event_type}:{handler_name}"
    if now - _alert_throttled_at.get(key, 0.0) < _ALERT_THROTTLE_SECONDS:
        return
    _alert_throttled_at[key] = now
    try:
        # 延迟 import：scheduler 顶层依赖链重，且反向依赖 event_client 的模块众多
        from app.modules.safety.scheduler import ALERT_NOTIFY_OPEN_ID
        from app.modules.safety.feishu.notification import send_user_card

        ok = await send_user_card(
            open_id=ALERT_NOTIFY_OPEN_ID,
            title="⚠️ 飞书事件处理失败告警",
            content=(
                f"**{handler_name}** 处理事件 **{event_type}** 失败\n"
                f"已重试 {_HANDLER_RETRIES + 1} 次仍未成功，本次事件丢弃。\n"
                f"时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"同类型失败 1 小时内只告警一次；若持续失败，"
                f"数据由每日定时全量/差异同步兜底补齐，请检查服务日志定位根因。"
            ),
        )
        if ok:
            logger.warning("已发送事件失败告警: type=%s handler=%s", event_type, handler_name)
        else:
            logger.warning("事件失败告警发送失败(返回False): type=%s handler=%s", event_type, handler_name)
    except Exception:  # noqa: BLE001
        logger.exception("事件失败告警发送异常: type=%s handler=%s", event_type, handler_name)


async def _dispatch(event_type: str, event_data: dict[str, Any]) -> Any:
    """分发事件给注册的处理器，返回第一个处理器的返回值。

    card.action.trigger 不重试：外层等待 2.9s 卡片响应，重试会重复更新卡片状态。
    """
    handlers = _handlers.get(event_type, [])
    if handlers:
        logger.info("分发安全飞书事件: type=%s", event_type)
        result = None
        allow_retry = event_type != "card.action.trigger"
        for handler in handlers:
            attempts = (1 + _HANDLER_RETRIES) if allow_retry else 1
            for attempt in range(1, attempts + 1):
                try:
                    result = await handler(event_data)
                    break
                except Exception:
                    if attempt >= attempts:
                        logger.exception(
                            "事件处理器重试耗尽: %s (type=%s, 共 %d 次尝试)",
                            handler.__name__, event_type, attempt,
                        )
                        await _alert_handler_failure(event_type, handler.__name__)
                    else:
                        logger.warning(
                            "事件处理器异常(第 %d/%d 次尝试，将重试): %s",
                            attempt, attempts, handler.__name__,
                            exc_info=True,
                        )
                        await asyncio.sleep(_RETRY_BACKOFF[attempt - 1])
        return result
    logger.warning(
        "安全飞书未注册的 event_type=%s (data_keys=%s)，请检查是否已添加 @on_event 处理器",
        event_type, list(event_data.keys())[:10],
    )
    return None


async def _get_ws_url_and_config() -> tuple[str | None, int]:
    """获取 WebSocket URL 并解析 service_id + PingInterval。

    返回 (url, service_id)。
    """
    if not SAFETY_FEISHU_APP_ID or not SAFETY_FEISHU_APP_SECRET:
        logger.error("安全模块飞书配置缺失，无法获取 WebSocket URL")
        return None, 0

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            WS_ENDPOINT_URL,
            json={"AppID": SAFETY_FEISHU_APP_ID, "AppSecret": SAFETY_FEISHU_APP_SECRET},
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
                    "安全飞书 WS URL 获取成功, service_id=%s, ping_interval=%s",
                    service_id, _ping_interval,
                )
                return url, service_id
            logger.error(
                "安全飞书获取 WS URL 失败: code=%s msg=%s",
                data.get("code"), data.get("msg"),
            )
        else:
            logger.error("安全飞书获取 WS URL HTTP 错误: %s", resp.status_code)
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
    return frame.SerializeToString()


def _build_ack_frame(frame, biz_rt: int) -> bytes:
    """构建 DATA 帧的 ACK 回复（飞书协议要求收到事件后必须回复 ACK）。

    注意：不覆盖 frame.payload —— 调用方（如 card.action.trigger 处理）可能
    已经将卡片更新内容写入 payload，覆盖会导致按钮状态无法变更。
    """
    from lark_oapi.ws.const import HEADER_BIZ_RT

    header = frame.headers.add()
    header.key = HEADER_BIZ_RT
    header.value = str(biz_rt)

    return frame.SerializeToString()


# ── 合包（multi-frame segmentation）──
# 飞书在事件 payload 超单帧上限时，会把一个逻辑事件拆成 sum 个帧，
# 每帧带 message_id / sum / seq 头。自定义 client 曾对每个片段直接
# json.loads，导致大事件（长记录）必然解析失败 → 平台同步静默失效。
# 此处参照 lark_oapi ws client._combine：按 message_id 缓冲片段，收齐才合并。
_SEGMENT_TTL = 5.0  # 与 lark_oapi 一致：片段缓冲 TTL（秒）
_segment_buffers: dict[str, list[bytes]] = {}
_segment_stamps: dict[str, float] = {}


def _header_value(headers, key: str, default: str) -> str:
    """读取帧 header 值，缺失时返回 default（不抛异常）。

    lark_oapi 的 _get_by_key 缺失时抛 HeaderNotFoundException，这里用安全读取。
    """
    for header in headers:
        if header.key == key:
            return header.value
    return default


def _assemble_segmented_payload(headers, payload: bytes) -> bytes | None:
    """处理飞书合包：sum<=1 原样返回；sum>1 按 message_id 缓冲片段，收齐返回拼接。

    返回 None 表示分段尚未收齐 —— 调用方应跳过本次帧（不解析、不分发、不发 ACK）。
    """
    from lark_oapi.ws.const import HEADER_MESSAGE_ID, HEADER_SEQ, HEADER_SUM

    sum_ = _header_value(headers, HEADER_SUM, "1")
    if int(sum_) <= 1:
        return payload

    msg_id = _header_value(headers, HEADER_MESSAGE_ID, "")
    seq = _header_value(headers, HEADER_SEQ, "0")
    if not msg_id:
        # 协议异常：分段帧却无 message_id，无法可靠关联片段，退回单帧解析
        logger.warning("安全飞书合包帧缺少 message_id，无法合包 (sum=%s)", sum_)
        return payload

    now = time.monotonic()
    # 惰性清理过期片段缓冲（5s TTL）
    for mid in list(_segment_stamps):
        if now - _segment_stamps[mid] > _SEGMENT_TTL:
            _segment_buffers.pop(mid, None)
            _segment_stamps.pop(mid, None)

    val = _segment_buffers.get(msg_id)
    if val is None:
        buf = [b""] * int(sum_)
        buf[int(seq)] = payload
        _segment_buffers[msg_id] = buf
        _segment_stamps[msg_id] = now
        return None

    val[int(seq)] = payload
    _segment_stamps[msg_id] = now
    joined = b""
    for piece in val:
        if not piece:
            return None  # 还有片段未到，继续等待
        joined += piece
    # 收齐：清理缓冲并返回完整 payload
    _segment_buffers.pop(msg_id, None)
    _segment_stamps.pop(msg_id, None)
    return joined


async def _ping_loop(ws, service_id: int) -> None:
    """定期发送 protobuf PING 帧保持连接和事件路由。"""
    while not _stop.is_set():
        try:
            ping_data = _build_ping_frame(service_id)
            await ws.send(ping_data)
            logger.debug("安全飞书 PING 已发送 (service_id=%s)", service_id)
        except Exception as e:
            logger.warning("安全飞书 PING 失败: %s", e)
            return
        try:
            await asyncio.wait_for(_stop.wait(), timeout=_ping_interval)
            return
        except TimeoutError:
            pass


# ── 消息处理 ──


# 帧活动计数器（用于诊断连接是否存活）
_frame_count: dict[str, int] = {"received": 0, "control": 0, "data": 0, "event": 0, "segment": 0, "error": 0}

# PONG 看门狗：记录最后一次收到 PONG 的时间，用于检测静默断连
_last_pong_at: float = 0.0  # monotonic seconds


def _get_frame_stats() -> dict:
    """返回帧活动统计。"""
    return dict(_frame_count)


async def _handle_binary_message(ws, message: bytes) -> None:
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
                    logger.debug("安全飞书 ← PONG (连接存活, 共收到 %d 帧)", _frame_count["received"])
                else:
                    logger.info("安全飞书 CONTROL 帧: %s (共 %d 帧)", msg_type, _frame_count["received"])
            except Exception:
                logger.info("安全飞书 CONTROL 帧(无 type header, 共 %d 帧)", _frame_count["received"])
            return

        if ft == FrameType.DATA:
            _frame_count["data"] += 1
            start_ms = int(round(time.time() * 1000))
            type_val = _get_by_key(frame.headers, HEADER_TYPE)
            msg_type = MessageType(type_val)

            if msg_type == MessageType.EVENT:
                # ── 合包处理：大事件被飞书拆成 sum 个帧（message_id/sum/seq 头）──
                # 未收齐时返回 None → 提前 return：不解析、不分发、不发 ACK
                payload = _assemble_segmented_payload(frame.headers, frame.payload)
                if payload is None:
                    _frame_count["segment"] += 1
                    logger.debug(
                        "安全飞书合包片段待齐，暂不解析/ACK (共 %d 帧)",
                        _frame_count["segment"],
                    )
                    return
                _frame_count["event"] += 1
                event = json.loads(payload.decode("utf-8"))
                logger.info(
                    "📨 安全飞书收到事件(完整): %s",
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
                    # Bitable 同步等耗时业务在后台执行
                    asyncio.create_task(_dispatch_event(event))
                    resp = {"code": 200}
                frame.payload = json.dumps(resp, ensure_ascii=False).encode("utf-8")
            else:
                logger.info("安全飞书 DATA 帧: type=%s (共 %d 帧)", msg_type, _frame_count["received"])

            # 发送 ACK（飞书要求 3 秒内回复，现在立即发送）
            end_ms = int(round(time.time() * 1000))
            ack_data = _build_ack_frame(frame, end_ms - start_ms)
            await ws.send(ack_data)

    except Exception as e:
        _frame_count["error"] += 1
        logger.warning("安全飞书帧处理失败 (%d bytes): %s", len(message), e)


async def start_ws() -> None:
    """启动安全模块飞书 WebSocket 连接。

    与设备交互机器人一致：无限重连模式，连接断开后自动重试，不设重试上限。
    仅当显式调用 stop_ws() 或 restart_ws() 时才会停止。
    """
    global _stop, _ws_task
    _stop = asyncio.Event()
    _ws_task = asyncio.current_task()

    if not SAFETY_FEISHU_APP_ID or not SAFETY_FEISHU_APP_SECRET:
        logger.warning(
            "安全模块飞书配置缺失（SAFETY_FEISHU_APP_ID / SAFETY_FEISHU_APP_SECRET），跳过事件订阅"
        )
        return

    logger.info(
        "启动安全模块飞书事件订阅 (app_id=%s, 无限重连模式)",
        SAFETY_FEISHU_APP_ID,
    )

    # 预热 Bitable 配置缓存（失败不阻塞订阅，store 读时回退 registry 默认）
    try:
        from app.modules.safety.bitable_config.store import store

        await store.warmup()
    except Exception:
        logger.exception("Bitable 配置缓存预热失败（不影响事件订阅）")

    # 预热 AI 配置中心缓存（失败仅告警，读路径回退 env/registry 默认）
    try:
        from app.modules.safety.ai_config.store import store as ai_config_store

        await ai_config_store.warmup()
    except Exception:
        logger.exception("AI 配置中心缓存预热失败（不影响事件订阅）")

    # 预热 AI 场景配置缓存（失败仅告警，读路径回退 registry 默认/场景默认开启）
    try:
        from app.modules.safety.ai_config.scenario_store import scenario_store

        await scenario_store.warmup()
    except Exception:
        logger.exception("AI 场景配置缓存预热失败（不影响事件订阅）")

    attempt = 0
    while not _stop.is_set():
        try:
            # 1. 获取 WebSocket URL + service_id
            ws_url, service_id = await _get_ws_url_and_config()
            if not ws_url:
                attempt += 1
                logger.error(
                    "安全飞书无法获取 WebSocket URL，第 %d 次重试，10 秒后重连",
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
                logger.info("安全飞书 WebSocket 已连接 (service_id=%s)", service_id)
                attempt = 0  # 连接成功，重置失败计数

                # 3. 订阅 Bitable 文档事件（持久订阅，每次启动重试无害）
                # 逐个导入 handler 模块触发 @on_event 注册；单个模块失败只影响
                # 对应事件类型，不得中断 WS 连接与其余订阅（此前某 handler 缺依赖
                # 曾导致整个 WS 事件链路崩溃，表现为连接后立即异常并无限重连）
                _handler_modules = [
                    "app.modules.safety.feishu.bitable_ai_handler",
                    "app.modules.safety.feishu.business_agent_bot_handler",
                    "app.modules.safety.feishu.ehs_change_bitable_handler",
                    "app.modules.safety.feishu.emergency_drill_bitable_handler",
                    "app.modules.safety.feishu.emergency_drill_collection_handler",
                    "app.modules.safety.feishu.fire_alarm_bitable_handler",
                    "app.modules.safety.feishu.hazard_identification_bitable_handler",
                    "app.modules.safety.feishu.oh_bitable_handler",
                    "app.modules.safety.feishu.contractor_admission_bitable_handler",
                    "app.modules.safety.feishu.central_alarm_bitable_handler",
                    "app.modules.safety.feishu.cert_bitable_handler",
                    "app.modules.safety.feishu.chemical_inventory_bitable_handler",
                    "app.modules.safety.feishu.chemical_inventory_daily_handler",
                    "app.modules.safety.feishu.msds_bitable_handler",
                    "app.modules.safety.feishu.msds_collection_handler",
                    "app.modules.safety.feishu.menu_handler",
                ]
                for _handler_mod in _handler_modules:
                    try:
                        importlib.import_module(_handler_mod)
                    except Exception:
                        logger.exception(
                            "事件 handler 导入失败: %s（该事件类型不可用，其余订阅不受影响）",
                            _handler_mod,
                        )
                from app.modules.safety.feishu.bitable_handler import (
                    ensure_bitable_subscribed,
                )
                from app.modules.safety.feishu.central_alarm_bitable_handler import (
                    ensure_central_alarm_bitable_subscribed,
                )
                from app.modules.safety.feishu.cert_bitable import (
                    ensure_cert_bitable_subscribed,
                )
                from app.modules.safety.feishu.chemical_inventory_bitable_handler import (
                    ensure_chemical_inventory_bitable_subscribed,
                )
                from app.modules.safety.feishu.fire_alarm_bitable_handler import (
                    ensure_fire_alarm_bitable_subscribed,
                )
                from app.modules.safety.feishu.hazard_identification_bitable_handler import (
                    ensure_hazard_id_bitable_subscribed,
                )
                from app.modules.safety.feishu.key_risk_op_bitable_handler import (
                    ensure_key_risk_op_bitable_subscribed,
                )
                from app.modules.safety.feishu.knowledge_bitable_handler import (
                    ensure_knowledge_bitable_subscribed,
                )
                from app.modules.safety.feishu.oh_bitable_handler import (
                    ensure_oh_bitable_subscribed,
                )
                from app.modules.safety.feishu.special_op_bitable_handler import (
                    ensure_special_op_bitable_subscribed,
                )
                from app.modules.safety.feishu.contractor_admission_bitable_handler import (
                    ensure_contractor_admission_bitable_subscribed,
                )
                from app.modules.safety.feishu.ehs_change_bitable_handler import (
                    ensure_ehs_change_bitable_subscribed,
                )
                from app.modules.safety.feishu.emergency_drill_bitable_handler import (
                    ensure_emergency_drill_bitable_subscribed,
                )
                from app.modules.safety.feishu.msds_bitable_handler import (
                    ensure_msds_bitable_subscribed,
                )

                subscribed = await ensure_bitable_subscribed()
                if not subscribed:
                    _subscription_ok = False
                    logger.error(
                        "⚠️ Bitable 事件订阅失败！WebSocket 已连接但不会收到任何 Bitable 事件。"
                        "请在【系统功能 → 多维表格配置】检查该域连接配置和飞书应用权限。"
                    )
                else:
                    _subscription_ok = True
                    logger.info("✅ Bitable 事件订阅就绪，WebSocket 将接收实时事件推送")

                # 知识库表格也尝试订阅（与隐患表格在不同应用中，独立订阅）
                knowledge_subscribed = await ensure_knowledge_bitable_subscribed()
                if knowledge_subscribed:
                    logger.info("✅ 知识库 Bitable 事件订阅就绪")
                else:
                    logger.info("知识库 Bitable 事件订阅未启用（可能未配置 env var）")

                # 危险源辨识自动化 Bitable — 独立表格，独立订阅
                hazard_id_subscribed = await ensure_hazard_id_bitable_subscribed()
                if hazard_id_subscribed:
                    logger.info("✅ 危险源辨识 Bitable 事件订阅就绪")
                else:
                    logger.info("危险源辨识 Bitable 事件订阅未启用（可能未配置 env var）")

                # 特殊作业日报 Bitable — 必须显式订阅文档事件，WS 才会推送变更
                # （不订阅则该文档的 drive.file.bitable_record_changed_v1 永不推送）
                special_op_subscribed = await ensure_special_op_bitable_subscribed()
                if special_op_subscribed:
                    logger.info("✅ 特殊作业日报 Bitable 文档事件订阅就绪")
                else:
                    logger.error("⚠️ 特殊作业日报 Bitable 文档事件订阅失败，实时同步将失效")

                # 相关方准入 Bitable — 必须显式订阅文档事件（drive.file.bitable_record_changed_v1）
                admission_subscribed = await ensure_contractor_admission_bitable_subscribed()
                if admission_subscribed:
                    logger.info("✅ 相关方准入 Bitable 文档事件订阅就绪")
                else:
                    logger.error("⚠️ 相关方准入 Bitable 文档事件订阅失败，实时同步将失效")

                # 关键风险作业 Bitable — 必须显式订阅文档事件，WS 才会推送变更
                key_risk_op_subscribed = await ensure_key_risk_op_bitable_subscribed()
                if key_risk_op_subscribed:
                    logger.info("✅ 关键风险作业 Bitable 文档事件订阅就绪")
                else:
                    logger.error("⚠️ 关键风险作业 Bitable 文档事件订阅失败，实时同步将失效")

                # 职业健康 OH Bitable — 单文档 5 表镜像（人员汇总/体检记录/岗位/危害因素PPE/申请）
                oh_subscribed = await ensure_oh_bitable_subscribed()
                if oh_subscribed:
                    logger.info("✅ 职业健康 Bitable 事件订阅就绪")
                else:
                    logger.info("职业健康 Bitable 事件订阅未启用（可能未配置 env var）")

                # 消防报警 Bitable — 事件驱动增量同步（仅同步数据，不触发 AI 分析）
                fire_subscribed = await ensure_fire_alarm_bitable_subscribed()
                if fire_subscribed:
                    logger.info("✅ 消防报警 Bitable 事件订阅就绪")
                else:
                    logger.info("消防报警 Bitable 事件订阅未启用（可能未配置 env var）")

                # 中控报警 Bitable — 事件驱动增量同步（15 表，仅同步数据，不触发 AI 分析）
                central_subscribed = await ensure_central_alarm_bitable_subscribed()
                if central_subscribed:
                    logger.info("✅ 中控报警 Bitable 事件订阅就绪")
                else:
                    logger.info("中控报警 Bitable 事件订阅未启用（可能未配置 env var）")

                # 危化品库存 Bitable — 总表事件驱动增量同步
                chem_inv_subscribed = await ensure_chemical_inventory_bitable_subscribed()
                if chem_inv_subscribed:
                    logger.info("✅ 危化品库存 Bitable 事件订阅就绪")
                else:
                    logger.info("危化品库存 Bitable 事件订阅未启用（可能未配置 env var）")

                # MSDS Bitable — 采集入口 + 收录台账（单 base 两表，2026-09-08
                # 自从不推送的 bitable.record.* 迁移至文档级事件）
                msds_subscribed = await ensure_msds_bitable_subscribed()
                if msds_subscribed:
                    logger.info("✅ MSDS Bitable 文档事件订阅就绪")
                else:
                    logger.error("⚠️ MSDS Bitable 文档事件订阅失败，实时同步将失效")

                # 应急演练 Bitable — 统计表 + 收录表（单 base 两表，同上迁移）
                drill_subscribed = await ensure_emergency_drill_bitable_subscribed()
                if drill_subscribed:
                    logger.info("✅ 应急演练 Bitable 文档事件订阅就绪")
                else:
                    logger.error("⚠️ 应急演练 Bitable 文档事件订阅失败，实时同步将失效")

                # EHS 变更 Bitable — 审批表 + 验收表（单 base 两表，同上迁移）
                ehs_subscribed = await ensure_ehs_change_bitable_subscribed()
                if ehs_subscribed:
                    logger.info("✅ EHS 变更 Bitable 文档事件订阅就绪")
                else:
                    logger.error("⚠️ EHS 变更 Bitable 文档事件订阅失败，实时同步将失效")

                # 持证台账 Bitable — 特种作业证 wiki + 监护人 A/B 证 base 两个文档
                # （修复现状缺口：此前 _handler_modules 未导入 cert 模块、start_ws 未订阅，
                #   3 张表的事件永远不会推送，见 backend-design §0 事实 2）
                cert_subscribed = await ensure_cert_bitable_subscribed()
                if cert_subscribed:
                    logger.info("✅ 持证台账 Bitable 事件订阅就绪")
                else:
                    logger.error("⚠️ 持证台账 Bitable 事件订阅失败，实时同步将失效")

                # 4. 启动 protobuf PING 心跳循环
                ping_task = asyncio.create_task(_ping_loop(ws, service_id))

                try:
                    # 5. 接收消息循环
                    while not _stop.is_set():
                        try:
                            message = await asyncio.wait_for(ws.recv(), timeout=180)
                        except TimeoutError:
                            # PONG 看门狗：若超过 300s 未收到 PONG，标记连接可能已僵死
                            now = asyncio.get_running_loop().time()
                            if _last_pong_at > 0 and (now - _last_pong_at) > 300:
                                logger.error(
                                    "⚠️ PONG 超时: 已 %.0fs 未收到 PONG，连接可能已僵死，将主动断开重连",
                                    now - _last_pong_at,
                                )
                                break  # 退出接收循环，触发重连
                            logger.debug("安全飞书 WS recv 超时(180s)，继续等待...")
                            continue

                        if isinstance(message, bytes):
                            await _handle_binary_message(ws, message)
                        else:
                            # 文本消息（ping/pong JSON 等，极少见）
                            try:
                                event = json.loads(message)
                                msg_type = event.get("type", "")
                                if msg_type == "ping":
                                    logger.info("安全飞书收到文本 ping，回复 pong")
                                    await ws.send(json.dumps({"type": "pong"}))
                                else:
                                    logger.info(
                                        "安全飞书收到文本事件: type=%s",
                                        msg_type or event.get("header", {}).get("event_type", "?"),
                                    )
                                    await _dispatch_event(event)
                            except json.JSONDecodeError:
                                logger.debug("安全飞书收到非 JSON 文本消息: %s", str(message)[:100])
                finally:
                    ping_task.cancel()

        except asyncio.CancelledError:
            break
        except websockets.exceptions.ConnectionClosed as e:
            attempt += 1
            logger.warning(
                "安全飞书 WebSocket 连接关闭: %s，第 %d 次重试，10 秒后重连",
                e, attempt,
            )
        except Exception:
            attempt += 1
            logger.exception(
                "安全飞书 WebSocket 异常，第 %d 次重试，10 秒后重连",
                attempt,
            )

        # 无限重连模式：等待 10s 后自动重试（除非显式 stop）
        try:
            await asyncio.wait_for(_stop.wait(), timeout=10)
        except TimeoutError:
            pass

    logger.info("安全飞书 WebSocket 客户端已停止")


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
        logger.debug("安全飞书无法确定事件类型: %s", json.dumps(event, ensure_ascii=False)[:200])
        return None


async def stop_ws() -> None:
    """停止安全模块飞书 WebSocket 连接。"""
    global _stop
    if _stop:
        _stop.set()


async def restart_ws() -> dict:
    """手动重启 WS 连接（先停止旧连接，再启动新连接）。"""
    global _stop, _ws_task

    if _stop:
        _stop.set()
    if _ws_task and not _ws_task.done():
        _ws_task.cancel()
        try:
            await _ws_task
        except asyncio.CancelledError:
            pass

    _ws_task = asyncio.create_task(start_ws())
    logger.info("安全飞书 WebSocket 已通过 restart_ws() 手动恢复")

    return {
        "status": "ok",
        "message": "安全飞书 WebSocket 连接已重新启动",
        "registered_events": list(_handlers.keys()),
    }


# 订阅状态（由 start_ws 在连接成功后设置）
_subscription_ok: bool = False


async def get_ws_status() -> dict:
    """查询当前 WS 连接状态。"""
    task_alive = _ws_task is not None and not _ws_task.done()
    pong_ago: float | None = None
    if _last_pong_at > 0:
        pong_ago = asyncio.get_running_loop().time() - _last_pong_at
    return {
        "connected": task_alive,
        "subscription_ok": _subscription_ok,
        "registered_events": list(_handlers.keys()),
        "mode": "unlimited",  # 无限重连模式，与设备交互机器人一致
        "frame_stats": _get_frame_stats(),
        "last_pong_seconds_ago": round(pong_ago, 1) if pong_ago is not None else None,
        "pong_watchdog_healthy": pong_ago is not None and pong_ago < 300 if pong_ago is not None else None,
    }
