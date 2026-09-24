"""gateway post 富文本消息支持测试（2026-09-23 群聊文图混合未回复事故修复）。

覆盖：
- _extract_post_parts 纯函数：新老格式、@机器人剔除、多段拼接、media 跳过、
  解析失败；
- 类型路由：文+图 → 识别管线（user_text/msg_type 透传）、多图逐张各起
  任务、纯文字 post → 对话链路、空 post / file 类型 → 提示卡 + ignored
  审计（不再静默丢弃）；
- recognizer 用户文字注入：_prompt_with_user_text 纯函数 + 两个识别函数
  的提示词透传（stub LLM 客户端断言）。

接缝沿 test_finished_receipt 样板（agent_db / captured_sends / fresh_redis）。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.redis as app_core_redis
from app.modules.warehouse.agent import gateway
from app.modules.warehouse.agent import runner as runner_module
from app.modules.warehouse.agent.pipeline.recognizer import (
    FINISHED_RECEIPT_PROMPT,
    RECOGNIZE_PROMPT,
    _prompt_with_user_text,
    recognize_finished_receipt,
    recognize_receipt,
)
from app.modules.warehouse.models import WarehouseAgentAudit

# ── fixtures（test_finished_receipt 同款注入口）──


@pytest.fixture
def agent_db(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> AsyncSession:
    @asynccontextmanager
    async def _patched() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(gateway, "_db_session", _patched)
    monkeypatch.setattr(runner_module, "_db_session", _patched)
    return db_session


@pytest.fixture
def captured_sends(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    sent: list[dict[str, str]] = []

    async def fake_send(payload: dict[str, str]) -> str | None:
        sent.append(payload)
        return "om_fake_id"

    from app.modules.warehouse.feishu import notification

    monkeypatch.setattr(notification, "_send_create", fake_send)
    return sent


@pytest.fixture(autouse=True)
def fresh_runner(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    monkeypatch.setattr(runner_module, "_runner", None)
    yield
    runner_module._runner = None


@pytest.fixture
async def fresh_redis(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[aioredis.Redis]:
    from app.core.config import get_settings

    client = aioredis.from_url(get_settings().REDIS_URL, decode_responses=True)
    monkeypatch.setattr(app_core_redis, "redis_client", client)
    yield client
    await client.aclose()


# ── 工厂 ──

INCIDENT_TEXT = "成品入库 替考拉宁 批号 TED2609002 75.405kg"


def _im_post_event(
    *,
    chat_id: str,
    sender_open_id: str,
    paragraphs: list[list[dict[str, Any]]] | None = None,
    chat_type: str = "group",
) -> dict[str, Any]:
    """post 事件工厂（默认复刻 2026-09-23 事故形态：@机器人 + 文字 + 图）。"""
    if paragraphs is None:
        paragraphs = [[
            {"tag": "at", "user_id": gateway.bot_open_id(),
             "user_name": "仓库管理机器人"},
            {"tag": "text", "text": f" {INCIDENT_TEXT}"},
            {"tag": "img", "image_key": "img_v2_fake_post_1"},
        ]]
    return {
        "sender": {
            "sender_id": {"open_id": sender_open_id, "union_id": "un", "user_id": "u"},
            "sender_type": "user",
            "tenant_key": "tenant",
        },
        "message": {
            "message_id": f"om_{uuid.uuid4().hex}",
            "root_id": "",
            "parent_id": "",
            "create_time": "1700000000000",
            "chat_id": chat_id,
            "chat_type": chat_type,
            "message_type": "post",
            "content": json.dumps(
                {"title": "", "content": paragraphs}, ensure_ascii=False
            ),
            "mentions": [
                {
                    "key": "@_user_1",
                    "id": {"open_id": gateway.bot_open_id()},
                    "name": "仓库管理机器人",
                }
            ],
        },
    }


def _interactive_cards(sends: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        json.loads(p["content"]) for p in sends if p.get("msg_type") == "interactive"
    ]


def _card_content(card: dict[str, Any]) -> str:
    return "\n".join(
        element.get("content") or ""
        for element in card.get("body", {}).get("elements", [])
        if isinstance(element, dict)
    )


async def _drain_gateway_tasks() -> None:
    tasks = [t for t in list(gateway._background_tasks) if not t.done()]
    for t in tasks:
        await t


# ═══════════════════════════════════════════════════════════════
# _extract_post_parts 纯函数
# ═══════════════════════════════════════════════════════════════


def _message_of(content: Any) -> dict[str, Any]:
    return {
        "message_type": "post",
        "content": content if isinstance(content, str) else json.dumps(
            content, ensure_ascii=False
        ),
    }


class TestExtractPostParts:
    def test_new_format_text_img_and_at(self) -> None:
        message = _message_of({
            "title": "",
            "content": [[
                {"tag": "at", "user_id": gateway.bot_open_id(),
                 "user_name": "仓库管理机器人"},
                {"tag": "text", "text": f" {INCIDENT_TEXT}"},
                {"tag": "img", "image_key": "img_v2_fake_post_1"},
            ]],
        })
        text, image_keys = gateway._extract_post_parts(message)
        assert text == INCIDENT_TEXT  # @机器人自身剔除，前后空格 strip
        assert image_keys == ["img_v2_fake_post_1"]

    def test_other_user_at_kept(self) -> None:
        message = _message_of({
            "title": "",
            "content": [[
                {"tag": "at", "user_id": "ou_someone_else", "user_name": "张三"},
                {"tag": "text", "text": " 看一下"},  # 真机形态：@后的 text 段自带前导空格
            ]],
        })
        text, image_keys = gateway._extract_post_parts(message)
        assert text == "@张三 看一下"
        assert image_keys == []

    def test_old_locale_format(self) -> None:
        message = _message_of({
            "zh_cn": {
                "title": "进货通知",
                "content": [
                    [{"tag": "text", "text": "第一行"}],
                    [
                        {"tag": "img", "image_key": "img_v2_locale"},
                        {"tag": "text", "text": "图后说明"},
                    ],
                ],
            }
        })
        text, image_keys = gateway._extract_post_parts(message)
        assert text == "进货通知\n第一行\n图后说明"
        assert image_keys == ["img_v2_locale"]

    def test_link_element_text_taken(self) -> None:
        message = _message_of({
            "title": "",
            "content": [[
                {"tag": "a", "text": "单据链接", "href": "https://example.com"},
            ]],
        })
        text, _ = gateway._extract_post_parts(message)
        assert text == "单据链接"

    def test_media_emotion_only_returns_empty(self) -> None:
        message = _message_of({
            "title": "",
            "content": [[
                {"tag": "emotion", "emoji_type": "OK"},
                {"tag": "media", "file_key": "file_v2_video"},
            ]],
        })
        text, image_keys = gateway._extract_post_parts(message)
        assert text == ""
        assert image_keys == []

    def test_bad_json_returns_empty(self) -> None:
        text, image_keys = gateway._extract_post_parts(_message_of("不是 JSON"))
        assert text == ""
        assert image_keys == []


# ═══════════════════════════════════════════════════════════════
# 类型路由
# ═══════════════════════════════════════════════════════════════


class TestGatewayPostRouting:
    async def test_post_text_image_routes_to_pipeline_with_user_text(
        self,
        agent_db: AsyncSession,
        captured_sends: list[dict[str, str]],
        fresh_redis: aioredis.Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """文+图 post（事故形态）：占位卡 + 识别任务携带 user_text/msg_type。"""
        spawned: list[dict[str, Any]] = []

        async def fake_process(**kwargs: Any) -> None:
            spawned.append(kwargs)

        monkeypatch.setattr(gateway, "_process_receipt_image", fake_process)

        await gateway.handle_im_message(
            _im_post_event(chat_id="oc_post_1", sender_open_id="ou_user_1")
        )
        await _drain_gateway_tasks()

        assert len(spawned) == 1
        assert spawned[0]["image_key"] == "img_v2_fake_post_1"
        assert spawned[0]["user_text"] == INCIDENT_TEXT
        assert spawned[0]["msg_type"] == "post"
        assert spawned[0]["chat_type"] == "group"

        cards_sent = _interactive_cards(captured_sends)
        assert len(cards_sent) == 1  # 占位卡（识别本身已桩掉）
        assert cards_sent[0]["header"]["title"]["content"] == "🖼 正在识别，请稍候…"
        assert "已收到图片" in _card_content(cards_sent[0])

    async def test_post_multi_image_spawns_task_per_image(
        self,
        agent_db: AsyncSession,
        captured_sends: list[dict[str, str]],
        fresh_redis: aioredis.Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """多图 post：逐张各起任务 + 占位卡提示张数（2026-09-23 决策）。"""
        spawned: list[dict[str, Any]] = []

        async def fake_process(**kwargs: Any) -> None:
            spawned.append(kwargs)

        monkeypatch.setattr(gateway, "_process_receipt_image", fake_process)

        paragraphs: list[list[dict[str, Any]]] = [[
            {"tag": "text", "text": "两张单据"},
            {"tag": "img", "image_key": "img_v2_multi_1"},
            {"tag": "img", "image_key": "img_v2_multi_2"},
        ]]
        await gateway.handle_im_message(
            _im_post_event(
                chat_id="oc_post_2", sender_open_id="ou_user_2",
                paragraphs=paragraphs,
            )
        )
        await _drain_gateway_tasks()

        assert [s["image_key"] for s in spawned] == ["img_v2_multi_1", "img_v2_multi_2"]
        assert all(s["user_text"] == "两张单据" for s in spawned)
        cards_sent = _interactive_cards(captured_sends)
        assert len(cards_sent) == 1
        assert "2 张图片" in _card_content(cards_sent[0])
        assert "逐张识别" in _card_content(cards_sent[0])

    async def test_post_text_only_routes_to_text_handler(
        self,
        agent_db: AsyncSession,
        captured_sends: list[dict[str, str]],
        fresh_redis: aioredis.Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """纯文字 post（富文本无图）：作为普通文字进对话链路。"""
        handled: list[dict[str, Any]] = []

        async def fake_handle(**kwargs: Any) -> None:
            handled.append(kwargs)

        monkeypatch.setattr(gateway, "_handle_text_message", fake_handle)

        paragraphs: list[list[dict[str, Any]]] = [[
            {"tag": "at", "user_id": gateway.bot_open_id(),
             "user_name": "仓库管理机器人"},
            {"tag": "text", "text": " 库存里还有多少替考拉宁"},
        ]]
        await gateway.handle_im_message(
            _im_post_event(
                chat_id="oc_post_3", sender_open_id="ou_user_3",
                paragraphs=paragraphs,
            )
        )

        assert len(handled) == 1
        assert handled[0]["text"] == "库存里还有多少替考拉宁"
        assert not _interactive_cards(captured_sends)  # 不发识别占位卡

    async def test_post_empty_replies_unsupported_card_and_audits(
        self,
        agent_db: AsyncSession,
        captured_sends: list[dict[str, str]],
        fresh_redis: aioredis.Redis,
    ) -> None:
        """空 post（纯表情/视频段）：提示卡 + ignored 审计（不再静默）。"""
        paragraphs: list[list[dict[str, Any]]] = [[
            {"tag": "at", "user_id": gateway.bot_open_id(),
             "user_name": "仓库管理机器人"},
            {"tag": "emotion", "emoji_type": "OK"},
        ]]
        await gateway.handle_im_message(
            _im_post_event(
                chat_id="oc_post_4", sender_open_id="ou_user_4",
                paragraphs=paragraphs,
            )
        )
        await _drain_gateway_tasks()

        cards_sent = _interactive_cards(captured_sends)
        assert len(cards_sent) == 1
        assert cards_sent[0]["header"]["title"]["content"] == "🤔 暂不支持该消息类型"
        assert "post" in _card_content(cards_sent[0])

        rows = (
            await agent_db.execute(
                select(WarehouseAgentAudit).where(
                    WarehouseAgentAudit.error_code == "unsupported_message_type"
                )
            )
        ).scalars().all()
        assert any(
            r.args_summary.get("message_type") == "post"
            and r.result_status == "ignored"
            for r in rows
        )

    async def test_file_type_replies_unsupported_card_and_audits(
        self,
        agent_db: AsyncSession,
        captured_sends: list[dict[str, str]],
        fresh_redis: aioredis.Redis,
    ) -> None:
        """file 类型：提示卡 + ignored 审计（2026-09-23 前静默 return）。"""
        event = {
            "sender": {
                "sender_id": {"open_id": "ou_user_5", "union_id": "un", "user_id": "u"},
                "sender_type": "user",
                "tenant_key": "tenant",
            },
            "message": {
                "message_id": f"om_{uuid.uuid4().hex}",
                "root_id": "",
                "parent_id": "",
                "create_time": "1700000000000",
                "chat_id": "oc_post_5",
                "chat_type": "group",
                "message_type": "file",
                "content": json.dumps({"file_key": "file_v2_x"}),
                "mentions": [
                    {
                        "key": "@_user_1",
                        "id": {"open_id": gateway.bot_open_id()},
                        "name": "仓库管理机器人",
                    }
                ],
            },
        }
        await gateway.handle_im_message(event)

        cards_sent = _interactive_cards(captured_sends)
        assert len(cards_sent) == 1
        assert "file" in _card_content(cards_sent[0])
        rows = (
            await agent_db.execute(
                select(WarehouseAgentAudit).where(
                    WarehouseAgentAudit.error_code == "unsupported_message_type"
                )
            )
        ).scalars().all()
        assert any(r.args_summary.get("message_type") == "file" for r in rows)


# ═══════════════════════════════════════════════════════════════
# recognizer 用户文字注入
# ═══════════════════════════════════════════════════════════════


class TestPromptWithUserText:
    def test_none_or_empty_returns_prompt_unchanged(self) -> None:
        assert _prompt_with_user_text(RECOGNIZE_PROMPT, None) == RECOGNIZE_PROMPT
        assert _prompt_with_user_text(FINISHED_RECEIPT_PROMPT, "  ") == (
            FINISHED_RECEIPT_PROMPT
        )

    def test_text_appends_reference_section(self) -> None:
        prompt = _prompt_with_user_text(RECOGNIZE_PROMPT, INCIDENT_TEXT)
        assert prompt.startswith(RECOGNIZE_PROMPT)
        assert "用户随图提供的文字" in prompt
        assert INCIDENT_TEXT in prompt
        assert "优先采信" in prompt


def _valid_raw_payload() -> dict[str, Any]:
    return {
        name: {"value": f"v_{name}", "confidence": 0.9}
        for name in (
            "material_name", "vendor_batch_no", "quantity", "unit",
            "supplier", "manufacturer", "plate_no", "contract_no",
        )
    }


def _valid_finished_payload() -> dict[str, Any]:
    return {
        "product_name": {"value": "替考拉宁", "confidence": 0.9},
        "product_batch_no": {"value": "TED2609002", "confidence": 0.9},
        "quantity": {"value": 75.405, "confidence": 0.9},
        "unit": {"value": "kg", "confidence": 0.9},
        "rows": [{
            "product_name": "替考拉宁", "product_batch_no": "TED2609002",
            "quantity": 75.405, "unit": "kg", "spec": None,
            "produced_at": None, "expiry": None,
        }],
    }


class _CaptureClient:
    """单次调用即返回合法 JSON 的识别客户端（记录 messages）。"""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.captured: list[dict[str, Any]] = []

    async def __aenter__(self) -> _CaptureClient:
        return self

    async def __aexit__(self, *a: Any) -> None:
        return None

    async def chat_with_tools(
        self, messages: list[dict[str, Any]], **kwargs: Any
    ) -> Any:
        self.captured.append(messages)
        cls = type("_Msg", (), {
            "content": json.dumps(self._payload, ensure_ascii=False),
            "usage": None,
            "finish_reason": None,
        })
        return cls()


class TestRecognizerUserTextInjection:
    async def test_raw_receipt_prompt_contains_user_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.modules.warehouse.agent.pipeline import recognizer

        client = _CaptureClient(_valid_raw_payload())
        monkeypatch.setattr(recognizer, "get_llm_client", lambda: client)
        await recognize_receipt("fake-image", user_text=INCIDENT_TEXT)

        assert client.captured, "识别客户端未被调用"
        prompt_text = client.captured[0][0]["content"][0]["text"]
        assert INCIDENT_TEXT in prompt_text

    async def test_raw_receipt_without_user_text_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.modules.warehouse.agent.pipeline import recognizer

        client = _CaptureClient(_valid_raw_payload())
        monkeypatch.setattr(recognizer, "get_llm_client", lambda: client)
        await recognize_receipt("fake-image")

        prompt_text = client.captured[0][0]["content"][0]["text"]
        assert prompt_text == RECOGNIZE_PROMPT

    async def test_finished_receipt_prompt_contains_user_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.modules.warehouse.agent.pipeline import recognizer

        client = _CaptureClient(_valid_finished_payload())
        monkeypatch.setattr(recognizer, "get_llm_client", lambda: client)
        result = await recognize_finished_receipt(
            "fake-image", user_text=INCIDENT_TEXT
        )

        prompt_text = client.captured[0][0]["content"][0]["text"]
        assert INCIDENT_TEXT in prompt_text
        assert result.rows[0]["product_batch_no"] == "TED2609002"
