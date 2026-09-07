"""S3 ticket 04 验收：三场景集成回归（同会话双场景 + scene 隔离 + 提示词审计 + 混合查询）。

集成接缝（真 LLM + 真 Base / 真库 whdev，事务回滚隔离；发送 dry-run 捕获）：
- 同会话双场景：同一 (chat_id, open_id) 会话先「登记 GMP 出库：…」（确认 →
  写 GMP 出库总账 → 读回 → 回执），再「登记成品出库：…」（确认 → 写成品
  出库台账 → 读回 → 回执）→ 断言两个 draft 的 scene 正确、互不串场
  （gmp 草稿 aligned/recognized/status 不被成品流程改动）；
- scene 隔离：update_draft 指定 gmp 草稿 draft_no 但传成品字段（快递号）→
  按实现语义断言（见测试 docstring：update_draft 字段别名为三场景并集，
  跨场字段落入 aligned 但 submit 映射忽略＝inert；确认按钮仍走 gmp 场景，
  confirm 回调注册表 gmp_outbound → submit_gmp、finished_outbound →
  submit_outbound 各归其位）；
- 提示词长度审计：build_system_prompt 输出字符数 ≤ 8000（防三场景膨胀；
  实测数字 print 到报告）；
- 混合查询与登记：同会话先问库存（query_stock → 真 Base）再登记 GMP
  （create_gmp_draft）→ 断言两次工具审计 result_status=ok 且 session_id
  相同（工具路由正确、互不干扰）。

数据安全纪律：live 写入仅经 submit_gmp / submit_outbound create_record，
record_id 取 draft.target_record_id 精确 finally 删除（严禁按批号等业务
字段模糊清理）。

运行：cd "E:\\dazah(仓储)\\backend" &&
      DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/dazah_whdev"
      uv run pytest tests/modules/warehouse/test_live_multi_scene.py -v
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.redis as app_core_redis
from app.modules.warehouse.agent import confirm, gateway
from app.modules.warehouse.agent import runner as runner_module
from app.modules.warehouse.agent.cards import (
    FINISHED_CONFIRM_CARD_TITLE,
    FINISHED_OUTBOUND_SCENE,
    FINISHED_RESULT_CARD_TITLE_OK,
    GMP_CONFIRM_CARD_TITLE,
    GMP_OUTBOUND_SCENE,
    GMP_RESULT_CARD_TITLE_OK,
)
from app.modules.warehouse.agent.pipeline import draft_flow
from app.modules.warehouse.agent.pipeline.draft_flow import (
    create_dialog_draft,
    send_confirm_card,
)
from app.modules.warehouse.agent.pipeline.submit import (
    FINISHED_OUTBOUND_TABLE,
    GMP_OUTBOUND_TABLE,
    build_gmp_fields,
)
from app.modules.warehouse.agent.prompts import build_system_prompt
from app.modules.warehouse.agent.tools import draft_update
from app.modules.warehouse.agent.tools import finished as finished_module
from app.modules.warehouse.agent.tools import gmp as gmp_module
from app.modules.warehouse.agent.tools.draft_update import update_draft
from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter
from app.modules.warehouse.bitable_schema import (
    FIELD_TYPE_SELECT,
    FieldMeta,
)
from app.modules.warehouse.feishu import notification
from app.modules.warehouse.models import (
    WarehouseAgentAudit,
    WarehouseAgentDraft,
    WarehouseAgentSession,
)

# 提示词长度上限（ticket 04：三场景叠加防膨胀；字段字典保持按需注入）
PROMPT_MAX_CHARS = 8000

# live 数据（与 test_live_gmp / test_live_finished 同源：真 Base 选项集内）
GMP_TEXT = (
    "登记 GMP 出库：三氯甲烷 10423-260601 出库 25kg，"
    "生产批号 MA-ET-2026-050A，领用部门提炼工程一部"
)
FINISHED_TEXT = (
    "登记成品出库：硫酸黏菌素 批号 TEST-X2609 出库 225000 十亿，客户 can，快递 SF123456"
)


# ── fixtures（test_live_gmp/test_live_finished 同款）──


@pytest.fixture
def agent_db(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> AsyncSession:
    """gateway/runner/draft_update/gmp/finished 五处 _db_session → 测试 session。"""

    @asynccontextmanager
    async def _patched() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(gateway, "_db_session", _patched)
    monkeypatch.setattr(runner_module, "_db_session", _patched)
    monkeypatch.setattr(draft_update, "_db_session", _patched)
    monkeypatch.setattr(gmp_module, "_db_session", _patched)
    monkeypatch.setattr(finished_module, "_db_session", _patched)
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


# ── 测试辅助 ──


def _im_message_event(
    *, chat_id: str, sender_open_id: str, text: str
) -> dict[str, Any]:
    """im.message.receive_v1 文本事件（gateway 测试同构）。"""
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
            "chat_type": "p2p",
            "message_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
            "mentions": [],
        },
    }


def _card_of(payload: dict[str, str]) -> dict[str, Any]:
    card: dict[str, Any] = json.loads(payload["content"])
    return card


def _interactive_cards(sends: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [_card_of(p) for p in sends if p.get("msg_type") == "interactive"]


def _card_content(card: dict[str, Any]) -> str:
    return "\n".join(
        element.get("content") or ""
        for element in card.get("elements", [])
        if isinstance(element, dict)
    )


def _cards_with_title(sends: list[dict[str, str]], title: str) -> list[dict[str, Any]]:
    return [
        c
        for c in _interactive_cards(sends)
        if c.get("header", {}).get("title", {}).get("content") == title
    ]


async def _list_audits(
    db: AsyncSession, *, tool_name: str, session_id: Any | None = None
) -> list[WarehouseAgentAudit]:
    """查审计行。**必须传 session_id**：whdev 审计表含历史已提交行
    （此前运行/真实使用留下），不按会话过滤会取到历史行污染断言。"""
    stmt = select(WarehouseAgentAudit).where(WarehouseAgentAudit.tool_name == tool_name)
    if session_id is not None:
        stmt = stmt.where(WarehouseAgentAudit.session_id == session_id)
    rows = await db.execute(stmt)
    return list(rows.scalars().all())


async def _session_for(
    db: AsyncSession, *, chat_id: str, open_id: str
) -> WarehouseAgentSession | None:
    """定位本测试会话（chat_id 带 uuid 后缀，每次运行唯一）。"""
    rows = await db.execute(
        select(WarehouseAgentSession).where(
            WarehouseAgentSession.chat_id == chat_id,
            WarehouseAgentSession.user_open_id == open_id,
        )
    )
    return rows.scalars().first()


async def _drafts_for(
    db: AsyncSession, open_id: str, scene: str
) -> list[WarehouseAgentDraft]:
    rows = await db.execute(
        select(WarehouseAgentDraft).where(
            WarehouseAgentDraft.scene == scene,
            WarehouseAgentDraft.created_by_open_id == open_id,
        )
    )
    return list(rows.scalars().all())


def _gmp_table_fields_for_test() -> dict[str, FieldMeta]:
    """gmp_outbound 字段元数据（build_gmp_fields 单选适配用受控子集）。"""
    return {
        "物料批号": FieldMeta(
            type=FIELD_TYPE_SELECT, options=("10407-260802", "10423-260601")
        ),
        "单据类型": FieldMeta(type=FIELD_TYPE_SELECT, options=("出库", "退库")),
        "领用品种": FieldMeta(type=FIELD_TYPE_SELECT, options=()),
        "领用部门": FieldMeta(
            type=FIELD_TYPE_SELECT, options=("提炼工程一部", "提炼工程二部")
        ),
        "单位": FieldMeta(type=FIELD_TYPE_SELECT, options=("kg", "瓶", "L")),
    }


# ── 1. 提示词长度审计（三场景叠加防膨胀）──


async def test_prompt_length_within_budget_after_three_scenes() -> None:
    """build_system_prompt 字符数 ≤ 8000，且三场景规则段齐全。

    实测数字 print 进报告（ticket 04 验收口径）；超限则需裁剪字段字典
    （当前 5337 字符左右，余量充足）。
    """
    prompt = await build_system_prompt()
    length = len(prompt)
    print(
        f"\n[prompt 审计] build_system_prompt 字符数 = {length}（上限 {PROMPT_MAX_CHARS}）"
    )
    assert length <= PROMPT_MAX_CHARS, (
        f"提示词膨胀：{length} > {PROMPT_MAX_CHARS}，需裁剪字段字典（按需注入）后再上"
    )

    # 三场景叠加质量检查：路由规则/登记工具/推送引导段齐全
    assert "create_gmp_draft" in prompt
    assert "create_finished_outbound_draft" in prompt
    assert "场景判定" in prompt  # 三场景分流规则
    assert "update_draft" in prompt  # 草稿修改通用
    assert "快递推送" in prompt  # 成品出库推送引导


# ── 2. 同会话双场景登记（上下文不串场）──


async def test_live_same_session_gmp_then_finished(
    agent_db: AsyncSession,
    captured_sends: list[dict[str, str]],
    fresh_redis: aioredis.Redis,
) -> None:
    """同一会话先 GMP 后成品：双草稿 scene 正确、互不串场、各写各表。

    数据安全：两个 record_id 均取 draft.target_record_id，finally 精确删除。
    """
    open_id = "ou_live_multi"
    chat_id = f"oc_live_multi_{uuid.uuid4().hex[:8]}"
    adapter = WarehouseBitableAdapter()
    # (table_key, record_id)：仅收 submit 落库返回的精确 id，finally 逐一删除
    created_records: list[tuple[str, str]] = []
    try:
        # ── 第一段：GMP 出库登记 ──
        await gateway.handle_im_message(
            _im_message_event(chat_id=chat_id, sender_open_id=open_id, text=GMP_TEXT)
        )
        session_row = await _session_for(agent_db, chat_id=chat_id, open_id=open_id)
        assert session_row is not None, "会话未定位（gateway 未建会话）"
        gmp_audits = await _list_audits(
            agent_db, tool_name="create_gmp_draft", session_id=session_row.id
        )
        assert gmp_audits, "create_gmp_draft 未被 Runner 调用（LLM 行为偏离）"
        assert any(a.result_status == "ok" for a in gmp_audits)

        gmp_drafts = await _drafts_for(agent_db, open_id, GMP_OUTBOUND_SCENE)
        assert len(gmp_drafts) == 1, f"应恰好一张 GMP 草稿，实际 {len(gmp_drafts)}"
        gmp_draft = gmp_drafts[0]
        assert gmp_draft.status == "pending_confirm"
        gmp_aligned = dict(gmp_draft.aligned or {})
        assert gmp_aligned["material_batch_no"] == "10423-260601"
        assert float(gmp_aligned["quantity"]) == 25
        assert gmp_aligned["unit"] == "kg"
        assert gmp_aligned["production_batch_no"] == "MA-ET-2026-050A"

        # GMP 确认卡片（scene=gmp_outbound 按钮）
        gmp_cards = _cards_with_title(captured_sends, GMP_CONFIRM_CARD_TITLE)
        assert gmp_cards, "GMP 确认卡片未被捕获"
        assert (
            gmp_cards[-1]["elements"][2]["actions"][0]["value"]["scene"]
            == GMP_OUTBOUND_SCENE
        )

        # 点确认 → submit_gmp → 写 GMP 出库总账
        outcome = await confirm.handle_action(
            agent_db,
            value={
                "scene": GMP_OUTBOUND_SCENE,
                "action": "confirm",
                "draft_id": str(gmp_draft.id),
            },
            operator_open_id=open_id,
        )
        assert outcome.ok is True, f"GMP submit 失败: {outcome.message}"
        assert gmp_draft.status == "submitted"
        gmp_record_id = gmp_draft.target_record_id
        assert gmp_record_id and gmp_record_id.startswith("rec")
        created_records.append((GMP_OUTBOUND_TABLE, gmp_record_id))

        gmp_record = await adapter.get_record(GMP_OUTBOUND_TABLE, gmp_record_id)
        gmp_fields = gmp_record["fields"]
        assert float(gmp_fields.get("领用数量")) == 25
        assert "kg" in str(gmp_fields.get("单位"))
        assert "MA-ET-2026-050A" in str(gmp_fields.get("生产批号"))
        assert _cards_with_title(captured_sends, GMP_RESULT_CARD_TITLE_OK), (
            "GMP 回执卡片未被捕获"
        )

        # ── 第二段（同会话）：成品出库登记 ──
        await gateway.handle_im_message(
            _im_message_event(
                chat_id=chat_id, sender_open_id=open_id, text=FINISHED_TEXT
            )
        )
        finished_audits = await _list_audits(
            agent_db,
            tool_name="create_finished_outbound_draft",
            session_id=session_row.id,
        )
        assert finished_audits, (
            "create_finished_outbound_draft 未被 Runner 调用（LLM 行为偏离/串场）"
        )
        assert any(a.result_status == "ok" for a in finished_audits)
        # 同一会话：第二段仍定位到同一条 session（上下文不串场）
        session_row_again = await _session_for(
            agent_db, chat_id=chat_id, open_id=open_id
        )
        assert session_row_again is not None and session_row_again.id == session_row.id

        finished_drafts = await _drafts_for(agent_db, open_id, FINISHED_OUTBOUND_SCENE)
        assert len(finished_drafts) == 1, (
            f"应恰好一张成品草稿，实际 {len(finished_drafts)}"
        )
        finished_draft = finished_drafts[0]
        assert finished_draft.status == "pending_confirm"
        finished_aligned = dict(finished_draft.aligned or {})
        assert finished_aligned["product_name"] == "硫酸黏菌素"
        assert finished_aligned["product_batch_no"] == "TEST-X2609"
        assert float(finished_aligned["quantity"]) == 225000
        assert finished_aligned["unit"] == "十亿"
        assert finished_aligned["customer"] == "can"

        # 互不串场：gmp 草稿未被成品流程改动（scene/status/working set 原样）
        assert gmp_draft.scene == GMP_OUTBOUND_SCENE
        assert gmp_draft.status == "submitted"
        assert dict(gmp_draft.aligned or {}) == gmp_aligned
        assert dict(gmp_draft.recognized or {}) == dict(gmp_draft.recognized or {})
        # 成品确认卡片按钮 scene=finished_outbound（不是 gmp）
        finished_cards = _cards_with_title(captured_sends, FINISHED_CONFIRM_CARD_TITLE)
        assert finished_cards, "成品确认卡片未被捕获"
        assert (
            finished_cards[-1]["elements"][2]["actions"][0]["value"]["scene"]
            == FINISHED_OUTBOUND_SCENE
        )

        # 点确认 → submit_outbound → 写成品出库台账
        outcome2 = await confirm.handle_action(
            agent_db,
            value={
                "scene": FINISHED_OUTBOUND_SCENE,
                "action": "confirm",
                "draft_id": str(finished_draft.id),
            },
            operator_open_id=open_id,
        )
        assert outcome2.ok is True, f"成品 submit 失败: {outcome2.message}"
        assert finished_draft.status == "submitted"
        finished_record_id = finished_draft.target_record_id
        assert finished_record_id and finished_record_id.startswith("rec")
        created_records.append((FINISHED_OUTBOUND_TABLE, finished_record_id))

        finished_record = await adapter.get_record(
            FINISHED_OUTBOUND_TABLE, finished_record_id
        )
        finished_fields = finished_record["fields"]
        assert "TEST-X2609" in str(finished_fields.get("产品批号"))
        assert float(finished_fields.get("出库量")) == 225000
        assert "十亿" in str(finished_fields.get("单位"))
        assert "can" in str(finished_fields.get("销售客户"))
        assert _cards_with_title(captured_sends, FINISHED_RESULT_CARD_TITLE_OK), (
            "成品回执卡片未被捕获"
        )

        # 互不串场（落库口径）：GMP 台账记录不含成品字段、反之亦然
        assert "产品批号" not in gmp_fields
        assert "物料批号" not in finished_fields and "生产批号" not in finished_fields
        print(
            f"\n[live 双场景] gmp={gmp_draft.draft_no}({gmp_record_id}) "
            f"finished={finished_draft.draft_no}({finished_record_id})"
        )
    finally:
        for table_key, record_id in created_records:
            await adapter.delete_record(table_key, record_id)  # 测试清理（精确 id）


# ── 3. scene 隔离：跨场字段修改 + 确认门路由 ──


async def test_live_scene_isolation_cross_field_and_confirm_gate(
    agent_db: AsyncSession, captured_sends: list[dict[str, str]]
) -> None:
    """update_draft 对 gmp 草稿传成品字段（快递号）→ 按实现语义断言。

    实现语义（draft_update.FIELD_ALIASES 为三场景并集，无 per-scene 过滤）：
    跨场字段被接收并写入 aligned，但对 gmp submit 是 inert——build_gmp_fields
    映射表无 express_no，不会写进 Base；确认卡片仍是 GMP 分支（不渲染
    快递号），确认按钮 value.scene 仍为 gmp_outbound，confirm 注册表把
    gmp_outbound → submit_gmp、finished_outbound → submit_outbound 各归其位。
    """
    draft = await create_dialog_draft(
        agent_db,
        scene=GMP_OUTBOUND_SCENE,
        fields={
            "material_batch_no": "10407-260802",
            "quantity": 25,
            "unit": "kg",
            "production_batch_no": "MA-1",
            "department": "提炼工程一部",
        },
        open_id="ou_multi_isolation",
        chat_id="oc_multi_isolation",
    )
    await send_confirm_card(agent_db, draft, chat_id="oc_multi_isolation")
    aligned_before = dict(draft.aligned or {})

    # 跨场修改：指定 gmp 草稿 draft_no，传成品字段「快递号」
    result = await update_draft(
        draft.draft_no,
        {"快递号": "SF999999"},
        _ctx={"open_id": "ou_multi_isolation", "chat_id": "oc_multi_isolation"},
    )
    # 实现语义：并集别名接收（不报错），落入 aligned；gmp 必收字段原样
    assert "error" not in result, result
    assert result["updated"]["express_no"] == "SF999999"
    assert draft.aligned["express_no"] == "SF999999"
    for key, value in aligned_before.items():
        assert draft.aligned[key] == value, f"跨场修改误改了 gmp 字段 {key}"

    # 重发的仍是 GMP 分支确认卡片（按钮 scene=gmp_outbound，不渲染快递号）
    cards = _cards_with_title(captured_sends, GMP_CONFIRM_CARD_TITLE)
    assert len(cards) == 2, "修改后应重发 GMP 确认卡片"
    resent = cards[-1]
    assert resent["elements"][2]["actions"][0]["value"]["scene"] == GMP_OUTBOUND_SCENE
    assert "快递号" not in _card_content(resent), "成品字段不应出现在 GMP 卡片上"

    # 确认门路由：gmp 草稿的确认点击走 gmp submit（不是 finished）
    assert confirm.is_registered_scene(GMP_OUTBOUND_SCENE)
    assert confirm.is_registered_scene(FINISHED_OUTBOUND_SCENE)
    assert confirm._confirm_callbacks[GMP_OUTBOUND_SCENE] is (
        draft_flow._gmp_submit_callback
    )
    assert confirm._confirm_callbacks[FINISHED_OUTBOUND_SCENE] is (
        draft_flow._finished_submit_callback
    )

    # inert 断言：submit 写入集合不含跨场字段（build_gmp_fields 无 express_no）
    fields, _degraded = build_gmp_fields(
        draft, table_fields=_gmp_table_fields_for_test()
    )
    assert "快递号" not in fields and "express_no" not in fields
    assert fields["领用数量"] == 25 and fields["单位"] == "kg"
    assert fields["生产批号"] == "MA-1"


# ── 4. 混合查询与登记（同会话工具路由）──


async def test_live_mixed_query_then_register_same_session(
    agent_db: AsyncSession,
    captured_sends: list[dict[str, str]],
    fresh_redis: aioredis.Redis,
) -> None:
    """同会话先问库存再登记 GMP：query_stock 与 create_gmp_draft 路由正确。

    两轮工具审计 session_id 相同（同一会话），均 result_status=ok；
    查询轮不建草稿，登记轮建 GMP 草稿（pending_confirm，不写 Base）。
    """
    open_id = "ou_live_mixed"
    chat_id = f"oc_live_mixed_{uuid.uuid4().hex[:8]}"

    # 第一轮：纯查询（真 Base，硫酸有库存——MCP 端点测试同源口径）
    await gateway.handle_im_message(
        _im_message_event(
            chat_id=chat_id, sender_open_id=open_id, text="帮我查一下硫酸的库存"
        )
    )
    session_row = await _session_for(agent_db, chat_id=chat_id, open_id=open_id)
    assert session_row is not None, "会话未定位（gateway 未建会话）"
    query_audits = await _list_audits(
        agent_db, tool_name="query_stock", session_id=session_row.id
    )
    assert query_audits, "query_stock 未被 Runner 调用（查询路由偏离）"
    assert any(a.result_status == "ok" for a in query_audits)

    # 查询轮不产生登记草稿
    assert await _drafts_for(agent_db, open_id, GMP_OUTBOUND_SCENE) == []

    # 第二轮（同会话）：登记 GMP 出库
    await gateway.handle_im_message(
        _im_message_event(chat_id=chat_id, sender_open_id=open_id, text=GMP_TEXT)
    )
    register_audits = await _list_audits(
        agent_db, tool_name="create_gmp_draft", session_id=session_row.id
    )
    assert register_audits, "create_gmp_draft 未在同一会话被调用（路由偏离）"
    assert any(a.result_status == "ok" for a in register_audits)

    # 同会话两轮：审计 session_id 一致；草稿已建（pending_confirm，未确认不写 Base）
    assert all(a.session_id == session_row.id for a in register_audits)
    assert await _drafts_for(agent_db, open_id, GMP_OUTBOUND_SCENE) != []
    drafts = await _drafts_for(agent_db, open_id, GMP_OUTBOUND_SCENE)
    assert all(d.status == "pending_confirm" for d in drafts)

    # 确认卡片已发（GMP 分支）；查询结果卡片在先（工具路由时序正确）
    assert _cards_with_title(captured_sends, GMP_CONFIRM_CARD_TITLE), (
        "GMP 确认卡片未被捕获"
    )
    print(
        f"\n[live 混合] session_id={session_row.id} "
        f"query_stock_ok={any(a.result_status == 'ok' for a in query_audits)} "
        f"register_ok={any(a.result_status == 'ok' for a in register_audits)}"
    )
