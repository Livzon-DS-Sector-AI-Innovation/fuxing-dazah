"""S2 ticket 05 验收：gateway 图片路由 → 识别 Pipeline 全链路（主接缝）。

主接缝（spec Testing Decisions：模拟 image 事件 payload → 全链路 dry-run：
下载 mock → 识别真 LLM → 对齐真主数据 → 卡片 dry-run 捕获 → 点确认 →
submit live 写删读回）：

- test_live_image_event_full_pipeline_to_submit：image 事件 →
  gateway.handle_im_message → 占位卡片 → 后台任务（真识别+对齐+草稿）→
  确认卡片捕获 → 模拟点确认（真回调 submit_receipt → live 写 Base）→
  读回（批号/到货情况/附件列）→ 回执卡片 → finally 按 record_id 精确删除
  清理（数据安全纪律：只删本测试经 draft.target_record_id 记录的记录）；
- 降级路径（monkeypatch 隔离网络）：HEIC 格式嗅探降级「暂支持 JPG/PNG」、
  缺 image_key 直接降级、识别异常降级卡片含失败阶段 + audit error；
- media.download_im_image 单测（fake http）：URL/参数/重试后成功 + 格式嗅探。

运行：cd "E:\\dazah(仓储)\\backend" &&
      DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/dazah_whdev"
      uv run pytest tests/modules/warehouse/test_live_receipt_pipeline.py -v
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.redis as app_core_redis
from app.modules.warehouse.agent import gateway
from app.modules.warehouse.agent.cards import (
    RECEIPT_CONFIRM_CARD_TITLE,
    RECEIPT_RESULT_CARD_TITLE_OK,
)
from app.modules.warehouse.agent.pipeline.submit import ATTACHMENT_FIELD, RECEIPT_TABLE
from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter
from app.modules.warehouse.feishu import media, notification
from app.modules.warehouse.models import WarehouseAgentAudit, WarehouseAgentDraft

# 仓库根 = tests/modules/warehouse/test_x.py 往上 4 级
REPO_ROOT = Path(__file__).resolve().parents[4]
IMAGES_DIR = REPO_ROOT / ".scratch" / "s2-recognition" / "dataset" / "images"

# magic 样本（sniff_image_format 契约）
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"jpeg-payload" * 4
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"png-payload" * 4
HEIC_BYTES = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00heicmif1"


# ── fixtures（test_live_gateway.py 同款注入口）──


@pytest.fixture
async def fresh_redis(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[aioredis.Redis]:
    """每测试独立 Redis 客户端（gateway 去重用；避免模块单例跨 loop 连接）。"""
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


# ── helper ──


def _im_image_event(
    *,
    chat_id: str,
    sender_open_id: str,
    image_key: str | None = "img_v3_fake_key",
    message_type: str = "image",
) -> dict[str, Any]:
    """im.message.receive_v1 图片事件（票01 记录结构：content 为 image_key）。"""
    content: dict[str, Any] = {} if image_key is None else {"image_key": image_key}
    return {
        "sender": {
            "sender_id": {"open_id": sender_open_id, "union_id": "un_x", "user_id": "u_x"},
            "sender_type": "user",
            "tenant_key": "tenant",
        },
        "message": {
            "message_id": f"om_{uuid.uuid4().hex}",
            "root_id": "",
            "parent_id": "",
            "create_time": "1700000000000",
            "chat_id": chat_id,
            "chat_type": "p2p",
            "message_type": message_type,
            "content": json.dumps(content, ensure_ascii=False),
            "mentions": [],
        },
    }


def _card_action_event(
    *, operator_open_id: str, action: str, draft_id: str, scene: str
) -> dict[str, Any]:
    """card.action.trigger 的 event dict（gateway 收到的是内层 event）。"""
    return {
        "operator": {"open_id": operator_open_id, "union_id": "un", "user_id": "u"},
        "token": "t",
        "action": {
            "tag": "button",
            "value": {"action": action, "scene": scene, "draft_id": draft_id},
        },
        "host": "im",
    }


def _card_of(payload: dict[str, str]) -> dict[str, Any]:
    return json.loads(payload["content"])


def _interactive_cards(sends: list[dict[str, str]]) -> list[dict[str, Any]]:
    """捕获 payload → 交互卡片 dict 列表。"""
    return [
        json.loads(payload["content"])
        for payload in sends
        if payload.get("msg_type") == "interactive"
    ]


def _card_content(card: dict[str, Any]) -> str:
    return "\n".join(
        element.get("content") or ""
        for element in card.get("elements", [])
        if isinstance(element, dict)
    )


def _confirm_buttons(card: dict[str, Any]) -> list[dict[str, Any]]:
    for element in card.get("elements", []):
        if isinstance(element, dict) and element.get("tag") == "action":
            return list(element.get("actions") or [])
    return []


async def _drain_background_tasks(timeout: float = 600.0) -> None:
    """等待 gateway 后台图片任务全部收尾（超时视为失败）。"""
    tasks = [t for t in list(gateway._background_tasks) if not t.done()]
    if not tasks:
        return
    _done, pending = await asyncio.wait(tasks, timeout=timeout)
    assert not pending, f"后台任务超时未完成: {pending}"


async def _gateway_image_audits(db: AsyncSession) -> list[WarehouseAgentAudit]:
    rows = await db.execute(
        select(WarehouseAgentAudit).where(WarehouseAgentAudit.tool_name == "gateway")
    )
    return list(rows.scalars().all())


def _dataset_image() -> Path:
    """主接缝用图：批号/数量识别完整的首选样本（票04 live submit 同款），缺失回退首张。"""
    preferred = IMAGES_DIR / "rec0aItKXJ.jpg"
    if preferred.exists():
        return preferred
    return sorted(IMAGES_DIR.glob("*.jpg"))[0]


# ── 1. 主接缝：image 事件 → 占位 → 识别对齐 → 确认卡片 → 确认 → live 写删读回 ──


@pytest.mark.skipif(
    not IMAGES_DIR.exists() or not any(IMAGES_DIR.glob("*.jpg")),
    reason="识别数据集缺失（scripts/build_recognition_dataset.py 先产出）",
)
async def test_live_image_event_full_pipeline_to_submit(
    gateway_db: AsyncSession,
    captured_sends: list[dict[str, str]],
    fresh_redis: aioredis.Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """全链路：im 下载 mock（真图字节）→ 真识别/对齐 → 确认卡片 → 点确认 →
    live 写 Base → 读回 → 回执卡片 → record_id 精确删除清理。"""
    image_path = _dataset_image()
    image_bytes = image_path.read_bytes()

    async def fake_download_im_image(message_id: str, file_key: str) -> bytes:
        return image_bytes

    # im 下载 mock（卡片发送已捕获）；原图 upload/对齐/LLM/submit 均真调
    monkeypatch.setattr(media, "download_im_image", fake_download_im_image)

    chat_id = f"oc_p2p_{uuid.uuid4().hex[:10]}"
    open_id = f"ou_pipeline_{uuid.uuid4().hex[:8]}"
    event = _im_image_event(chat_id=chat_id, sender_open_id=open_id)

    await gateway.handle_im_message(event)

    # 占位卡片先行（正在识别）
    assert len(captured_sends) == 1
    assert captured_sends[0]["receive_id_type"] == "open_id"
    assert captured_sends[0]["receive_id"] == open_id
    placeholder = _card_of(captured_sends[0])
    assert "正在识别" in placeholder["header"]["title"]["content"]

    # 后台任务：真 LLM 识别 + 真主数据对齐 + 草稿落库 + 确认卡片
    await _drain_background_tasks()

    assert len(captured_sends) == 2, "后台任务完成后应再发确认卡片"
    confirm_card = _card_of(captured_sends[1])
    assert confirm_card["header"]["title"]["content"] == RECEIPT_CONFIRM_CARD_TITLE
    buttons = _confirm_buttons(confirm_card)
    assert buttons and buttons[0]["value"]["scene"] == "receipt"
    assert buttons[0]["value"]["action"] == "confirm"
    draft_id = buttons[0]["value"]["draft_id"]

    draft = await gateway_db.get(WarehouseAgentDraft, uuid.UUID(draft_id))
    assert draft is not None
    assert draft.status == "pending_confirm"
    # 真识别结果落库（首选样本批号必出，票04 live 同款契约）
    recognized = draft.recognized if isinstance(draft.recognized, dict) else {}
    assert str((recognized.get("vendor_batch_no") or {}).get("value") or "").strip()
    # 对齐落库（真主数据）
    aligned = draft.aligned if isinstance(draft.aligned, dict) else {}
    assert aligned.get("match_confidence") in ("exact", "prefix", "fuzzy")
    # 原图 upload_image 挂 Base 成功 → source_image 有 token（submit 写附件列）
    assert (draft.source_image or "").strip()

    # 模拟点确认（走真回调 submit_receipt → live 写 material_receipt）
    update = await gateway.handle_card_action_trigger(
        _card_action_event(
            operator_open_id=open_id,
            action="confirm",
            draft_id=draft_id,
            scene="receipt",
        )
    )
    assert update is not None
    assert "已登记" in update["elements"][0]["content"]
    assert draft.status == "submitted"

    record_id = draft.target_record_id or ""
    adapter = WarehouseBitableAdapter()
    try:
        # record_id 精确记录（数据安全纪律：finally 只删本测试创建的记录）
        assert record_id.startswith("rec")
        record = await adapter.get_record(RECEIPT_TABLE, record_id)
        fields = record["fields"]
        assert fields.get("厂家批号"), "Base 记录缺厂家批号"
        assert fields.get("到货情况") == "到货物料"
        # 原图附件列写入（spec 决策 3）
        assert fields.get(ATTACHMENT_FIELD), "Base 记录缺原图附件"

        # 回执卡片（dry-run 捕获，发发起人私聊）
        cards = _interactive_cards(captured_sends)
        assert len(cards) == 3  # 占位 + 确认 + 回执
        result_card = cards[-1]
        assert result_card["header"]["title"]["content"] == RECEIPT_RESULT_CARD_TITLE_OK
        assert record_id in _card_content(result_card)

        # audit 链：gateway ok（含 draft_no）+ submit_receipt ok
        gateway_audits = await _gateway_image_audits(gateway_db)
        assert any(
            a.result_status == "ok" and a.args_summary.get("draft_no") == draft.draft_no
            for a in gateway_audits
        )
        submit_rows = await gateway_db.execute(
            select(WarehouseAgentAudit).where(
                WarehouseAgentAudit.tool_name == "submit_receipt",
                WarehouseAgentAudit.draft_id == draft.id,
            )
        )
        submit_audits = list(submit_rows.scalars().all())
        assert len(submit_audits) == 1
        assert submit_audits[0].result_status == "ok"
    finally:
        if record_id:
            await adapter.delete_record(RECEIPT_TABLE, record_id)  # 精确清理
        await fresh_redis.delete(f"feishu:msg:{event['message']['message_id']}")


# ── 2. 降级路径（monkeypatch 隔离网络）──


async def test_image_heic_format_degrades(
    gateway_db: AsyncSession,
    captured_sends: list[dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HEIC 图（手机拍照常态）→ 嗅探命中 → 「暂支持 JPG/PNG」降级，不进识别。"""

    async def fake_download(message_id: str, file_key: str) -> bytes:
        return HEIC_BYTES

    async def boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("格式不支持时不应触发识别")

    monkeypatch.setattr(media, "download_im_image", fake_download)
    monkeypatch.setattr(gateway, "recognize_receipt", boom)
    event = _im_image_event(chat_id="oc_p2p_heic", sender_open_id="ou_heic")

    await gateway.handle_im_message(event)
    await _drain_background_tasks()

    assert len(captured_sends) == 2  # 占位 + 降级卡片
    degrade = _card_of(captured_sends[1])
    content = _card_content(degrade)
    assert "JPG" in content and "PNG" in content
    audits = await _gateway_image_audits(gateway_db)
    assert any(
        a.result_status == "error" and a.error_code == "unsupported_image_format"
        for a in audits
    )


async def test_image_event_without_image_key_degrades(
    gateway_db: AsyncSession, captured_sends: list[dict[str, str]]
) -> None:
    """content 缺 image_key → 无法下载定位，直接降级（无占位、无后台任务）。"""
    event = _im_image_event(chat_id="oc_p2p_nokey", sender_open_id="ou_nokey", image_key=None)

    await gateway.handle_im_message(event)
    await _drain_background_tasks()

    assert len(captured_sends) == 1  # 只有降级卡片
    degrade = _card_of(captured_sends[0])
    assert "读取图片信息" in _card_content(degrade)
    audits = await _gateway_image_audits(gateway_db)
    assert any(
        a.result_status == "error" and a.error_code == "missing_image_key"
        for a in audits
    )


async def test_image_recognition_failure_degrades(
    gateway_db: AsyncSession,
    captured_sends: list[dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """识别阶段异常 → 降级卡片含失败阶段「图片识别」+ audit error。"""

    async def fake_download(message_id: str, file_key: str) -> bytes:
        return PNG_BYTES

    async def boom(image_b64: str, content_type: str = "image/jpeg") -> None:
        raise RuntimeError("llm boom")

    monkeypatch.setattr(media, "download_im_image", fake_download)
    monkeypatch.setattr(gateway, "recognize_receipt", boom)
    event = _im_image_event(chat_id="oc_p2p_fail", sender_open_id="ou_fail")

    await gateway.handle_im_message(event)
    await _drain_background_tasks()

    assert len(captured_sends) == 2  # 占位 + 失败降级卡片
    failed = _card_of(captured_sends[1])
    assert "图片识别失败" in failed["header"]["title"]["content"]
    assert "图片识别" in _card_content(failed)  # 失败阶段
    audits = await _gateway_image_audits(gateway_db)
    assert any(
        a.result_status == "error" and a.error_code == "RuntimeError" for a in audits
    )


# ── 3. media.download_im_image 单测（fake http，不触网）──


class _FakeResp:
    def __init__(self, status_code: int = 200, content: bytes = b"") -> None:
        self.status_code = status_code
        self.content = content
        self.text = ""


class _FakeHttp:
    def __init__(self, responses: list[_FakeResp]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def get(self, url: str, **kwargs: Any) -> _FakeResp:
        self.calls.append({"url": url, **kwargs})
        return self.responses.pop(0)


def test_sniff_image_format() -> None:
    """magic 字节嗅探：jpeg/png/heic/unknown。"""
    assert media.sniff_image_format(JPEG_BYTES) == "jpeg"
    assert media.sniff_image_format(PNG_BYTES) == "png"
    assert media.sniff_image_format(HEIC_BYTES) == "heic"
    assert media.sniff_image_format(b"not-an-image-at-all") == "unknown"
    assert media.sniff_image_format(b"") == "unknown"


async def test_download_im_image_hits_im_resource_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """URL/查询参数/凭证头正确；HTTP 500 后重试一次成功（重试契约）。"""
    fake_http = _FakeHttp([_FakeResp(500, b""), _FakeResp(200, JPEG_BYTES)])
    monkeypatch.setattr(media, "_get_http", lambda: fake_http)
    monkeypatch.setattr(media, "_credentials", lambda *a, **k: ("app_id_x", "secret_x"))

    async def fake_token(app_id: str, app_secret: str) -> str:
        return "tenant_token_x"

    monkeypatch.setattr(media, "get_tenant_token", fake_token)

    content = await media.download_im_image("om_msg_x", "img_key_x")
    assert content == JPEG_BYTES
    assert len(fake_http.calls) == 2  # 首次 500 → 重试成功
    call = fake_http.calls[-1]
    assert call["url"] == (
        "https://open.feishu.cn/open-apis/im/v1/messages/om_msg_x/resources/img_key_x"
    )
    assert call["params"] == {"type": "image"}
    assert call["headers"]["Authorization"] == "Bearer tenant_token_x"
