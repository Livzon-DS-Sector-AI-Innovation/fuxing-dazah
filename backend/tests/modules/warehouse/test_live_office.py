"""S1 ticket 07 验收：办公工具 + HITL 确认门。

组件直测（spec Testing Decisions）：send_card 确认门全流程（工具调用 → 预览
卡片 → 仅发起人点确认 → dry-run 捕获发往目标地址的真实卡片 → drafts 状态机）、
非发起人/取消/过期拒绝、create_reminder 注册+短间隔触发+取消+未来时间校验。
live 主接缝：gateway.handle_im_message 全链路（真 LLM 真库），发送 dry-run
捕获（monkeypatch notification._send_create）：
- 「把呆料清单发给 group:XXX 测试群」→ LLM 调 send_card → 预览卡片出现
  （未确认前目标地址零发送）→ 模拟发起人点确认 → 捕获到目标群的真实卡片。

运行：cd "E:\\dazah(仓储)\\backend" &&
      DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/dazah_whdev"
      uv run pytest tests/modules/warehouse/test_live_office.py -v
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.redis as app_core_redis
from app.modules.warehouse.agent import confirm, gateway
from app.modules.warehouse.agent import runner as runner_module
from app.modules.warehouse.agent.tools import office as office_tools
from app.modules.warehouse.agent.tools.query import TOOL_FUNCS, TOOLS
from app.modules.warehouse.feishu import notification
from app.modules.warehouse.models import WarehouseAgentDraft

# ── fixtures ──


@pytest.fixture(autouse=True)
def fresh_runner(monkeypatch: pytest.MonkeyPatch):
    """每测试重置 Runner 单例（pytest-asyncio 每测试新建 loop，连接池不可跨用）。"""
    monkeypatch.setattr(runner_module, "_runner", None)
    yield
    runner_module._runner = None


@pytest.fixture
def office_db(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncSession:
    """office/runner/gateway 的 _db_session → 包装测试 session（不 commit，回滚隔离）。"""

    @asynccontextmanager
    async def _patched() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(office_tools, "_db_session", _patched)
    monkeypatch.setattr(runner_module, "_db_session", _patched)
    monkeypatch.setattr(gateway, "_db_session", _patched)
    return db_session


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
async def fresh_redis(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[aioredis.Redis]:
    """每测试独立 Redis 客户端（gateway 去重用；模块级单例跨 loop 会抛异常）。"""
    from app.core.config import get_settings

    client = aioredis.from_url(get_settings().REDIS_URL, decode_responses=True)
    monkeypatch.setattr(app_core_redis, "redis_client", client)
    yield client
    await client.aclose()


# ── helpers ──


def _card_of(payload: dict[str, str]) -> dict[str, Any]:
    return json.loads(payload["content"])


def _buttons_of(card: dict[str, Any]) -> list[dict[str, Any]]:
    """卡片内全部按钮（elements 中 action 元素的 actions 摊平）。"""
    buttons: list[dict[str, Any]] = []
    for element in card.get("elements") or []:
        if element.get("tag") == "action":
            buttons.extend(element.get("actions") or [])
    return buttons


def _card_action_event(
    *, operator_open_id: str, action: str, draft_id: str
) -> dict[str, Any]:
    """card.action.trigger 的 event dict（gateway 收到的是内层 event）。"""
    return {
        "operator": {"open_id": operator_open_id, "union_id": "un", "user_id": "u"},
        "token": "t",
        "action": {
            "tag": "button",
            "value": {"action": action, "scene": office_tools.SEND_CARD_SCENE, "draft_id": draft_id},
        },
        "host": "im",
    }


def _unique_chat(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


async def _request_via_tool(
    office_db: AsyncSession,
    *,
    target: str,
    requester: str = "ou_worker_a",
    chat_id: str | None = None,
    title: str = "呆料周报",
    content: str = "本周呆料共 12 批，明细如下…",
) -> dict[str, Any]:
    """经 send_card 工具发起一次确认（组件接缝），返回工具结果。"""
    return await office_tools.send_card(
        target,
        title,
        content,
        _ctx={"open_id": requester, "chat_id": chat_id or _unique_chat("oc_comp")},
    )


# ══ 组件：注册表并入 ══


def test_office_tools_registered() -> None:
    """send_card / create_reminder 并入 query 注册表；send_card 确认回调已注册。"""
    assert TOOL_FUNCS["send_card"] is office_tools.send_card
    assert TOOL_FUNCS["create_reminder"] is office_tools.create_reminder
    names = {t["function"]["name"] for t in TOOLS}
    assert {"send_card", "create_reminder"} <= names
    assert confirm.is_registered_scene(office_tools.SEND_CARD_SCENE)
    assert not confirm.is_registered_scene("no_such_scene")


# ══ 组件：send_card 确认门 ══


async def test_send_card_confirm_gate_full_flow(
    office_db: AsyncSession, captured_sends: list[dict[str, str]]
) -> None:
    """确认门全流程：工具调用 → 预览卡片（目标零发送）→ 发起人点确认 →
    dry-run 捕获发往目标的真实卡片 → drafts 状态 confirmed。"""
    requester = "ou_worker_a"
    chat_id = _unique_chat("oc_comp")
    result = await _request_via_tool(
        office_db,
        target="user:ou_target_person",
        requester=requester,
        chat_id=chat_id,
    )
    assert "error" not in result
    assert result["status"] == "pending_confirm"

    # 未确认前：目标地址零发送；预览卡片发到发起人所在会话
    assert all(p["receive_id"] != "ou_target_person" for p in captured_sends)
    preview_payload = next(p for p in captured_sends if p["receive_id"] == chat_id)
    preview = _card_of(preview_payload)
    assert "待发送确认" in preview["header"]["title"]["content"]
    body = preview["elements"][0]["content"]
    assert "呆料周报" in body
    assert "user:ou_target_person" in body
    assert "本周呆料共 12 批" in body
    confirm_btn, cancel_btn = _buttons_of(preview)
    assert confirm_btn["value"]["scene"] == office_tools.SEND_CARD_SCENE
    assert confirm_btn["value"]["action"] == "confirm"
    assert cancel_btn["value"]["action"] == "cancel"
    draft_id = confirm_btn["value"]["draft_id"]

    # 非目标地址收到确认 → dry-run 捕获发往目标私聊的真实卡片
    update = await gateway.handle_card_action_trigger(
        _card_action_event(
            operator_open_id=requester, action="confirm", draft_id=draft_id
        )
    )
    assert update is not None
    assert "已发送到" in update["elements"][0]["content"]
    target_sends = [p for p in captured_sends if p["receive_id"] == "ou_target_person"]
    assert len(target_sends) == 1
    assert target_sends[0]["receive_id_type"] == "open_id"
    real_card = _card_of(target_sends[0])
    assert real_card["header"]["title"]["content"] == "呆料周报"
    assert "本周呆料共 12 批" in real_card["elements"][0]["content"]

    draft = await office_db.get(WarehouseAgentDraft, uuid.UUID(draft_id))
    assert draft is not None
    assert draft.status == "confirmed"


async def test_send_card_non_requester_rejected(
    office_db: AsyncSession, captured_sends: list[dict[str, str]]
) -> None:
    """非发起人点确认：拒绝、不发送、草稿保持 pending_confirm。"""
    result = await _request_via_tool(
        office_db, target="group:oc_target_grp_a", requester="ou_owner"
    )
    draft_id = str(result["draft_id"])
    sends_before = len(captured_sends)

    update = await gateway.handle_card_action_trigger(
        _card_action_event(
            operator_open_id="ou_hacker", action="confirm", draft_id=draft_id
        )
    )
    assert update is not None
    assert "仅发起人" in update["elements"][0]["content"]
    assert len(captured_sends) == sends_before  # 零新增发送
    assert all(p["receive_id"] != "oc_target_grp_a" for p in captured_sends)
    draft = await office_db.get(WarehouseAgentDraft, uuid.UUID(draft_id))
    assert draft is not None
    assert draft.status == "pending_confirm"


async def test_send_card_cancel_no_send(
    office_db: AsyncSession, captured_sends: list[dict[str, str]]
) -> None:
    """发起人点取消：状态 cancelled，不发送。"""
    result = await _request_via_tool(
        office_db, target="group:oc_target_grp_b", requester="ou_owner"
    )
    draft_id = str(result["draft_id"])

    update = await gateway.handle_card_action_trigger(
        _card_action_event(operator_open_id="ou_owner", action="cancel", draft_id=draft_id)
    )
    assert update is not None
    assert "已取消" in update["elements"][0]["content"]
    assert all(p["receive_id"] != "oc_target_grp_b" for p in captured_sends)
    draft = await office_db.get(WarehouseAgentDraft, uuid.UUID(draft_id))
    assert draft is not None
    assert draft.status == "cancelled"

    # 取消后再点确认：草稿非 pending，拒绝且不发送
    update2 = await gateway.handle_card_action_trigger(
        _card_action_event(operator_open_id="ou_owner", action="confirm", draft_id=draft_id)
    )
    assert update2 is not None
    assert "已被处理" in update2["elements"][0]["content"]
    assert all(p["receive_id"] != "oc_target_grp_b" for p in captured_sends)


async def test_send_card_expired_no_send(
    office_db: AsyncSession, captured_sends: list[dict[str, str]]
) -> None:
    """TTL 过期（注入：回拨 expires_at）点确认：拒绝、状态 expired、不发送。"""
    result = await _request_via_tool(
        office_db, target="group:oc_target_grp_c", requester="ou_owner"
    )
    draft_id = uuid.UUID(str(result["draft_id"]))
    draft = await office_db.get(WarehouseAgentDraft, draft_id)
    assert draft is not None and draft.expires_at is not None
    assert draft.expires_at - datetime.now(UTC) > timedelta(minutes=9)  # 默认 TTL 10min
    draft.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await office_db.flush()

    update = await gateway.handle_card_action_trigger(
        _card_action_event(operator_open_id="ou_owner", action="confirm", draft_id=str(draft_id))
    )
    assert update is not None
    assert "已过期" in update["elements"][0]["content"]
    assert all(p["receive_id"] != "oc_target_grp_c" for p in captured_sends)
    refreshed = await office_db.get(WarehouseAgentDraft, draft_id)
    assert refreshed is not None
    assert refreshed.status == "expired"


async def test_send_card_invalid_target_error(office_db: AsyncSession) -> None:
    """无效目标（人名/空 ID/错误前缀）返回 error 并提示向用户索取，不猜测。"""
    for bad in ("陈玉英", "user:", "user:陈玉英", "group:张三的群"):
        result = await office_tools.send_card(
            bad, "标题", "内容", _ctx={"open_id": "ou_x", "chat_id": "oc_y"}
        )
        assert "error" in result, f"target={bad!r} 应返回 error"
        assert "user:<open_id>" in result["hint"]


# ══ 组件：create_reminder ══


async def test_create_reminder_fires_and_captured(
    office_db: AsyncSession, captured_sends: list[dict[str, str]]
) -> None:
    """注册提醒 → 短间隔注入（0.6s）→ 到点 dry-run 捕获提醒卡片 → 状态 fired。"""
    trigger = datetime.now(UTC) + timedelta(seconds=0.6)
    result = await office_tools.create_reminder(
        trigger.isoformat(),
        "该看出报情况了",
        _ctx={"open_id": "ou_reminder_user", "chat_id": "oc_rem_chat"},
    )
    assert "error" not in result
    reminder_id = str(result["reminder_id"])
    assert result["trigger_at"] == trigger.isoformat()

    await asyncio.sleep(1.5)
    reminder_payloads = [
        p for p in captured_sends
        if "到点提醒" in _card_of(p)["header"]["title"]["content"]
    ]
    assert len(reminder_payloads) == 1
    assert reminder_payloads[0]["receive_id"] == "oc_rem_chat"
    card = _card_of(reminder_payloads[0])
    assert "该看出报情况了" in card["elements"][0]["content"]

    draft = await office_db.get(WarehouseAgentDraft, uuid.UUID(reminder_id))
    assert draft is not None
    assert draft.scene == office_tools.REMINDER_SCENE
    assert draft.status == "fired"


async def test_create_reminder_past_or_unparseable_time_error(
    office_db: AsyncSession,
) -> None:
    """过去时间 / 无法解析的时间返回 error，不落库不调度。"""
    ctx: dict[str, Any] = {"open_id": "ou_reminder_user", "chat_id": "oc_rem_chat"}
    past = await office_tools.create_reminder(
        "2020-01-01T08:00:00", "太迟了", _ctx=ctx
    )
    assert "error" in past
    assert "未来" in past["error"]

    unparseable = await office_tools.create_reminder("明天下午", "没转 ISO", _ctx=ctx)
    assert "error" in unparseable
    assert "无法解析" in unparseable["error"]

    empty = await office_tools.create_reminder(
        (datetime.now(UTC) + timedelta(hours=1)).isoformat(), "  ", _ctx=ctx
    )
    assert "error" in empty
    assert "content" in empty["error"]


async def test_cancel_reminder(
    office_db: AsyncSession, captured_sends: list[dict[str, str]]
) -> None:
    """取消提醒：延时任务撤销、状态 cancelled、到点不发送；重复取消返回 False。"""
    trigger = datetime.now(UTC) + timedelta(seconds=60)
    result = await office_tools.create_reminder(
        trigger.isoformat(), "一小时后不该触发", _ctx={"open_id": "ou_c", "chat_id": "oc_c"}
    )
    assert "error" not in result
    reminder_id = str(result["reminder_id"])

    assert await office_tools.cancel_reminder(reminder_id) is True
    await asyncio.sleep(0.3)
    assert not [
        p for p in captured_sends
        if "到点提醒" in _card_of(p)["header"]["title"]["content"]
    ]
    draft = await office_db.get(WarehouseAgentDraft, uuid.UUID(reminder_id))
    assert draft is not None
    assert draft.status == "cancelled"
    assert await office_tools.cancel_reminder(reminder_id) is False  # 已取消，不可再取消


# ══ live 主接缝：真 LLM 全链路 ══


async def test_live_send_card_via_gateway(
    office_db: AsyncSession,
    captured_sends: list[dict[str, str]],
    fresh_redis: aioredis.Redis,
) -> None:
    """「把呆料清单发给 group:XXX 测试群」→ 真实 LLM 调 send_card → 预览卡片
    出现（目标地址零发送）→ 发起人点确认 → dry-run 捕获发往目标群的真实卡片。"""
    requester = "ou_live_requester"
    target_group = "oc_livetest_target_group"
    event = {
        "sender": {
            "sender_id": {"open_id": requester, "union_id": "un_x", "user_id": "u_x"},
            "sender_type": "user",
            "tenant_key": "tenant",
        },
        "message": {
            "message_id": f"om_{uuid.uuid4().hex}",
            "root_id": "",
            "parent_id": "",
            "create_time": "1700000000000",
            "chat_id": _unique_chat("oc_live"),
            "chat_type": "p2p",
            "message_type": "text",
            "content": json.dumps(
                {"text": f"请把呆料清单发送到 group:{target_group} 这个测试群"},
                ensure_ascii=False,
            ),
            "mentions": [],
        },
    }
    await gateway.handle_im_message(event)

    # 未确认前：目标群零发送；预览确认卡片出现（scene=send_card）
    assert all(p["receive_id"] != target_group for p in captured_sends)
    preview: dict[str, Any] | None = None
    for payload in captured_sends:
        if payload.get("msg_type") != "interactive":
            continue
        card = _card_of(payload)
        for button in _buttons_of(card):
            if button.get("value", {}).get("scene") == office_tools.SEND_CARD_SCENE:
                preview = card
    assert preview is not None, "未捕获到 send_card 预览确认卡片"
    draft_id = next(
        button["value"]["draft_id"]
        for button in _buttons_of(preview)
        if button["value"].get("action") == "confirm"
    )

    # 发起人点确认 → dry-run 捕获到目标群的真实卡片
    update = await gateway.handle_card_action_trigger(
        _card_action_event(
            operator_open_id=requester, action="confirm", draft_id=draft_id
        )
    )
    assert update is not None
    assert "已发送到" in update["elements"][0]["content"]
    target_sends = [p for p in captured_sends if p["receive_id"] == target_group]
    assert len(target_sends) == 1
    assert target_sends[0]["receive_id_type"] == "chat_id"

    draft = await office_db.get(WarehouseAgentDraft, uuid.UUID(draft_id))
    assert draft is not None
    assert draft.status == "confirmed"


async def test_send_card_second_confirm_rejected_after_confirmed(
    office_db: AsyncSession, captured_sends: list[dict[str, str]]
) -> None:
    """审查修复验证：确认成功后重复点击被状态机拒绝（防重复发送）。"""
    requester = "ou_worker_a"
    result = await _request_via_tool(
        office_db,
        target="user:ou_target_person",
        requester=requester,
        chat_id=_unique_chat("oc_rep"),
    )
    assert "error" not in result
    # 从预览卡片拿 draft_id
    preview_payload = next(
        p for p in captured_sends if "待发送确认" in str(p)
    ) if any("待发送确认" in str(p) for p in captured_sends) else None
    assert preview_payload is not None
    preview = _card_of(preview_payload)
    confirm_btn, _ = _buttons_of(preview)
    draft_id = confirm_btn["value"]["draft_id"]

    # 第一次点击 → 确认执行
    update1 = await gateway.handle_card_action_trigger(
        _card_action_event(operator_open_id=requester, action="confirm", draft_id=draft_id)
    )
    assert update1 is not None and "✅" in str(update1["elements"][0]["content"])

    # 第二次点击 → 状态已非 pending_confirm，拒绝（不重复执行发送）
    sends_before = len([p for p in captured_sends if p["receive_id"] == "ou_target_person"])
    update2 = await gateway.handle_card_action_trigger(
        _card_action_event(operator_open_id=requester, action="confirm", draft_id=draft_id)
    )
    assert update2 is not None and "⚠️" in str(update2["elements"][0]["content"])
    sends_after = len([p for p in captured_sends if p["receive_id"] == "ou_target_person"])
    assert sends_after == sends_before  # 零重复发送
