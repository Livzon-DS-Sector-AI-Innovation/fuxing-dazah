"""S1 ticket 01 验收：warehouse WS 事件客户端 + 发送通道（live + dry-run 单测）。

live 测试打真实飞书 endpoint（仓库管理机器人 cli_aaa0eaf293fa5be0 独立凭证）：
- `_get_ws_url_and_config()` 返回非空 wss URL + 服务端下发的 ping 间隔；
- websockets 真实握手 open（收消息留人工冒烟，步骤见 ticket 01 Comments）。

单测（不发网络请求）：
- notification dry_run：payload 构建（msg_type=interactive / content JSON 结构）
  与 dry_run=True 时不触碰 HTTP；
- on_event 注册 + _dispatch 分发（正常 / 处理器异常不中断 / 未知事件 warning）；
- _dispatch_event v2 信封解包、card.action.trigger ACK（真 protobuf 帧往返，
  lark_oapi Frame 序列化，与 safety 生产路径同协议）。

运行：cd "E:\\dazah(仓储)\\backend" &&
      DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/dazah_whdev"
      uv run pytest tests/modules/warehouse/test_live_ws_client.py -v
"""

from __future__ import annotations

import asyncio
import base64
import json
import ssl
from collections.abc import Iterator
from typing import Any

import pytest
import websockets
from lark_oapi.ws.pb.pbbp2_pb2 import Frame
from websockets.protocol import State

from app.modules.warehouse.feishu import event_client, notification

# ── fixtures ──


@pytest.fixture
def clean_handlers() -> Iterator[None]:
    """隔离 event_client._handlers：测试结束后移除本测试新注册的键。"""
    before = set(event_client._handlers)
    yield
    for key in set(event_client._handlers) - before:
        event_client._handlers.pop(key, None)


class _FakeWS:
    """捕获 send 的假 WS 连接（ACK 帧断言用）。"""

    def __init__(self) -> None:
        self.sent: list[bytes] = []

    async def send(self, data: bytes) -> None:
        self.sent.append(data)


def _build_event_frame(event: dict[str, Any], service_id: int = 1) -> bytes:
    """构建 lark_oapi EVENT DATA 帧（与飞书服务端下发同构，protobuf 序列化）。"""
    from lark_oapi.ws.const import HEADER_TYPE
    from lark_oapi.ws.enum import FrameType, MessageType

    frame = Frame()
    header = frame.headers.add()
    header.key = HEADER_TYPE
    header.value = MessageType.EVENT.value  # str "event"
    frame.service = service_id
    frame.method = FrameType.DATA.value  # int 1
    frame.SeqID = 1  # protobuf required 字段（与服务端帧一致）
    frame.LogID = 1
    frame.payload = json.dumps(event, ensure_ascii=False).encode("utf-8")
    return frame.SerializeToString()


def _sample_card() -> dict[str, Any]:
    """典型 Agent 结果卡片（msg_type=interactive 的 content 结构）。"""
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "库存查询结果"},
            "template": "blue",
        },
        "elements": [{"tag": "markdown", "content": "**硫酸** 批号 A1，数量 100 kg"}],
    }


# ── live：WS endpoint 与握手（真实凭证）──


async def test_live_get_ws_url_and_config() -> None:
    """真实调用 endpoint 接口：返回非空 wss URL + 合理 ping 间隔。"""
    url, service_id = await event_client._get_ws_url_and_config()
    assert url, "endpoint 未返回 URL（检查 WAREHOUSE_FEISHU_APP_ID/SECRET）"
    assert url.startswith("wss://")
    assert service_id > 0
    # 服务端下发的 ClientConfig.PingInterval（默认 120，允许服务端动态值）
    assert 30 <= event_client._ping_interval <= 600


async def test_live_ws_handshake_open() -> None:
    """websockets 真实握手成功 open（一次性 URL，收消息留给人工冒烟）。"""
    url, _service_id = await event_client._get_ws_url_and_config()
    assert url
    ssl_context = ssl.create_default_context()
    async with asyncio.timeout(30):
        async with websockets.connect(
            url,
            ssl=ssl_context,
            max_size=2**23,
            ping_interval=None,  # 禁用 WS 级 ping，使用 protobuf PING（与 safety 一致）
            ping_timeout=None,
            close_timeout=5,
        ) as ws:
            assert ws.state is State.OPEN


# ── 单测：notification payload 构建与 dry_run ──


async def test_send_card_builds_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """send_card 构建完整 payload：msg_type=interactive、content 为卡片 JSON。"""
    captured: dict[str, str] = {}

    async def fake_send(payload: dict[str, str]) -> str | None:
        captured.update(payload)
        return "om_fake_id"

    monkeypatch.setattr(notification, "_send_create", fake_send)
    card = _sample_card()
    result = await notification.send_card("oc_chat_1", card)

    assert result == "om_fake_id"
    assert captured["receive_id_type"] == "chat_id"
    assert captured["receive_id"] == "oc_chat_1"
    assert captured["msg_type"] == "interactive"
    content = json.loads(captured["content"])
    assert content == card  # content 是完整卡片 JSON 串（ensure_ascii=False 可逆）


async def test_send_text_builds_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """send_text 构建 msg_type=text、content={"text": ...} 的 payload。"""
    captured: dict[str, str] = {}

    async def fake_send(payload: dict[str, str]) -> str | None:
        captured.update(payload)
        return "om_fake_id"

    monkeypatch.setattr(notification, "_send_create", fake_send)
    result = await notification.send_text("oc_chat_1", "你好")
    assert result is True
    assert captured["receive_id_type"] == "chat_id"
    assert captured["msg_type"] == "text"
    assert json.loads(captured["content"]) == {"text": "你好"}


async def test_send_card_to_user_uses_open_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """send_card_to_user 私聊走 open_id receive_id_type。"""
    captured: dict[str, str] = {}

    async def fake_send(payload: dict[str, str]) -> str | None:
        captured.update(payload)
        return "om_fake_id"

    monkeypatch.setattr(notification, "_send_create", fake_send)
    result = await notification.send_card_to_user("ou_user_1", _sample_card())
    assert result is True
    assert captured["receive_id_type"] == "open_id"
    assert captured["receive_id"] == "ou_user_1"
    assert captured["msg_type"] == "interactive"


async def test_dry_run_skips_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """dry_run=True：三个发送函数均构建消息体但不发 HTTP，返回模拟成功。"""

    async def boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("dry_run 模式不得触发发送")

    # 双保险：内部发送与 SDK client 获取都不允许被调用
    monkeypatch.setattr(notification, "_send_create", boom)
    monkeypatch.setattr(notification, "get_warehouse_feishu_client", boom)

    card = _sample_card()
    assert await notification.send_card("oc_chat_1", card, dry_run=True) == "dry_run"
    assert await notification.send_text("oc_chat_1", "hi", dry_run=True) is True
    assert await notification.send_card_to_user("ou_user_1", card, dry_run=True) is True


async def _never_send(payload: dict[str, str]) -> str | None:
    """替身 _send_create：不触网、返回 None（无凭证语境下的“失败”语义）。"""
    return None


async def test_module_level_dry_run_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    """模块级开关：set_dry_run(True) 后未显式传参的调用走 dry_run。"""
    monkeypatch.setattr(notification, "_send_create", _never_send)
    try:
        notification.set_dry_run(True)
        assert await notification.send_card("oc_chat_1", _sample_card()) == "dry_run"
        # 显式参数覆盖模块级开关（_never_send 返回 None = 真实发送路径的失败返回值）
        assert await notification.send_card("oc_chat_1", _sample_card(), dry_run=False) is None
    finally:
        notification.set_dry_run(False)


# ── 单测：on_event 注册与 _dispatch 分发 ──


async def test_on_event_registration_and_dispatch(clean_handlers: None) -> None:
    """@on_event 注册后 _dispatch 按 event_type 分发并透传返回值。"""
    calls: list[dict[str, Any]] = []

    @event_client.on_event("wh.test.normal")
    async def handler(data: dict[str, Any]) -> str:
        calls.append(data)
        return "ok"

    result = await event_client._dispatch("wh.test.normal", {"k": "v"})
    assert result == "ok"
    assert calls == [{"k": "v"}]
    assert "wh.test.normal" in event_client._handlers


async def test_dispatch_handler_exception_does_not_break(
    clean_handlers: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """处理器抛异常：记录日志、不中断循环，后续处理器照常执行。"""
    calls: list[str] = []
    logged: list[str] = []

    def _spy_exception(msg: str, *args: Any) -> None:
        logged.append(msg % args if args else msg)

    monkeypatch.setattr(event_client.logger, "exception", _spy_exception)

    @event_client.on_event("wh.test.error")
    async def bad_handler(data: dict[str, Any]) -> None:
        raise RuntimeError("boom")

    @event_client.on_event("wh.test.error")
    async def good_handler(data: dict[str, Any]) -> str:
        calls.append(str(data.get("k")))
        return "done"

    result = await event_client._dispatch("wh.test.error", {"k": "v"})
    assert result == "done"
    assert calls == ["v"]
    assert any("bad_handler" in m for m in logged)  # 异常处理器被记录


async def test_dispatch_unknown_event_warning_no_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未注册的事件类型：warning 日志、返回 None、不抛异常。

    项目 dictConfig 对模块 logger 设 propagate=False，caplog 收不到，
    因此直接 spy 模块 logger（与生产日志路径同源）。
    """
    logged: list[str] = []
    monkeypatch.setattr(
        event_client.logger, "warning",
        lambda msg, *args: logged.append(msg % args if args else msg),
    )
    result = await event_client._dispatch("wh.test.unknown", {"k": 1})
    assert result is None
    assert any("wh.test.unknown" in m for m in logged)


# ── 单测：事件解码（v2 信封解包 + card.action.trigger ACK）──


async def test_dispatch_event_v2_unwrap(monkeypatch: pytest.MonkeyPatch) -> None:
    """v2 信封 {"schema","header","event"} 解包出 event_type 与 event payload。"""
    received: dict[str, Any] = {}

    async def fake_dispatch(event_type: str, event_data: dict[str, Any]) -> None:
        received["type"] = event_type
        received["data"] = event_data

    monkeypatch.setattr(event_client, "_dispatch", fake_dispatch)
    event = {
        "schema": "2.0",
        "header": {"event_type": "im.message.receive_v1"},
        "event": {"message": {"message_id": "om_1"}},
    }
    await event_client._dispatch_event(event)
    assert received["type"] == "im.message.receive_v1"
    assert received["data"] == {"message": {"message_id": "om_1"}}


async def test_card_action_trigger_ack_envelope(clean_handlers: None) -> None:
    """card.action.trigger：真 protobuf 帧往返，ACK payload 为 code=200 + base64 卡片。

    该 Response 信封（{"code": 200, "data": base64(card_json)}）是飞书 WS 协议
    让按钮状态变更的契约，gateway 卡片回调依赖此行为。
    """
    card_return = {"config": {"update_multi": True}, "elements": []}

    @event_client.on_event("card.action.trigger")
    async def card_handler(data: dict[str, Any]) -> dict[str, Any]:
        return card_return

    event = {
        "schema": "2.0",
        "header": {"event_type": "card.action.trigger"},
        "event": {"operator": {"open_id": "ou_x"}},
    }
    ws = _FakeWS()
    await event_client._handle_binary_message(ws, _build_event_frame(event))

    assert len(ws.sent) == 1  # ACK 必发（3 秒契约）
    ack = Frame()
    ack.ParseFromString(ws.sent[0])
    resp = json.loads(ack.payload.decode("utf-8"))
    assert resp["code"] == 200
    assert json.loads(base64.b64decode(resp["data"])) == card_return


async def test_plain_event_ack_no_card_payload(clean_handlers: None) -> None:
    """普通事件（非卡片）：ACK payload 为 {"code": 200}，事件异步分发不阻塞。"""
    done = asyncio.Event()

    @event_client.on_event("wh.test.plain")
    async def plain_handler(data: dict[str, Any]) -> None:
        done.set()

    event = {
        "schema": "2.0",
        "header": {"event_type": "wh.test.plain"},
        "event": {"k": "v"},
    }
    ws = _FakeWS()
    await event_client._handle_binary_message(ws, _build_event_frame(event))

    ack = Frame()
    ack.ParseFromString(ws.sent[0])
    assert json.loads(ack.payload.decode("utf-8")) == {"code": 200}
    # 异步 create_task 分发，短暂让出后应完成
    await asyncio.wait_for(done.wait(), timeout=2)
    event_client._handlers.pop("wh.test.plain", None)
