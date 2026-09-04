"""S1 ticket 02 验收：gateway 组装层（主接缝，spec Testing Decisions）。

构造 im.message.receive_v1 / card.action.trigger 的 event dict 直接调
gateway.handle_im_message / handle_card_action_trigger（不依赖 WS），全链路真实：
路由 → 去重（真 Redis SETNX）→ 会话定位（真库 whdev，事务回滚隔离）→
Runner 真实现（票03 起 LLM 真调；异常用例 monkeypatch 桩）→ 卡片构建 →
发送捕获（monkeypatch notification._send_create，payload 构建路径真实执行、
不触网）。

运行：cd "E:\\dazah(仓储)\\backend" &&
      DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/dazah_whdev"
      uv run pytest tests/modules/warehouse/test_live_gateway.py -v
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.redis as app_core_redis
from app.modules.warehouse.agent import confirm, gateway
from app.modules.warehouse.agent import runner as runner_module
from app.modules.warehouse.feishu import notification
from app.modules.warehouse.models import WarehouseAgentAudit, WarehouseAgentSession

# ── fixtures：Redis / 发送捕获 / gateway db 注入 ──


@pytest.fixture(autouse=True)
def fresh_runner(monkeypatch: pytest.MonkeyPatch):
    """每测试重置 Runner 单例。

    get_runner() 的模块级单例持有 WarehouseLLMClient（httpx 连接池绑定首次
    使用的 event loop），而 pytest-asyncio 每测试新建 loop——跨 loop 复用
    会连接报错（同 conftest 顶部记录的 redis_client 单例坑）。
    """
    monkeypatch.setattr(runner_module, "_runner", None)
    yield
    runner_module._runner = None


@pytest.fixture
async def fresh_redis(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[aioredis.Redis]:
    """每测试独立的 Redis 客户端并替换 app.core.redis.redis_client。

    app.core.redis 的模块级单例连接池绑定首次使用的 event loop，而
    pytest-asyncio 每个测试新建 loop——跨 loop 复用连接会抛异常。gateway
    的去重 helper 每次函数内 import 该属性，替换后即用本测试的客户端。
    """
    from app.core.config import get_settings

    client = aioredis.from_url(get_settings().REDIS_URL, decode_responses=True)
    monkeypatch.setattr(app_core_redis, "redis_client", client)
    yield client
    await client.aclose()


@pytest.fixture
def captured_sends(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    """捕获 notification 全部发送 payload（构建路径真实执行，不触网）。"""
    sent: list[dict[str, str]] = []

    async def fake_send(payload: dict[str, str]) -> str | None:
        sent.append(payload)
        return "om_fake_id"

    monkeypatch.setattr(notification, "_send_create", fake_send)
    return sent


@pytest.fixture
def gateway_db(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncSession:
    """gateway._db_session → 包装测试 session（不 commit，随 fixture 回滚隔离）。"""

    @asynccontextmanager
    async def _patched() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(gateway, "_db_session", _patched)
    return db_session


# ── 事件构造 helper（照票01 记录的 dict 结构）──


def _im_message_event(
    *,
    chat_id: str,
    sender_open_id: str,
    chat_type: str = "p2p",
    message_type: str = "text",
    text: str | None = None,
    content: dict[str, Any] | None = None,
    mentions: list[dict[str, Any]] | None = None,
    message_id: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = (
        content if content is not None else ({"text": text} if text is not None else {})
    )
    return {
        "sender": {
            "sender_id": {
                "open_id": sender_open_id,
                "union_id": "un_x",
                "user_id": "u_x",
            },
            "sender_type": "user",
            "tenant_key": "tenant",
        },
        "message": {
            "message_id": message_id or f"om_{uuid.uuid4().hex}",
            "root_id": "",
            "parent_id": "",
            "create_time": "1700000000000",
            "chat_id": chat_id,
            "chat_type": chat_type,
            "message_type": message_type,
            "content": json.dumps(body, ensure_ascii=False),
            "mentions": mentions or [],
        },
    }


def _card_action_event(
    *, operator_open_id: str, action: str, draft_id: str
) -> dict[str, Any]:
    """card.action.trigger 的 event dict（gateway 收到的是内层 event）。"""
    return {
        "operator": {"open_id": operator_open_id, "union_id": "un", "user_id": "u"},
        "token": "t",
        "action": {
            "tag": "button",
            "value": {"action": action, "scene": "confirm_action", "draft_id": draft_id},
        },
        "host": "im",
    }


def _bot_mention() -> list[dict[str, Any]]:
    return [
        {
            "key": "@_user_1",
            "id": {"open_id": gateway.BOT_OPEN_ID, "union_id": "un_bot", "user_id": "bot"},
            "name": "仓库管理机器人",
            "tenant_key": "tenant",
        }
    ]


def _card_of(payload: dict[str, str]) -> dict[str, Any]:
    return json.loads(payload["content"])


def _unique_chat(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# ── 1. 私聊文本 E2E ──


async def test_text_private_message_e2e(
    gateway_db: AsyncSession, captured_sends: list[dict[str, str]]
) -> None:
    """私聊文本 → 占位卡片 + 结果卡片两次发送（dry-run 捕获），全程无异常。"""
    event = _im_message_event(
        chat_id=_unique_chat("oc_p2p"), sender_open_id="ou_user_a", text="你好"
    )
    await gateway.handle_im_message(event)

    assert len(captured_sends) == 2
    first, second = captured_sends
    assert first["receive_id_type"] == "open_id"
    assert first["receive_id"] == "ou_user_a"
    assert first["msg_type"] == "interactive"
    placeholder = _card_of(first)
    assert "正在处理" in placeholder["header"]["title"]["content"]

    assert second["receive_id_type"] == "open_id"
    assert second["msg_type"] == "interactive"
    result = _card_of(second)
    # 票03 起 Runner 为真实现（LLM 真调），回复内容不固定——断言非空即可
    assert result["elements"][0]["content"].strip()


# ── 2. 群聊非 @ 忽略 ──


async def test_group_non_mention_ignored(
    gateway_db: AsyncSession, captured_sends: list[dict[str, str]]
) -> None:
    """群聊无 @ → 零发送、不建会话。"""
    chat_id = _unique_chat("oc_group")
    event = _im_message_event(
        chat_id=chat_id, chat_type="group", sender_open_id="ou_user_b", text="大家好"
    )
    await gateway.handle_im_message(event)

    assert captured_sends == []
    rows = (
        await gateway_db.execute(
            select(WarehouseAgentSession).where(WarehouseAgentSession.chat_id == chat_id)
        )
    ).scalars().all()
    assert rows == []


# ── 3. 群聊 @ 响应 ──


async def test_group_mention_responded(
    gateway_db: AsyncSession, captured_sends: list[dict[str, str]]
) -> None:
    """群聊 @机器人 → 正常响应（群卡片走 chat_id 通道），@占位符替换为名称。"""
    chat_id = _unique_chat("oc_group")
    event = _im_message_event(
        chat_id=chat_id,
        chat_type="group",
        sender_open_id="ou_user_c",
        text="@_user_1 硫酸还有多少",
        mentions=_bot_mention(),
    )
    await gateway.handle_im_message(event)

    assert len(captured_sends) == 2
    assert captured_sends[0]["receive_id_type"] == "chat_id"
    assert captured_sends[0]["receive_id"] == chat_id
    result = _card_of(captured_sends[1])
    # 票03 起 Runner 为真实现（LLM 真调），回复内容不固定——断言非空即可
    assert result["elements"][0]["content"].strip()


# ── 4. 同 message_id 去重 ──


async def test_duplicate_message_deduped(
    gateway_db: AsyncSession,
    captured_sends: list[dict[str, str]],
    fresh_redis: aioredis.Redis,
) -> None:
    """同一 message_id 二次投递 → 只处理一次（第二次零发送，真 Redis SETNX）。"""
    message_id = f"om_dup_{uuid.uuid4().hex[:10]}"
    dedup_key = f"feishu:msg:{message_id}"
    try:
        event = _im_message_event(
            chat_id=_unique_chat("oc_p2p"),
            sender_open_id="ou_user_d",
            text="第一次",
            message_id=message_id,
        )
        await gateway.handle_im_message(event)
        assert len(captured_sends) == 2

        await gateway.handle_im_message(event)  # 同 message_id 重复投递
        assert len(captured_sends) == 2  # 第二次零发送
    finally:
        await fresh_redis.delete(dedup_key)


# ── 5. 图片消息引导 ──


async def test_image_message_guidance(
    gateway_db: AsyncSession, captured_sends: list[dict[str, str]]
) -> None:
    """图片事件 → 友好引导卡片（单次发送，不进 Runner、不误报错误）。"""
    event = _im_message_event(
        chat_id=_unique_chat("oc_p2p"),
        sender_open_id="ou_user_e",
        message_type="image",
        content={"image_key": "img_v3_00s0_xxx"},
    )
    await gateway.handle_im_message(event)

    assert len(captured_sends) == 1
    card = _card_of(captured_sends[0])
    assert "图片识别" in card["elements"][0]["content"]


# ── 6. 会话持久化与复用 ──


async def test_session_persisted(
    gateway_db: AsyncSession, captured_sends: list[dict[str, str]]
) -> None:
    """首次对话建 sessions 记录；再次对话复用（不新建）且历史追加。"""
    chat_id = _unique_chat("oc_p2p")
    open_id = "ou_user_f"

    await gateway.handle_im_message(
        _im_message_event(chat_id=chat_id, sender_open_id=open_id, text="第一次")
    )
    rows = (
        await gateway_db.execute(
            select(WarehouseAgentSession).where(WarehouseAgentSession.chat_id == chat_id)
        )
    ).scalars().all()
    assert len(rows) == 1
    first_id = rows[0].id
    assert rows[0].user_open_id == open_id

    await gateway.handle_im_message(
        _im_message_event(chat_id=chat_id, sender_open_id=open_id, text="第二次")
    )
    rows2 = (
        await gateway_db.execute(
            select(WarehouseAgentSession).where(WarehouseAgentSession.chat_id == chat_id)
        )
    ).scalars().all()
    assert len(rows2) == 1  # 复用，未新建
    assert rows2[0].id == first_id
    messages = rows2[0].history.get("messages", [])
    assert len(messages) == 4  # 两轮对话：user/assistant 各两条
    assert messages[0]["content"] == "第一次"
    assert messages[2]["content"] == "第二次"


# ── 7. Runner 异常降级 ──


class _BoomRunner:
    async def run(self, session: Any, text: str) -> Any:
        raise RuntimeError("runner boom")


async def test_runner_error_degrades(
    gateway_db: AsyncSession,
    captured_sends: list[dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runner 抛错 → 用户收到降级话术卡片，audit 记录 error。"""
    monkeypatch.setattr(gateway, "get_runner", lambda: _BoomRunner())
    event = _im_message_event(
        chat_id=_unique_chat("oc_p2p"), sender_open_id="ou_user_g", text="触发异常"
    )
    await gateway.handle_im_message(event)

    assert len(captured_sends) == 2  # 占位卡片 + 降级卡片
    error_card = _card_of(captured_sends[1])
    assert "处理失败" in error_card["header"]["title"]["content"]

    audits = (
        await gateway_db.execute(
            select(WarehouseAgentAudit).where(
                WarehouseAgentAudit.tool_name == "gateway",
                WarehouseAgentAudit.result_status == "error",
                WarehouseAgentAudit.error_code == "RuntimeError",
            )
        )
    ).scalars().all()
    assert len(audits) == 1
    assert audits[0].session_id is not None


# ── 8. ConfirmService 确认流 ──


async def test_confirm_flow(
    gateway_db: AsyncSession,
    captured_sends: list[dict[str, str]],
) -> None:
    """确认门机制：请求确认 → 点确认回调执行；非发起人拒绝；过期拒绝。"""
    calls: list[str] = []

    async def fake_callback(db: AsyncSession, draft: Any) -> str | None:
        calls.append(draft.draft_no)
        return "已执行测试动作"

    confirm.register_confirm_callback(confirm.CONFIRM_SCENE, fake_callback)
    try:
        # ── 正常流：发起人点确认 → 回调执行、状态 confirmed ──
        draft = await confirm.request_confirm(
            gateway_db,
            requester_open_id="ou_req",
            summary="向张三发送呆料报告（测试）",
            payload={"to": "zhangsan"},
        )
        assert draft.status == "pending_confirm"
        assert draft.expires_at is not None

        card = confirm.build_confirm_card(draft)
        confirm_btn = card["elements"][1]["actions"][0]
        assert confirm_btn["value"]["scene"] == "confirm_action"
        assert confirm_btn["value"]["draft_id"] == str(draft.id)

        update = await gateway.handle_card_action_trigger(
            _card_action_event(
                operator_open_id="ou_req", action="confirm", draft_id=str(draft.id)
            )
        )
        assert update is not None
        assert "已执行测试动作" in update["elements"][0]["content"]
        assert calls == [draft.draft_no]
        assert draft.status == "confirmed"

        # ── 非发起人点击：拒绝、回调不执行、草稿保持 pending ──
        draft2 = await confirm.request_confirm(
            gateway_db, requester_open_id="ou_req2", summary="第二条确认（测试）"
        )
        update2 = await gateway.handle_card_action_trigger(
            _card_action_event(
                operator_open_id="ou_hacker", action="confirm", draft_id=str(draft2.id)
            )
        )
        assert update2 is not None
        assert "仅发起人" in update2["elements"][0]["content"]
        assert calls == [draft.draft_no]  # 回调未再执行
        assert draft2.status == "pending_confirm"

        # ── 过期点击：拒绝、状态置 expired ──
        draft3 = await confirm.request_confirm(
            gateway_db, requester_open_id="ou_req3", summary="第三条确认（测试）"
        )
        draft3.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await gateway_db.flush()
        update3 = await gateway.handle_card_action_trigger(
            _card_action_event(
                operator_open_id="ou_req3", action="confirm", draft_id=str(draft3.id)
            )
        )
        assert update3 is not None
        assert "已过期" in update3["elements"][0]["content"]
        assert calls == [draft.draft_no]  # 过期后回调不执行
        assert draft3.status == "expired"
    finally:
        confirm.unregister_confirm_callback(confirm.CONFIRM_SCENE)

    # confirm 审计：确认 ok 一条、非发起人 denied 一条、过期 denied 一条
    audits = (
        await gateway_db.execute(
            select(WarehouseAgentAudit)
            .where(WarehouseAgentAudit.tool_name == "confirm")
            .order_by(WarehouseAgentAudit.created_at)
        )
    ).scalars().all()
    statuses = [a.result_status for a in audits]
    assert "ok" in statuses
    assert statuses.count("denied") == 2
