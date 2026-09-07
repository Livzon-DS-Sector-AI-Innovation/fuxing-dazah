"""S2 ticket 03 验收：Draft 状态机 + 确认卡片 + 对话修改。

单测（真库 whdev + 事务回滚隔离；发送捕获不触网）：
- 状态机全迁移路径：created→aligned→pending_confirm→confirmed（票03 桩）/
  cancelled（卡片按钮与 draft_flow 两条路径）/ expired（TTL 清扫）；
- 非法迁移拒绝（终态/跳步）+ 幂等（重复 confirm/cancel 拒绝）；
- draft_no 序号（WR+日期+当日序号递增）；
- 确认卡片渲染：必提/选提分区、低置信 ⚠、物料对齐行/未匹配警告、
  按钮 value（scene=receipt/action/draft_id）、缺字段降级；
- update_draft 组件直测：字段别名映射、数量数字化、权限/状态校验、
  重发确认卡片。

live 主接缝前段（真 LLM + 真主数据，数据集缺失自动 skip）：
- 测试集真图 → recognize_receipt → align_receipt → create_receipt_draft →
  mark_aligned → send_confirm_card（dry-run 捕获）→ drafts 全程状态落库。

live 对话修改（经 gateway + 真 Runner LLM）：
- 构造 aligned 草稿的用户会话 → 文本「把数量改成 200」→ update_draft 被调用
  （audit）+ aligned.quantity 更新 + 新确认卡片（dry-run 捕获）。

运行：cd "E:\\dazah(仓储)\\backend" &&
      DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/dazah_whdev"
      uv run pytest tests/modules/warehouse/test_live_draft_flow.py -v
"""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.redis as app_core_redis
from app.modules.warehouse.agent import confirm, gateway
from app.modules.warehouse.agent import pipeline as pipeline_module
from app.modules.warehouse.agent import repository as agent_repository
from app.modules.warehouse.agent import runner as runner_module
from app.modules.warehouse.agent.cards import (
    RECEIPT_CONFIRM_CARD_TITLE,
    render_receipt_confirm_card,
)
from app.modules.warehouse.agent.pipeline.draft_flow import (
    DraftFlowError,
    cancel_draft,
    create_receipt_draft,
    expire_stale,
    mark_aligned,
    send_confirm_card,
)
from app.modules.warehouse.agent.pipeline.recognizer import (
    build_receipt,
    recognize_receipt,
)
from app.modules.warehouse.agent.tools import draft_update
from app.modules.warehouse.feishu import notification
from app.modules.warehouse.models import (
    WarehouseAgentAudit,
    WarehouseAgentDraft,
)

# 仓库根 = tests/modules/warehouse/test_x.py 往上 4 级
REPO_ROOT = Path(__file__).resolve().parents[4]
IMAGES_DIR = REPO_ROOT / ".scratch" / "s2-recognition" / "dataset" / "images"

RECEIPT_SCENE = "receipt"


# ── fixtures：db 注入 / 发送捕获 / Runner 单例 / Redis ──


@pytest.fixture
def agent_db(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> AsyncSession:
    """gateway/runner/draft_update 三处 _db_session → 包装测试 session。

    update_draft 在 Runner 工具循环内自开事务、Runner 审计与待处理摘要
    同理——都指向同一测试 session（不 commit），随 fixture 回滚隔离。
    """

    @asynccontextmanager
    async def _patched() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(gateway, "_db_session", _patched)
    monkeypatch.setattr(runner_module, "_db_session", _patched)
    monkeypatch.setattr(draft_update, "_db_session", _patched)
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


@pytest.fixture(autouse=True)
def fresh_runner(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """每测试重置 Runner 单例（pytest-asyncio 每测试新建 loop，连接池绑定）。"""
    monkeypatch.setattr(runner_module, "_runner", None)
    yield
    runner_module._runner = None


@pytest.fixture
async def fresh_redis(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[aioredis.Redis]:
    """每测试独立 Redis 客户端并替换 app.core.redis.redis_client（去重用）。"""
    from app.core.config import get_settings

    client = aioredis.from_url(get_settings().REDIS_URL, decode_responses=True)
    monkeypatch.setattr(app_core_redis, "redis_client", client)
    yield client
    await client.aclose()


# ── 测试数据工厂 ──


def _recognized_payload() -> dict[str, Any]:
    """识别 JSON dict（model_dump 同构；含低置信/空值字段覆盖渲染分支）。"""
    return {
        "material_name": {"value": "硫酸铵", "confidence": 0.95},
        "vendor_batch_no": {"value": "2511", "confidence": 0.55},
        "quantity": {"value": "32000", "confidence": 0.9},
        "unit": {"value": "Kg", "confidence": 0.92},
        "supplier": {"value": "福州优傲材料科技有限公司", "confidence": 0.85},
        "manufacturer": {"value": "福建天辰耀隆新材料有限公司", "confidence": 0.8},
        "plate_no": {"value": None, "confidence": 0.1},
        "contract_no": {"value": "PO2501150179", "confidence": 0.88},
        "package_spec": {"value": "50Kg/包", "confidence": 0.75},
        "remark": {"value": None, "confidence": 0.0},
    }


def _aligned_receipt(recognized: Any, *, match: str = "exact") -> Any:
    """构造 AlignedReceipt（假主数据，单测不依赖真 Base）。"""
    from app.modules.warehouse.agent.pipeline.aligner import AlignedReceipt

    return AlignedReceipt(
        recognized=recognized,
        aligned={
            "material_name": "硫酸铵",
            "code": "C001",
            "level": "工业级",
            "material_category": "原辅料",
            "sub_category": "固体（原料库）",
            "unit_suggestion": "吨",
            "supplier_matched": False,
            "manufacturer_matched": False,
        },
        match_confidence=match,
        match_detail={"matched_by": match, "key": "硫酸铵"},
    )


async def _seed_aligned_draft(
    db: AsyncSession, *, open_id: str, quantity: Any = "100"
) -> WarehouseAgentDraft:
    """种子：识别落库 + 对齐落库（status=aligned，卡片未发）。"""
    payload = _recognized_payload()
    payload["quantity"] = {"value": quantity, "confidence": 0.9}
    recognized = build_receipt(payload)
    draft = await create_receipt_draft(
        db,
        recognized=recognized,
        image_file_token="img_v3_seed",
        open_id=open_id,
        chat_id="oc_seed",
    )
    await mark_aligned(db, draft, _aligned_receipt(recognized))
    return draft


async def _draft_flow_audits(db: AsyncSession, draft_id: uuid.UUID) -> list[WarehouseAgentAudit]:
    # 不按 created_at 排序：PostgreSQL now() 为事务起始时间，同事务内恒定
    # （测试单事务写多条 audit 时排序无意义）——断言一律顺序无关
    rows = await db.execute(
        select(WarehouseAgentAudit).where(
            WarehouseAgentAudit.tool_name == "draft_flow",
            WarehouseAgentAudit.draft_id == draft_id,
        )
    )
    return list(rows.scalars().all())


def _card_of(payload: dict[str, str]) -> dict[str, Any]:
    card: dict[str, Any] = json.loads(payload["content"])
    return card


def _confirm_card_payloads(sends: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        _card_of(p)
        for p in sends
        if _card_of(p).get("header", {}).get("title", {}).get("content")
        == RECEIPT_CONFIRM_CARD_TITLE
    ]


# ── 1. 状态机：创建/对齐/迁移/audit/序号 ──


async def test_create_receipt_draft_persists(
    db_session: AsyncSession,
) -> None:
    """识别落库：created 状态 + recognized JSONB + source_image + TTL + audit。"""
    recognized = build_receipt(_recognized_payload())
    before = datetime.now(UTC)
    draft = await create_receipt_draft(
        db_session,
        recognized=recognized,
        image_file_token="img_v3_test",
        open_id="ou_creator",
        chat_id="oc_chat1",
    )
    after = datetime.now(UTC)

    assert draft.draft_no.startswith("WR")
    assert len(draft.draft_no) == 14  # WR+YYYYMMDD(8)+-(1)+NNN(3)
    assert draft.scene == RECEIPT_SCENE
    assert draft.status == "created"
    assert draft.source_image == "img_v3_test"
    assert draft.created_by_open_id == "ou_creator"
    assert draft.recognized["material_name"] == {"value": "硫酸铵", "confidence": 0.95}
    assert draft.aligned == {}
    ttl = draft.expires_at
    assert ttl is not None and before + timedelta(seconds=590) < ttl < after + timedelta(seconds=610)

    audits = await _draft_flow_audits(db_session, draft.id)
    assert len(audits) == 1
    assert audits[0].args_summary["action"] == "create"
    assert audits[0].result_status == "ok"
    assert audits[0].draft_id == draft.id


async def test_create_draft_no_sequence_increments(db_session: AsyncSession) -> None:
    """同日多张草稿序号递增（WR+YYYYMMDD-NNN，仿 plans WP）。"""
    recognized = build_receipt(_recognized_payload())
    first = await create_receipt_draft(
        db_session, recognized=recognized, open_id="ou_seq"
    )
    second = await create_receipt_draft(
        db_session, recognized=recognized, open_id="ou_seq"
    )
    assert first.draft_no[:10] == second.draft_no[:10]  # 同日期前缀
    seq_first = int(first.draft_no.rsplit("-", 1)[1])
    seq_second = int(second.draft_no.rsplit("-", 1)[1])
    assert seq_second == seq_first + 1


async def test_mark_aligned_transition_and_payload(db_session: AsyncSession) -> None:
    """created→aligned：aligned JSONB = 对齐字段 + match_confidence + match_detail。"""
    recognized = build_receipt(_recognized_payload())
    draft = await create_receipt_draft(
        db_session, recognized=recognized, open_id="ou_align"
    )
    await mark_aligned(db_session, draft, _aligned_receipt(recognized))

    assert draft.status == "aligned"
    assert draft.aligned["material_name"] == "硫酸铵"
    assert draft.aligned["code"] == "C001"
    assert draft.aligned["match_confidence"] == "exact"
    assert draft.aligned["match_detail"]["key"] == "硫酸铵"
    # recognized 不被对齐改写（审计可回溯）
    assert draft.recognized["material_name"]["value"] == "硫酸铵"

    audits = await _draft_flow_audits(db_session, draft.id)
    assert sorted(a.args_summary["action"] for a in audits) == [
        "create",
        "mark_aligned",
    ]
    mark_audit = next(a for a in audits if a.args_summary["action"] == "mark_aligned")
    assert mark_audit.args_summary["from"] == "created"
    assert mark_audit.args_summary["to"] == "aligned"


# ── 2. 非法迁移 + 幂等 ──


async def test_illegal_transitions_rejected(db_session: AsyncSession) -> None:
    """跳步/终态再迁移一律 DraftFlowError（幂等 = 状态前置校验）。"""
    recognized = build_receipt(_recognized_payload())
    draft = await create_receipt_draft(
        db_session, recognized=recognized, open_id="ou_illegal"
    )

    # created 直接发确认卡片（跳过对齐）→ 拒绝
    with pytest.raises(DraftFlowError):
        await send_confirm_card(db_session, draft, chat_id="oc_x")
    await mark_aligned(db_session, draft, _aligned_receipt(recognized))
    # aligned 重复对齐 → 拒绝
    with pytest.raises(DraftFlowError):
        await mark_aligned(db_session, draft, _aligned_receipt(recognized))
    await send_confirm_card(db_session, draft, chat_id="oc_x")
    assert draft.status == "pending_confirm"
    # 终态不可再迁移：手工置 cancelled 后 cancel/expired 均拒绝
    draft.status = "cancelled"
    with pytest.raises(DraftFlowError):
        await cancel_draft(db_session, draft)
    with pytest.raises(DraftFlowError):
        await send_confirm_card(db_session, draft, chat_id="oc_x")


async def test_resend_confirm_card_allowed(
    db_session: AsyncSession, captured_sends: list[dict[str, str]]
) -> None:
    """pending_confirm→pending_confirm（对话修改后重发）合法且记 resend 审计。"""
    draft = await _seed_aligned_draft(db_session, open_id="ou_resend")
    await send_confirm_card(db_session, draft, chat_id="oc_resend")
    await send_confirm_card(db_session, draft, chat_id="oc_resend")

    assert draft.status == "pending_confirm"
    cards = _confirm_card_payloads(captured_sends)
    assert len(cards) == 2
    audits = await _draft_flow_audits(db_session, draft.id)
    send_audits = [a for a in audits if a.args_summary["action"] == "send_confirm_card"]
    assert len(send_audits) == 2
    assert sorted(a.args_summary["resend"] for a in send_audits) == [False, True]


async def test_confirm_via_handle_action_and_repeat_rejected(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """确认走 ConfirmService → confirmed；重复确认拒绝。

    票04 起回调为 submit_receipt 真身（写 Base）——确认门机制测试注入
    假回调，真身 live 流程见 test_live_submit.py。
    """
    from app.modules.warehouse.agent.pipeline import submit as submit_module

    async def fake_submit(db: AsyncSession, draft: WarehouseAgentDraft) -> str | None:
        return "假提交完成"

    monkeypatch.setattr(submit_module, "submit_receipt", fake_submit)
    draft = await _seed_aligned_draft(db_session, open_id="ou_confirm")
    await send_confirm_card(db_session, draft, chat_id="oc_confirm")

    outcome = await confirm.handle_action(
        db_session,
        value={
            "scene": RECEIPT_SCENE,
            "action": "confirm",
            "draft_id": str(draft.id),
        },
        operator_open_id="ou_confirm",
    )
    assert outcome.ok is True
    assert outcome.status == "confirmed"
    assert outcome.message == "假提交完成"
    assert draft.status == "confirmed"

    # 幂等：confirmed 后再点确认 → 拒绝（not_pending）
    outcome2 = await confirm.handle_action(
        db_session,
        value={
            "scene": RECEIPT_SCENE,
            "action": "confirm",
            "draft_id": str(draft.id),
        },
        operator_open_id="ou_confirm",
    )
    assert outcome2.ok is False
    assert outcome2.status == "invalid"
    assert draft.status == "confirmed"


async def test_cancel_via_handle_action_and_repeat_rejected(
    db_session: AsyncSession,
) -> None:
    """取消走 ConfirmService → cancelled；重复取消拒绝。"""
    draft = await _seed_aligned_draft(db_session, open_id="ou_cancel")
    await send_confirm_card(db_session, draft, chat_id="oc_cancel")

    outcome = await confirm.handle_action(
        db_session,
        value={
            "scene": RECEIPT_SCENE,
            "action": "cancel",
            "draft_id": str(draft.id),
        },
        operator_open_id="ou_cancel",
    )
    assert outcome.ok is True
    assert outcome.status == "cancelled"
    assert draft.status == "cancelled"

    outcome2 = await confirm.handle_action(
        db_session,
        value={
            "scene": RECEIPT_SCENE,
            "action": "cancel",
            "draft_id": str(draft.id),
        },
        operator_open_id="ou_cancel",
    )
    assert outcome2.ok is False
    assert outcome2.status == "invalid"


async def test_cancel_draft_via_flow(db_session: AsyncSession) -> None:
    """draft_flow.cancel：aligned 直取消（卡片外取消入口）+ audit。"""
    draft = await _seed_aligned_draft(db_session, open_id="ou_flowcancel")
    await cancel_draft(db_session, draft, operator_open_id="ou_flowcancel")
    assert draft.status == "cancelled"
    audits = await _draft_flow_audits(db_session, draft.id)
    cancel_audits = [a for a in audits if a.args_summary["action"] == "cancel"]
    assert len(cancel_audits) == 1
    assert cancel_audits[0].args_summary["to"] == "cancelled"
    assert cancel_audits[0].args_summary["operator"] == "ou_flowcancel"


# ── 3. TTL 过期 ──


async def test_expire_stale_marks_only_stale(db_session: AsyncSession) -> None:
    """expire_stale：仅过期时间已过的活跃草稿置 expired；未到期/终态不动。"""
    recognized = build_receipt(_recognized_payload())
    stale_created = await create_receipt_draft(
        db_session, recognized=recognized, open_id="ou_exp1"
    )
    fresh_aligned = await _seed_aligned_draft(db_session, open_id="ou_exp2")
    stale_pending = await _seed_aligned_draft(db_session, open_id="ou_exp3")
    await send_confirm_card(db_session, stale_pending, chat_id="oc_exp")
    stale_cancelled = await _seed_aligned_draft(db_session, open_id="ou_exp4")
    await cancel_draft(db_session, stale_cancelled)

    past = datetime.now(UTC) - timedelta(seconds=1)
    stale_created.expires_at = past
    stale_pending.expires_at = past
    stale_cancelled.expires_at = past
    await db_session.flush()

    count = await expire_stale(db_session)
    assert count >= 2  # 本用例 2 条 + 库中可能存在的其他历史过期活跃草稿
    assert stale_created.status == "expired"
    assert stale_pending.status == "expired"
    assert fresh_aligned.status == "aligned"  # 未到期不动
    assert stale_cancelled.status == "cancelled"  # 终态不动

    audits = await _draft_flow_audits(db_session, stale_created.id)
    expire_audits = [a for a in audits if a.args_summary["action"] == "expire"]
    assert len(expire_audits) == 1
    assert expire_audits[0].args_summary["to"] == "expired"


async def test_expired_draft_confirm_rejected(db_session: AsyncSession) -> None:
    """pending_confirm 草稿 TTL 已过 → 点击确认被拒并置 expired。"""
    draft = await _seed_aligned_draft(db_session, open_id="ou_ttl")
    await send_confirm_card(db_session, draft, chat_id="oc_ttl")
    draft.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()

    outcome = await confirm.handle_action(
        db_session,
        value={
            "scene": RECEIPT_SCENE,
            "action": "confirm",
            "draft_id": str(draft.id),
        },
        operator_open_id="ou_ttl",
    )
    assert outcome.ok is False
    assert outcome.status == "expired"
    assert draft.status == "expired"


async def test_send_failure_keeps_pending_and_audits(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """卡片发送失败：迁移保持 pending_confirm + audit 记 send_failed（可重试）。"""

    async def fail_send(payload: dict[str, str]) -> str | None:
        return None

    monkeypatch.setattr(notification, "_send_create", fail_send)
    draft = await _seed_aligned_draft(db_session, open_id="ou_sendfail")
    await send_confirm_card(db_session, draft, chat_id="oc_sendfail")

    assert draft.status == "pending_confirm"
    audits = await _draft_flow_audits(db_session, draft.id)
    send_audits = [a for a in audits if a.args_summary["action"] == "send_confirm_card"]
    assert len(send_audits) == 1
    assert send_audits[0].result_status == "error"
    assert send_audits[0].error_code == "send_failed"


# ── 4. 确认卡片渲染 ──


def _render_card(
    *, recognized: dict[str, Any], aligned: dict[str, Any], status: str = "pending_confirm"
) -> dict[str, Any]:
    # id 显式传入：ORM Python 侧 default=uuid.uuid4 在 flush 时才应用，
    # 未落库实例的 id 为 None（卡片 draft_id 渲染输入需真实 uuid）
    draft = WarehouseAgentDraft(
        id=uuid.uuid4(),
        draft_no="WR20990101-042",
        scene=RECEIPT_SCENE,
        status=status,
        recognized=recognized,
        aligned=aligned,
    )
    return render_receipt_confirm_card(draft)


def test_receipt_card_sections_warn_and_buttons() -> None:
    """必提/选提分区 + 低置信 ⚠ + 空值 — + 物料对齐行 + 按钮 value。"""
    card = _render_card(recognized=_recognized_payload(), aligned={
        "material_name": "硫酸铵",
        "code": "C001",
        "material_category": "原辅料",
        "match_confidence": "exact",
    })
    assert card["header"]["title"]["content"] == RECEIPT_CONFIRM_CARD_TITLE
    content = card["elements"][0]["content"]
    # 必提分区：高置信无 ⚠、低置信 ⚠、缺失必提 — ⚠
    assert "必提信息" in content
    assert "1. 物料名称：硫酸铵" in content  # conf 0.95 无 ⚠
    assert "2. 厂家批号：2511 ⚠" in content  # conf 0.55 < 0.7
    assert "3. 数量：32000" in content
    assert "7. 车牌：— ⚠" in content  # 必提缺失（conf 0）高亮
    # 选提分区：有值展示、缺失 —（不加 ⚠）
    assert "选填信息" in content
    assert "1. 包装规格：50Kg/包" in content  # conf 0.75 ≥ 0.7
    assert "2. 生产日期：—" in content
    assert "2. 生产日期：— ⚠" not in content
    # 物料对齐行（非 none）：代码 + 大类
    assert "**物料对齐**：硫酸铵（代码 C001｜大类 原辅料）" in content
    # 修改引导（[修改] 无按钮，引导文本对话）
    assert "数量改成 200" in content
    # 按钮 value：scene=receipt + draft_id + confirm/cancel
    actions = card["elements"][2]["actions"]
    confirm_btn, cancel_btn = actions[0], actions[1]
    assert confirm_btn["value"] == {
        "scene": RECEIPT_SCENE,
        "draft_id": confirm_btn["value"]["draft_id"],
        "action": "confirm",
    }
    assert confirm_btn["text"]["content"] == "✅ 确认入库"
    assert cancel_btn["value"]["action"] == "cancel"
    assert len(confirm_btn["value"]["draft_id"]) == 36  # uuid4 str


def test_receipt_card_match_none_warning() -> None:
    """match_confidence=none → 未匹配主数据警告行，不显示对齐结果行。"""
    card = _render_card(
        recognized=_recognized_payload(),
        aligned={"material_name": "硫酸铵", "match_confidence": "none"},
    )
    content = card["elements"][0]["content"]
    assert "⚠ 物料名称未匹配主数据，请核对" in content
    assert "物料对齐" not in content


def test_receipt_card_degrade_missing_fields() -> None:
    """防御：recognized/aligned 全缺 → 不抛错，全 — 展示，按钮仍在。"""
    card = _render_card(recognized={}, aligned={})
    content = card["elements"][0]["content"]
    assert "1. 物料名称：— ⚠" in content
    assert "1. 包装规格：—" in content
    assert "物料对齐" not in content
    assert card["elements"][2]["actions"][0]["value"]["action"] == "confirm"


def test_receipt_card_manual_override_no_warn() -> None:
    """对话修改后的字段（aligned 覆盖）显示新值且不再加 ⚠。"""
    card = _render_card(
        recognized=_recognized_payload(),
        aligned={"material_name": "硫酸铵", "quantity": 200, "match_confidence": "exact",
                 "code": "C001", "material_category": "原辅料"},
    )
    content = card["elements"][0]["content"]
    assert "3. 数量：200" in content  # 人工改过，无 ⚠
    assert "3. 数量：200 ⚠" not in content


# ── 5. update_draft 组件直测 ──


async def test_update_draft_by_no_updates_and_resends(
    agent_db: AsyncSession, captured_sends: list[dict[str, str]]
) -> None:
    """指定 draft_no：字段写入 aligned + 状态回 pending_confirm + 重发卡片。"""
    draft = await _seed_aligned_draft(agent_db, open_id="ou_upd1")
    result = await draft_update.update_draft(
        draft.draft_no,
        {"数量": "200", "厂家批号": "B999"},
        _ctx={"open_id": "ou_upd1", "chat_id": "oc_upd1"},
    )
    assert "error" not in result
    assert result["status"] == "pending_confirm"
    assert result["draft_no"] == draft.draft_no
    assert result["updated"]["quantity"] == 200  # 数字化
    assert result["updated"]["vendor_batch_no"] == "B999"
    assert draft.status == "pending_confirm"

    cards = _confirm_card_payloads(captured_sends)
    assert len(cards) == 1
    content = cards[0]["elements"][0]["content"]
    assert "3. 数量：200" in content
    assert "2. 厂家批号：B999" in content


async def test_update_draft_default_latest_and_errors(
    agent_db: AsyncSession, captured_sends: list[dict[str, str]]
) -> None:
    """draft_no 缺省取最近 receipt 草稿；未知字段/非本人/不可改状态返回 error。"""
    stale = await _seed_aligned_draft(agent_db, open_id="ou_upd2", quantity="10")
    latest = await _seed_aligned_draft(agent_db, open_id="ou_upd2", quantity="20")
    # 同事务内 created_at（事务起始 now()）恒定——显式拉开保证"最近"排序确定
    now = datetime.now(UTC)
    stale.created_at = now - timedelta(seconds=60)
    latest.created_at = now
    await agent_db.flush()

    # 缺省 → 命中最近一张（quantity=20）
    result = await draft_update.update_draft(
        None, {"数量": 30}, _ctx={"open_id": "ou_upd2", "chat_id": "oc_upd2"}
    )
    assert "error" not in result
    assert result["draft_no"] == latest.draft_no
    assert stale.status == "aligned"  # 未被误改
    assert float(latest.aligned["quantity"]) == 30

    # 未知字段 → error 引导
    bad_field = await draft_update.update_draft(
        None, {"颜色": "红"}, _ctx={"open_id": "ou_upd2", "chat_id": "oc_upd2"}
    )
    assert "不支持的字段" in bad_field["error"]

    # 非发起人 → error
    foreign = await draft_update.update_draft(
        latest.draft_no, {"数量": 1}, _ctx={"open_id": "ou_other", "chat_id": "oc_x"}
    )
    assert "仅发起人可修改" in foreign["error"]

    # created 状态（未对齐）不可改
    recognized = build_receipt(_recognized_payload())
    created = await create_receipt_draft(
        agent_db, recognized=recognized, open_id="ou_upd2"
    )
    not_mutable = await draft_update.update_draft(
        created.draft_no, {"数量": 1}, _ctx={"open_id": "ou_upd2", "chat_id": "oc_x"}
    )
    assert "不可修改" in not_mutable["error"]

    # 不存在的草稿
    missing = await draft_update.update_draft(
        "WR20990101-999", {"数量": 1}, _ctx={"open_id": "ou_upd2", "chat_id": "oc_x"}
    )
    assert "不存在" in missing["error"]


async def test_list_actionable_drafts_includes_aligned(db_session: AsyncSession) -> None:
    """S1 修5 回归：list_actionable_drafts 纳入 aligned 状态（update_draft 依赖）。"""
    draft = await _seed_aligned_draft(db_session, open_id="ou_list")
    rows = await agent_repository.list_actionable_drafts(db_session, "ou_list")
    assert [d.id for d in rows] == [draft.id]


# ── 6. live 主接缝前段：真图 → 识别 → 对齐 → 草稿 → 确认卡片 ──


@pytest.mark.skipif(
    not IMAGES_DIR.exists() or not any(IMAGES_DIR.glob("*.jpg")),
    reason="识别数据集缺失（scripts/build_recognition_dataset.py 先产出）",
)
async def test_live_pipeline_front_segment(
    db_session: AsyncSession, captured_sends: list[dict[str, str]]
) -> None:
    """真图全链前段：recognize→align→create→mark_aligned→send_confirm_card。"""
    image_path = sorted(IMAGES_DIR.glob("*.jpg"))[0]
    image_b64 = base64.b64encode(image_path.read_bytes()).decode()

    recognized = await recognize_receipt(image_b64)
    assert recognized.material_name.value  # 识别非空（ticket 01 live 同口径）

    aligned = await pipeline_module.align_receipt(recognized)
    assert aligned.match_confidence in ("exact", "prefix", "fuzzy", "none")

    draft = await create_receipt_draft(
        db_session,
        recognized=recognized,
        image_file_token="img_v3_live_front",
        open_id="ou_live_front",
        chat_id="oc_live_front",
    )
    assert draft.status == "created"
    await mark_aligned(db_session, draft, aligned)
    assert draft.status == "aligned"
    await send_confirm_card(db_session, draft, chat_id="oc_live_front")
    assert draft.status == "pending_confirm"

    # 落库一致性（重新按 draft_no 查）
    reloaded = await agent_repository.get_agent_draft_by_no(
        db_session, draft_no=draft.draft_no
    )
    assert reloaded is not None
    assert reloaded.status == "pending_confirm"
    assert reloaded.recognized["material_name"]["value"]
    assert reloaded.aligned.get("match_confidence") == aligned.match_confidence
    assert reloaded.source_image == "img_v3_live_front"

    # 确认卡片（dry-run 捕获）：标题/按钮/低置信高亮
    cards = _confirm_card_payloads(captured_sends)
    assert len(cards) == 1
    card = cards[0]
    assert card["header"]["title"]["content"] == RECEIPT_CONFIRM_CARD_TITLE
    actions = card["elements"][2]["actions"]
    assert actions[0]["value"] == {
        "scene": RECEIPT_SCENE,
        "draft_id": str(draft.id),
        "action": "confirm",
    }
    assert actions[1]["value"]["action"] == "cancel"

    # 状态机审计：create / mark_aligned / send_confirm_card 各一条
    audits = await _draft_flow_audits(db_session, draft.id)
    assert sorted(a.args_summary["action"] for a in audits) == [
        "create",
        "mark_aligned",
        "send_confirm_card",
    ]
    print(
        f"\n[live 前段] 图={image_path.name} draft_no={draft.draft_no} "
        f"match={aligned.match_confidence} 物料={recognized.material_name.value}"
    )


# ── 7. live 对话修改（经 gateway + 真 Runner LLM）──


async def test_live_conversation_update_draft(
    agent_db: AsyncSession,
    captured_sends: list[dict[str, str]],
    fresh_redis: aioredis.Redis,
) -> None:
    """「把数量改成 200」→ update_draft 调用（audit）+ aligned.quantity 更新 + 新确认卡片。"""
    open_id = "ou_live_upd"
    chat_id = f"oc_live_upd_{uuid.uuid4().hex[:8]}"
    draft = await _seed_aligned_draft(agent_db, open_id=open_id, quantity="100")

    event = {
        "sender": {
            "sender_id": {"open_id": open_id, "union_id": "un", "user_id": "u"},
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
            "message_type": "text",
            "content": json.dumps({"text": "把数量改成 200"}, ensure_ascii=False),
            "mentions": [],
        },
    }
    await gateway.handle_im_message(event)

    # update_draft 被调用且成功（Runner 工具审计）
    rows = await agent_db.execute(
        select(WarehouseAgentAudit).where(
            WarehouseAgentAudit.tool_name == "update_draft",
            WarehouseAgentAudit.result_status == "ok",
        )
    )
    audits = list(rows.scalars().all())
    assert audits, "update_draft 未被 Runner 调用（LLM 行为偏离）"

    # aligned.quantity 更新 + 状态回 pending_confirm
    reloaded = await agent_repository.get_agent_draft_by_no(
        agent_db, draft_no=draft.draft_no
    )
    assert reloaded is not None
    assert float(reloaded.aligned["quantity"]) == 200
    assert reloaded.status == "pending_confirm"

    # 新确认卡片（dry-run 捕获）：数量 200 已上卡
    cards = _confirm_card_payloads(captured_sends)
    assert len(cards) == 1
    content = cards[0]["elements"][0]["content"]
    assert f"**草稿**：{draft.draft_no}" in content
    assert "数量：200" in content

    print(
        f"\n[live 对话修改] draft_no={draft.draft_no} "
        f"reply_tool={audits[0].args_summary}"
    )
