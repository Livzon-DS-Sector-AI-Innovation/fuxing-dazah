"""设备模块飞书 WebSocket 客户端 — 原生 WebSocket 实现。

使用 raw websockets 连接飞书长连接，避免 lark-oapi SDK 的全局 loop 冲突。
完整实现飞书 WS 协议：protobuf PING 心跳 + DATA 帧 ACK 回复。
"""

import asyncio
import json
import logging
import ssl
import uuid
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

                # ⚠️ 先发送 ACK 再处理事件，避免 AI 分析耗时过长
                # 导致飞书因收不到 ACK 而重试投递
                end_ms = int(round(time.time() * 1000))
                ack_data = _build_ack_frame(frame, end_ms - start_ms)
                await ws.send(ack_data)

                await _dispatch_event(event)
            else:
                logger.info("设备机器人 DATA 帧: type=%s", msg_type)

                end_ms = int(round(time.time() * 1000))
                ack_data = _build_ack_frame(frame, end_ms - start_ms)
                await ws.send(ack_data)

    except Exception:
        logger.exception(
            "设备机器人帧处理失败 (%d bytes) — 完整调用栈:",
            len(message),
        )


async def _dispatch_event(event: dict) -> None:
    """解析事件并分发给设备模块事件处理器。"""
    try:
        header = event.get("header", {})
        event_type = header.get("event_type", "")

        if not event_type:
            inner = event.get("event", {})
            event_type = inner.get("type", event.get("type", ""))

        logger.debug("设备机器人事件: type=%s, keys=%s", event_type, list(event.keys()))

        if event_type == "im.message.receive_v1":
            event_data = event.get("event", event)
            await _handle_message_event(event_data)
        elif event_type == "card.action.trigger":
            event_data = event.get("event", event)
            await _handle_card_action_event(event_data)
        else:
            logger.info("设备机器人忽略事件: %s", event_type)
    except Exception:
        logger.exception(
            "设备机器人事件分发失败: type=%s",
            event.get("header", {}).get("event_type", "?"),
        )


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
    is_new = await redis_client.set(dedup_key, "1", ex=600, nx=True)
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


async def _handle_card_action_event(event_data: dict) -> None:
    """处理 card.action.trigger 事件（验收卡片按钮点击）。

    直接在 ws_client 内完成验收逻辑，不委托 handler.py 避免循环 import。
    """
    logger.info(
        "卡片事件原始数据: %s",
        json.dumps(event_data, ensure_ascii=False)[:800],
    )
    try:
        # 1. 提取用户信息
        operator = event_data.get("operator", {})
        open_id = operator.get("open_id", "")
        user_id = operator.get("user_id", "")

        # 2. 解析 action value（双重 JSON 编码）
        action = event_data.get("action", {})
        raw_value = action.get("value", "")
        payload = {}
        try:
            inner = json.loads(raw_value)
            payload = json.loads(inner) if isinstance(inner, str) else inner
        except (json.JSONDecodeError, TypeError):
            logger.warning("无法解析 action value: %s", repr(raw_value)[:300])
            return

        act = payload.get("action", "")
        wo_id = payload.get("work_order_id", "")
        result = payload.get("result", "")
        logger.info("卡片解析: act=%s, wo=%s, result=%s", act, wo_id, result)

        if act != "verify" or not wo_id or result not in ("合格", "不合格"):
            logger.warning("无效的卡片 payload: %s", payload)
            return

        # 3. 卡片事件去重（防止飞书重试导致重复处理）
        open_message_id = (
            event_data.get("context", {}).get("open_message_id", "")
        )
        from app.core.redis import redis_client

        dedup_key = f"feishu:card:{wo_id}:{result}"
        if open_message_id:
            dedup_key = f"feishu:card:{open_message_id}:{result}"
        is_new = await redis_client.set(dedup_key, "1", ex=300, nx=True)
        if not is_new:
            logger.info("重复卡片事件已忽略: wo=%s, result=%s", wo_id, result)
            return

        # 4. 查找用户 → 执行验收
        from sqlalchemy import select as sa_select

        from app.core.database import async_session_factory
        from app.modules.equipment import repository as repo
        from app.modules.equipment.deps import EquipmentAccessContext
        from app.modules.equipment.feishu.notification import send_user_card
        from app.modules.equipment.schemas import WorkOrderVerify
        from app.modules.equipment.service.work_order import verify_work_order
        from app.platform.identity.models import User

        async with async_session_factory() as db:
            user = None
            if user_id:
                row = await db.execute(
                    sa_select(User).where(
                        User.feishu_user_id == user_id,
                        User.is_deleted == False,  # noqa: E712
                    )
                )
                user = row.scalar_one_or_none()

            if not user:
                await send_user_card(
                    open_id=open_id,
                    title="❌ 未找到用户",
                    receive_id_type="open_id",
                    content="未找到与您的飞书账号关联的系统用户。",
                )
                return

            wo = await repo.get_work_order_by_id(db, uuid.UUID(wo_id))
            if not wo:
                await send_user_card(
                    open_id=open_id,
                    title="❌ 工单不存在",
                    receive_id_type="open_id",
                    content="工单不存在或已删除。",
                )
                return

            if wo.status != "待验收":
                await send_user_card(
                    open_id=open_id,
                    title="⚠️ 无法验收",
                    receive_id_type="open_id",
                    content=f"工单 **{wo.work_order_no}** 当前为「{wo.status}」，"
                            "只有「待验收」才可操作。",
                )
                return

            label = "验收通过" if result == "合格" else "退回"
            verify_data = WorkOrderVerify(
                result=result,  # type: ignore[arg-type]
                remark=f"通过飞书卡片{label}",
            )
            try:
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

        # 5. 更新原卡片：去掉按钮，显示结果
        if open_message_id:
            emoji = "✅" if result == "合格" else "↩️"
            updated_card = {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"{emoji} 已{label} - {wo.work_order_no}",
                    },
                    "template": "green" if result == "合格" else "red",
                },
                "elements": [
                    {"tag": "markdown", "content": "此工单已处理完毕。"},
                ],
            }
            try:
                from lark_oapi.api.im.v1 import (
                    PatchMessageRequest,
                    PatchMessageRequestBody,
                )

                from app.modules.equipment.feishu.client import (
                    get_equipment_feishu_client,
                    get_equipment_tenant_token,
                )

                client = await get_equipment_feishu_client()
                token = await get_equipment_tenant_token(client)
                req = (
                    PatchMessageRequest.builder()
                    .message_id(open_message_id)
                    .request_body(
                        PatchMessageRequestBody.builder()
                        .content(json.dumps(updated_card, ensure_ascii=False))
                        .build()
                    )
                    .build()
                )
                req.headers["Authorization"] = f"Bearer {token}"
                resp = await client.im.v1.message.apatch(req)
                if resp.success():
                    logger.info("卡片已更新: msg=%s", open_message_id)
                else:
                    logger.warning(
                        "卡片更新失败: msg=%s, code=%s, msg=%s",
                        open_message_id, resp.code, resp.msg,
                    )
            except Exception:
                logger.exception("更新卡片消息失败")

    except Exception:
        logger.exception("处理卡片事件失败")


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

    # ── 0. 选择状态检查（数字输入匹配任务/工单列表）──
    from app.modules.equipment.service.inspection_session import (
        clear_selection,
        get_selection,
        get_session,
    )

    selection = await get_selection(open_id)
    if selection:
        if text in ("取消", "放弃", "cancel"):
            await clear_selection(open_id)
            from app.modules.equipment.feishu.notification import send_user_card
            await send_user_card(
                open_id=open_id, title="💡 提示",
                receive_id_type="open_id",
                content="已取消选择。",
            )
            return
        try:
            num = int(text)
            options = selection.get("options", [])
            opt = next((o for o in options if o.get("index") == num), None)
            if opt:
                select_type = selection.get("select_type", "")
                if select_type == "inspection":
                    # 不在这里 clear_selection — 让 process_feishu_text 自行处理
                    from app.modules.equipment.service.inspection_feishu import (
                        process_feishu_text,
                    )
                    await process_feishu_text(open_id, str(num), user_id=user_id)
                elif select_type == "work_order":
                    wo_no = opt.get("work_order_no", "")
                    wo_status = opt.get("status", "")
                    from app.modules.equipment.feishu.notification import send_user_card
                    if wo_status == "执行中":
                        await send_user_card(
                            open_id=open_id,
                            title=f"📋 工单 {wo_no}",
                            receive_id_type="open_id",
                            content=(
                                f"**{wo_no}** · {opt.get('order_type', '')}\n"
                                f"设备：{opt.get('equipment_name', '')}\n"
                                f"状态：{wo_status}\n\n"
                                f"发送「完成 {opt['index']} 描述」提交完成。"
                            ),
                        )
                    else:
                        await send_user_card(
                            open_id=open_id,
                            title=f"📋 工单 {wo_no}",
                            receive_id_type="open_id",
                            content=(
                                f"**{wo_no}** · {opt.get('order_type', '')}\n"
                                f"设备：{opt.get('equipment_name', '')}\n"
                                f"状态：{wo_status}"
                            ),
                        )
                return
        except ValueError:
            pass
        await send_user_card(
            open_id=open_id, title="💡 提示",
            receive_id_type="open_id",
            content="请输入有效数字选择，或回复「取消」放弃。",
        )
        return

    # ── 1. 巡检路由 ──
    _INSPECTION_COMMANDS = {
        "开始", "开始巡检", "start",
        "提交", "确认", "确认提交", "submit", "ok", "好的",
        "跳过", "skip", "pass",
        "进度", "状态", "progress", "status",
        "继续", "下一台", "下一个", "next", "continue",
        "取消", "放弃", "取消提交", "cancel", "abort",
        "退出", "返回", "exit", "quit", "back",
        "帮助", "help", "?", "？",
        "修改", "修正",
    }

    session = await get_session(open_id)
    is_inspection_cmd = text in _INSPECTION_COMMANDS or text.startswith("修改") or text.startswith("修正")

    if session or is_inspection_cmd:
        from app.modules.equipment.service.inspection_feishu import (
            process_feishu_text,
        )
        await process_feishu_text(open_id, text, user_id=user_id)
        return

    # ── 2. 工单等功能 ──
    from app.modules.equipment.feishu.notification import send_user_card

    if text in ("帮助", "help", "?", "？"):
        await send_user_card(
            open_id=open_id,
            title="🤖 设备助手使用说明",
            receive_id_type="open_id",
            content=(
                "**巡检功能**\n"
                "发送巡检照片可直接 AI 分析。\n"
                "发送「开始」进入逐台引导巡检。\n\n"
                "**工单功能**\n"
                "发送「工单」或「我的工单」查看工单列表\n"
                "发送「完成 工单号」提交完成执行中的工单\n"
                "发送「完成 序号 描述」也可按序号完成\n\n"
                "**示例**\n"
                "`完成 WO-20260615-0001`\n"
                "`完成 1 更换了密封圈`"
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
                open_id=open_id, title="💡 提示",
                receive_id_type="open_id",
                content="请输入工单号或序号，例如：`完成 WO-20260615-0001` 或 `完成 1`",
            )
            return

        parts = rest.split(" ", 1)
        first_arg = parts[0]
        detail = parts[1] if len(parts) > 1 else None

        # 尝试解析为数字索引（需要从 selection 缓存获取）
        try:
            idx = int(first_arg)
            # 查找缓存的工单列表
            wo_selection = await get_selection(open_id)
            if wo_selection and wo_selection.get("select_type") == "work_order":
                opts = wo_selection.get("options", [])
                match = next((o for o in opts if o.get("index") == idx), None)
                if match:
                    first_arg = match.get("work_order_no", first_arg)
        except ValueError:
            pass

        from app.modules.equipment.service.work_order_feishu import (
            complete_work_order_by_no,
        )
        await complete_work_order_by_no(
            user_id=user_id, open_id=open_id,
            work_order_no=first_arg, repair_detail=detail,
        )
    else:
        await send_user_card(
            open_id=open_id,
            title="💡 提示",
            receive_id_type="open_id",
            content=(
                "发送巡检照片可直接 AI 分析。\n"
                "发送「开始」进入逐台引导巡检。\n"
                "发送「工单」查看您的工单。\n"
                "发送「帮助」查看完整使用说明。"
            ),
        )


async def stop_equipment_ws() -> None:
    """停止设备模块 WebSocket 连接。"""
    global _stop
    if _stop:
        _stop.set()
