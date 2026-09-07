"""S3 ticket 01 验收：GMP 对话式登记（create_gmp_draft → 确认 → submit_gmp）。

单测（真库 whdev + 事务回滚隔离；Base/选项集刷新/发送全部注入假件不触网）：
- build_gmp_fields：字段映射（批号/数量/单位/生产批号/单据类型/部门）、
  lookup 物料名称拒写（不入 fields）、日期=当天毫秒时间戳（_today_ms 纯
  函数）、单选不在选项集跳过（degraded）、数量数字化、validate_write_fields
  通过；
- create_gmp_draft 工具：必收字段缺失 → missing + hint（无草稿落库）、
  物料批号不在选项集 → error 引导核对（error_code=batch_not_found）、
  齐全 → 草稿（created→aligned）+ 单据类型默认出库 + 单位归一（Kg→kg）+
  确认卡片（GMP 分支文案，dry-run 捕获）+ 领用部门选集未命中附 warning；
- create_dialog_draft：未知 scene 拒绝；SCENE_CONFIG 注册面
  （receipt/gmp_outbound/finished_outbound 均注册确认回调，finished 于
  S3 ticket 02 落地）；
- submit_gmp：状态前置（非 confirmed 拒绝）；
- update_draft gmp 场景：数量/领用部门别名写入 aligned + 重发 GMP 确认卡片。

live 主接缝（真 LLM + 真 Base，无数据集依赖）：
- 全链：gateway 文本「三氯甲烷 10423-260601 出库 25kg，生产批号
  MA-ET-2026-050A，领用部门提炼工程一部」→ 草稿 → 确认卡片（dry-run 捕获，
  GMP 分支）→ 点确认 → 写 GMP 出库总账（record_id 精记 finally 删）→
  读回一致（数量/单位/生产批号等）→ 回执卡片；
  ⚠ 物料批号因 Base 侧字段编辑限制降级不写入（SUBMIT_GMP_BATCH_ENABLED
  降级开关 + 回执标注人工补填，见 submit.py 开关注释）；
- 缺字段追问：「三氯甲烷 10423-260601 出库 25kg」（缺生产批号）→ 工具返回
  missing，LLM 追问而非硬写（无草稿落库、不写 Base）。

数据安全纪律：live 写入仅经 submit_gmp create_record，record_id 取自
draft.target_record_id 精确 finally 删除，严禁按批号等业务字段模糊清理。

运行：cd "E:\\dazah(仓储)\\backend" &&
      DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/dazah_whdev"
      uv run pytest tests/modules/warehouse/test_live_gmp.py -v
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Any

import pytest
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.redis as app_core_redis
from app.modules.warehouse.agent import confirm, gateway
from app.modules.warehouse.agent import runner as runner_module
from app.modules.warehouse.agent.cards import (
    GMP_CHECK_OK_LINE,
    GMP_CONFIRM_CARD_TITLE,
    GMP_OUTBOUND_SCENE,
    GMP_RESULT_CARD_TITLE_MISMATCH,
    GMP_RESULT_CARD_TITLE_OK,
    RECEIPT_CONFIRM_CARD_TITLE,
    RECEIPT_RESULT_CARD_TITLE_OK,
    render_receipt_confirm_card,
    render_receipt_result_card,
)
from app.modules.warehouse.agent.pipeline import (
    SCENE_CONFIG,
    create_dialog_draft,
    send_confirm_card,
)
from app.modules.warehouse.agent.pipeline import submit as submit_module
from app.modules.warehouse.agent.pipeline.draft_flow import DraftFlowError
from app.modules.warehouse.agent.pipeline.submit import (
    GMP_CHECK_FIELDS,
    GMP_OUTBOUND_TABLE,
    _today_ms,
    build_gmp_fields,
    submit_gmp,
)
from app.modules.warehouse.agent.tools import draft_update
from app.modules.warehouse.agent.tools import gmp as gmp_module
from app.modules.warehouse.agent.tools.draft_update import update_draft
from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter
from app.modules.warehouse.bitable_schema import (
    FIELD_TYPE_SELECT,
    FieldMeta,
    validate_write_fields,
)
from app.modules.warehouse.feishu import notification
from app.modules.warehouse.models import WarehouseAgentAudit, WarehouseAgentDraft

# ── fixtures：db 注入 / 发送捕获 / Runner 单例 / Redis ──


@pytest.fixture
def agent_db(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> AsyncSession:
    """gateway/runner/draft_update/gmp 四处 _db_session → 包装测试 session。

    create_gmp_draft 在 Runner 工具循环内自开事务（gmp._db_session）——
    与 gateway/runner/draft_update 同指一个测试 session（不 commit），
    随 fixture 回滚隔离。
    """

    @asynccontextmanager
    async def _patched() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(gateway, "_db_session", _patched)
    monkeypatch.setattr(runner_module, "_db_session", _patched)
    monkeypatch.setattr(draft_update, "_db_session", _patched)
    monkeypatch.setattr(gmp_module, "_db_session", _patched)
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


@pytest.fixture
def gmp_unit_env(
    agent_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> dict[str, FieldMeta]:
    """单测环境：gmp 选项集注入静态假件（不触网、不污染全局选项缓存）。

    返回注入的字段元数据（含 物料批号/单据类型/领用部门/单位 选项集），
    使工具校验行为确定（与 live 侧真实 refresh_table_fields 解耦）。
    """
    table_fields = _gmp_fields_for_test()

    async def _fake_table_fields() -> dict[str, FieldMeta]:
        return table_fields

    monkeypatch.setattr(gmp_module, "_gmp_table_fields", _fake_table_fields)
    return table_fields


# ── 测试数据工厂 ──


def _gmp_fields_for_test() -> dict[str, FieldMeta]:
    """gmp_outbound 字段元数据（单测注入；批号选项集为受控子集）。"""
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
        "领用数量": FieldMeta(type=2),
        "生产批号": FieldMeta(type=1),
    }


def _gmp_draft_row(
    aligned: dict[str, Any], *, status: str = "confirmed"
) -> WarehouseAgentDraft:
    """GMP 草稿 ORM 对象（aligned 即对话收集 working set）。"""
    return WarehouseAgentDraft(
        draft_no="WR20990101-101",
        scene=GMP_OUTBOUND_SCENE,
        status=status,
        recognized=dict(aligned),
        aligned=dict(aligned),
    )


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
    db: AsyncSession, *, tool_name: str, draft_id: Any | None = None
) -> list[WarehouseAgentAudit]:
    stmt = select(WarehouseAgentAudit).where(WarehouseAgentAudit.tool_name == tool_name)
    if draft_id is not None:
        stmt = stmt.where(WarehouseAgentAudit.draft_id == draft_id)
    rows = await db.execute(stmt)
    return list(rows.scalars().all())


async def _gmp_drafts(db: AsyncSession, open_id: str) -> list[WarehouseAgentDraft]:
    rows = await db.execute(
        select(WarehouseAgentDraft).where(
            WarehouseAgentDraft.scene == GMP_OUTBOUND_SCENE,
            WarehouseAgentDraft.created_by_open_id == open_id,
        )
    )
    return list(rows.scalars().all())


def _im_message_event(
    *, chat_id: str, sender_open_id: str, text: str
) -> dict[str, Any]:
    """im.message.receive_v1 文本事件（gateway 测试同构，见 test_live_gateway）。"""
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


# ── 1. build_gmp_fields：映射 / lookup 拒写 / 日期 / 单选适配 ──


def test_today_ms_pure() -> None:
    """日期纯函数：当天 → 毫秒时间戳（UTC 零点，飞书 datetime 写入契约）。"""
    expected = int(datetime(2026, 9, 7, tzinfo=UTC).timestamp() * 1000)
    assert _today_ms(date(2026, 9, 7)) == expected


def test_build_gmp_fields_mapping_lookup_rejected_and_today(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """全字段映射（开关置 True）：数量数字化、lookup 拒写、日期=当天毫秒。"""
    monkeypatch.setattr(submit_module, "SUBMIT_GMP_BATCH_ENABLED", True)
    draft = _gmp_draft_row(
        {
            "material_batch_no": "10407-260802",
            "material_name": "三氯甲烷",
            "quantity": "25",
            "unit": "kg",
            "production_batch_no": "MA-ET-2026-050A",
            "doc_type": "出库",
            "department": "提炼工程一部",
        }
    )
    fields, degraded = build_gmp_fields(
        draft,
        table_fields=_gmp_fields_for_test(),
        today=date(2026, 9, 7),
    )

    assert degraded == []
    assert fields["物料批号"] == "10407-260802"
    assert fields["领用数量"] == 25 and isinstance(fields["领用数量"], int)
    assert fields["单位"] == "kg"
    assert fields["生产批号"] == "MA-ET-2026-050A"
    assert fields["单据类型"] == "出库"
    assert fields["领用部门"] == "提炼工程一部"
    assert fields["日期"] == _today_ms(date(2026, 9, 7))
    # lookup（物料名称/物料代码/物料大类）与创建人拒写——不进入写入字段
    assert "物料名称" not in fields
    assert "物料代码" not in fields and "物料大类" not in fields
    assert "创建人" not in fields
    # S0 写契约本地校验通过（单选均为选项集内纯字符串）
    validate_write_fields(GMP_OUTBOUND_TABLE, fields)


def test_build_gmp_fields_batch_degraded_by_default() -> None:
    """批号降级开关默认 False：物料批号不写入 + degraded 标注（Base 字段限制）。"""
    assert submit_module.SUBMIT_GMP_BATCH_ENABLED is False
    draft = _gmp_draft_row(
        {"material_batch_no": "10407-260802", "quantity": "25", "unit": "kg"}
    )
    fields, degraded = build_gmp_fields(
        draft, table_fields=_gmp_fields_for_test(), today=date(2026, 9, 7)
    )
    assert "物料批号" in degraded
    assert "物料批号" not in fields
    assert fields["领用数量"] == 25 and fields["单位"] == "kg"
    validate_write_fields(GMP_OUTBOUND_TABLE, fields)


def test_build_gmp_fields_select_mismatch_and_bad_quantity_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """单位不在选项集 → 跳过 + degraded；数量非数字 → 跳过 + degraded。"""
    monkeypatch.setattr(submit_module, "SUBMIT_GMP_BATCH_ENABLED", True)
    draft = _gmp_draft_row(
        {
            "material_batch_no": "10407-260802",
            "quantity": "二十五",
            "unit": "毫升",
            "production_batch_no": "MA-1",
        }
    )
    fields, degraded = build_gmp_fields(
        draft,
        table_fields=_gmp_fields_for_test(),
        today=date(2026, 9, 7),
    )

    assert "单位" in degraded and "单位" not in fields
    assert "领用数量" in degraded and "领用数量" not in fields
    assert fields["物料批号"] == "10407-260802"
    assert fields["生产批号"] == "MA-1"
    assert fields["日期"] == _today_ms(date(2026, 9, 7))
    validate_write_fields(GMP_OUTBOUND_TABLE, fields)


def test_build_gmp_fields_empty_fields_only_date() -> None:
    """aligned 为空 → 仅恒写日期（当日），无 degraded。"""
    draft = _gmp_draft_row({})
    fields, degraded = build_gmp_fields(
        draft, table_fields=_gmp_fields_for_test(), today=date(2026, 9, 7)
    )
    assert degraded == []
    assert fields == {"日期": _today_ms(date(2026, 9, 7))}


# ── 2. create_gmp_draft 工具：缺失追问 / 非法批号 / 成功建稿 ──


async def test_create_gmp_draft_missing_fields_returns_missing(
    agent_db: AsyncSession, gmp_unit_env: Any
) -> None:
    """缺生产批号 → missing + hint（LLM 追问），不建草稿。"""
    result = await gmp_module.create_gmp_draft(
        {"物料批号": "10407-260802", "领用数量": "25", "单位": "kg"},
        _ctx={"open_id": "ou_gmp_miss", "chat_id": "oc_gmp_miss"},
    )
    assert result["status"] == "incomplete"
    assert result["missing"] == ["生产批号"]
    assert "请补充" in result["hint"]
    assert "生产批号" in result["hint"]
    assert await _gmp_drafts(agent_db, "ou_gmp_miss") == []


async def test_create_gmp_draft_invalid_batch_error(
    agent_db: AsyncSession, gmp_unit_env: Any
) -> None:
    """物料批号不在选项集 → error 引导核对（不猜测），不建草稿。"""
    result = await gmp_module.create_gmp_draft(
        {
            "物料批号": "99999-000000",
            "领用数量": 25,
            "单位": "kg",
            "生产批号": "MA-1",
        },
        _ctx={"open_id": "ou_gmp_bad", "chat_id": "oc_gmp_bad"},
    )
    assert "error" in result
    assert result["error_code"] == "batch_not_found"
    assert "核对" in result["error"]
    assert await _gmp_drafts(agent_db, "ou_gmp_bad") == []


async def test_create_gmp_draft_invalid_unit_error(
    agent_db: AsyncSession, gmp_unit_env: Any
) -> None:
    """单位不在选项集 → error 引导（可选 kg/瓶/L）。"""
    result = await gmp_module.create_gmp_draft(
        {
            "物料批号": "10407-260802",
            "领用数量": 25,
            "单位": "吨",
            "生产批号": "MA-1",
        },
        _ctx={"open_id": "ou_gmp_unit", "chat_id": "oc_gmp_unit"},
    )
    assert "error" in result and result["error_code"] == "unit_invalid"
    assert await _gmp_drafts(agent_db, "ou_gmp_unit") == []


async def test_create_gmp_draft_success_with_card(
    agent_db: AsyncSession,
    gmp_unit_env: Any,
    captured_sends: list[dict[str, str]],
) -> None:
    """齐全 → 草稿（aligned 即收集字段）+ 默认出库 + 单位归一 + GMP 确认卡片。

    领用部门不在选项集 → warning（不阻断）；物料名称仅展示（进 aligned，
    不在 submit 写入映射）。
    """
    result = await gmp_module.create_gmp_draft(
        {
            "物料批号": "10407-260802",
            "物料名称": "三氯甲烷",
            "领用数量": "25",
            "单位": "Kg",
            "生产批号": "MA-ET-2026-050A",
            "领用部门": "不存在的部门",
        },
        _ctx={"open_id": "ou_gmp_ok", "chat_id": "oc_gmp_ok"},
    )
    assert "error" not in result, result
    assert result["status"] == "pending_confirm"
    assert result["draft_no"]
    # 单据类型默认出库 + 单位大小写归一
    assert result["fields"]["doc_type"] == "出库"
    assert result["fields"]["unit"] == "kg"
    # 预告：批号 Base 编辑限制降级 + 领用部门选集未命中（均不阻断登记）
    assert any("物料批号" in w for w in result["warnings"])
    assert any("领用部门" in w for w in result["warnings"])

    drafts = await _gmp_drafts(agent_db, "ou_gmp_ok")
    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.status == "pending_confirm"
    assert draft.aligned["material_batch_no"] == "10407-260802"
    assert float(draft.aligned["quantity"]) == 25
    assert draft.recognized == draft.aligned  # 收集值留底 = working set

    # 确认卡片（GMP 分支）：标题/字段行/按钮 value.scene
    cards = _cards_with_title(captured_sends, GMP_CONFIRM_CARD_TITLE)
    assert len(cards) == 1
    card = cards[0]
    content = _card_content(card)
    assert "1. 物料批号：10407-260802" in content
    assert "2. 领用数量：25" in content
    assert "3. 单位：kg" in content
    assert "4. 生产批号：MA-ET-2026-050A" in content
    assert "物料名称：三氯甲烷" in content  # 仅展示
    buttons = card["elements"][2]["actions"]
    assert buttons[0]["value"]["scene"] == GMP_OUTBOUND_SCENE
    assert buttons[0]["value"]["draft_id"] == str(draft.id)
    assert buttons[1]["value"]["action"] == "cancel"

    # 状态机审计：create / mark_aligned / send_confirm_card
    audits = await _list_audits(agent_db, tool_name="draft_flow", draft_id=draft.id)
    assert sorted(a.args_summary["action"] for a in audits) == [
        "create",
        "mark_aligned",
        "send_confirm_card",
    ]


# ── 3. SCENE_CONFIG / create_dialog_draft / submit_gmp 前置 ──


def test_scene_config_structure_and_registration() -> None:
    """SCENE_CONFIG 三场景；receipt/gmp_outbound/finished_outbound 均注册回调。"""
    assert set(SCENE_CONFIG) == {"receipt", "gmp_outbound", "finished_outbound"}
    assert confirm.is_registered_scene("receipt")
    assert confirm.is_registered_scene("gmp_outbound")
    assert confirm.is_registered_scene("finished_outbound")  # S3 ticket 02 落地

    gmp_config = SCENE_CONFIG["gmp_outbound"]
    assert gmp_config.required_fields == (
        "material_batch_no",
        "quantity",
        "unit",
        "production_batch_no",
    )
    # 可写字段集：含全部可写项，排除 lookup/创建人（拒写）
    assert set(gmp_config.writable_fields) == {
        "物料批号",
        "日期",
        "单据类型",
        "领用品种",
        "领用部门",
        "单位",
        "领用数量",
        "生产批号",
    }


async def test_create_dialog_draft_unknown_scene_rejected(
    db_session: AsyncSession,
) -> None:
    """未知 scene（如 confirm_action）→ DraftFlowError，不落库。"""
    with pytest.raises(DraftFlowError):
        await create_dialog_draft(
            db_session, scene="confirm_action", fields={}, open_id="ou_x"
        )


async def test_submit_gmp_requires_confirmed(db_session: AsyncSession) -> None:
    """状态前置：非 confirmed（aligned）直接提交 → DraftFlowError。"""
    draft = _gmp_draft_row({"material_batch_no": "10407-260802"}, status="aligned")
    with pytest.raises(DraftFlowError):
        await submit_gmp(db_session, draft)
    assert draft.status == "aligned"  # 未被改动


# ── 4. 回执/确认卡片 scene 分支（receipt 零变化对照）──


def test_render_gmp_confirm_card_branch_and_defensive() -> None:
    """scene=gmp_outbound → GMP 卡片；字段缺失降级（—），不抛错。"""
    draft = WarehouseAgentDraft(
        draft_no="WR20990101-110",
        scene=GMP_OUTBOUND_SCENE,
        recognized={},
        aligned={},
    )
    card = render_receipt_confirm_card(draft)
    assert card["header"]["title"]["content"] == GMP_CONFIRM_CARD_TITLE
    content = _card_content(card)
    assert "1. 物料批号：— ⚠" in content  # 必收缺失提醒
    assert "1. 物料名称：—" in content  # 选填缺省无 ⚠（分区独立编号）

    # receipt 零变化对照：同函数 scene=receipt 走入库卡片
    receipt_draft = WarehouseAgentDraft(
        draft_no="WR20990101-111", scene="receipt", recognized={}, aligned={}
    )
    receipt_card = render_receipt_confirm_card(receipt_draft)
    assert receipt_card["header"]["title"]["content"] == RECEIPT_CONFIRM_CARD_TITLE


def test_render_gmp_result_card_titles() -> None:
    """回执卡片：gmp_outbound 用 GMP 标题与核对文案；receipt 标题不变。"""
    gmp_draft = WarehouseAgentDraft(draft_no="WR20990101-120", scene=GMP_OUTBOUND_SCENE)
    check = {
        "consistent": True,
        "mismatches": [],
        "written": {"物料批号": "10407-260802", "领用数量": 25, "单位": "kg"},
        "record_id": "recGMP001",
        "degraded": [],
    }
    card = render_receipt_result_card(gmp_draft, check)
    assert card["header"]["title"]["content"] == GMP_RESULT_CARD_TITLE_OK
    assert card["header"]["template"] == "green"
    assert GMP_CHECK_OK_LINE in _card_content(card)

    mismatch = render_receipt_result_card(
        gmp_draft,
        {
            **check,
            "consistent": False,
            "mismatches": [{"field": "领用数量", "written": "25", "read_back": "20"}],
        },
    )
    assert mismatch["header"]["title"]["content"] == GMP_RESULT_CARD_TITLE_MISMATCH
    assert mismatch["header"]["template"] == "red"

    receipt_draft = WarehouseAgentDraft(draft_no="WR20990101-121", scene="receipt")
    receipt_card = render_receipt_result_card(receipt_draft, check)
    assert receipt_card["header"]["title"]["content"] == RECEIPT_RESULT_CARD_TITLE_OK


# ── 5. update_draft gmp 场景 ──


async def test_update_draft_gmp_scene_fields_and_resend(
    agent_db: AsyncSession,
    gmp_unit_env: Any,
    captured_sends: list[dict[str, str]],
) -> None:
    """gmp 草稿对话修改：数量/领用部门别名 → aligned + 重发 GMP 确认卡片。"""
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
        open_id="ou_gmp_upd",
        chat_id="oc_gmp_upd",
    )
    await send_confirm_card(agent_db, draft, chat_id="oc_gmp_upd")
    assert len(_cards_with_title(captured_sends, GMP_CONFIRM_CARD_TITLE)) == 1

    result = await update_draft(
        draft.draft_no,
        {"数量": "30", "领用部门": "提炼工程二部"},
        _ctx={"open_id": "ou_gmp_upd", "chat_id": "oc_gmp_upd"},
    )
    assert "error" not in result, result
    assert result["updated"]["quantity"] == 30  # 数字化
    assert result["updated"]["department"] == "提炼工程二部"
    assert float(draft.aligned["quantity"]) == 30
    assert draft.aligned["department"] == "提炼工程二部"
    assert draft.status == "pending_confirm"

    # 重发的是 GMP 分支卡片（数量 30 上卡）
    cards = _cards_with_title(captured_sends, GMP_CONFIRM_CARD_TITLE)
    assert len(cards) == 2
    assert "数量：30" in _card_content(cards[-1])

    # submit 真身对应的 CHECK_FIELDS 口径（批号/数量/单位）
    assert GMP_CHECK_FIELDS == ("物料批号", "领用数量", "单位")


# ── 6. live 主接缝：对话 → 草稿 → 确认 → 写 Base（record_id 精记 finally 删）──


async def test_live_gmp_dialog_submit_full_flow(
    agent_db: AsyncSession,
    captured_sends: list[dict[str, str]],
    fresh_redis: aioredis.Redis,
) -> None:
    """真 LLM + 真 Base 全链：文本 → 草稿 → 确认卡片 → 确认 → 写 GMP 出库总账。

    数据安全：仅经 submit_gmp 写入，record_id 取 draft.target_record_id
    精确 finally 删除（严禁按批号模糊清理）。
    """
    open_id = "ou_live_gmp"
    chat_id = f"oc_live_gmp_{uuid.uuid4().hex[:8]}"
    event = _im_message_event(
        chat_id=chat_id,
        sender_open_id=open_id,
        text="三氯甲烷 10423-260601 出库 25kg，生产批号 MA-ET-2026-050A，领用部门提炼工程一部",
    )
    await gateway.handle_im_message(event)

    # 工具被调用且成功（Runner 工具审计）
    tool_audits = await _list_audits(agent_db, tool_name="create_gmp_draft")
    assert tool_audits, "create_gmp_draft 未被 Runner 调用（LLM 行为偏离）"
    assert any(a.result_status == "ok" for a in tool_audits)

    # 草稿落库：对话收集字段（无识别步骤，created→aligned→pending_confirm）
    drafts = await _gmp_drafts(agent_db, open_id)
    assert len(drafts) == 1, f"应恰好一张 GMP 草稿，实际 {len(drafts)}"
    draft = drafts[0]
    assert draft.status == "pending_confirm"
    aligned = draft.aligned
    assert aligned["material_batch_no"] == "10423-260601"
    assert float(aligned["quantity"]) == 25
    assert aligned["unit"] == "kg"
    assert aligned["production_batch_no"] == "MA-ET-2026-050A"
    assert aligned.get("doc_type", "出库") == "出库"  # 缺省按出库
    assert aligned.get("department") == "提炼工程一部"

    # 确认卡片（dry-run 捕获，GMP 分支文案）
    cards = _cards_with_title(captured_sends, GMP_CONFIRM_CARD_TITLE)
    assert cards, "GMP 确认卡片未被捕获"
    content = _card_content(cards[-1])
    assert "物料批号：10423-260601" in content
    assert "领用数量：25" in content

    # 点确认 → submit_gmp → 写 GMP 物料出库总账
    adapter = WarehouseBitableAdapter()
    outcome = await confirm.handle_action(
        agent_db,
        value={
            "scene": GMP_OUTBOUND_SCENE,
            "action": "confirm",
            "draft_id": str(draft.id),
        },
        operator_open_id=open_id,
    )
    assert outcome.ok is True, f"submit 失败: {outcome.message}"
    assert "GMP 出库已登记" in outcome.message
    assert draft.status == "submitted"
    record_id = draft.target_record_id
    assert record_id and record_id.startswith("rec")

    try:
        # 读回核对：数量/单位/生产批号/日期/部门 落库且读回一致；
        # 物料批号因 Base 侧字段编辑限制降级不写入（degraded 标注人工补填）
        record = await adapter.get_record(GMP_OUTBOUND_TABLE, record_id)
        read_fields = record["fields"]
        assert float(read_fields.get("领用数量")) == 25
        assert "kg" in str(read_fields.get("单位"))
        assert "MA-ET-2026-050A" in str(read_fields.get("生产批号"))
        assert read_fields.get("日期") is not None
        assert "出库" in str(read_fields.get("单据类型"))
        assert "提炼工程一部" in str(read_fields.get("领用部门"))
        assert not read_fields.get("物料批号")  # 降级：未写入
        # 读回一致（回执无 ⚠ + audit 无 mismatch + degraded 标注批号）
        assert "不一致" not in outcome.message
        submit_audits = await _list_audits(
            agent_db, tool_name="submit_gmp", draft_id=draft.id
        )
        assert len(submit_audits) == 1
        assert submit_audits[0].result_status == "ok"
        assert submit_audits[0].error_code is None
        assert "物料名称" not in submit_audits[0].args_summary["fields"]  # lookup 拒写
        assert "物料批号" in submit_audits[0].args_summary["degraded"]  # 降级标注
        print(
            f"\n[live GMP] draft_no={draft.draft_no} record_id={record_id} "
            f"fields={submit_audits[0].args_summary['fields']} "
            f"degraded={submit_audits[0].args_summary['degraded']}"
        )
    finally:
        await adapter.delete_record(
            GMP_OUTBOUND_TABLE, record_id
        )  # 测试清理（精确 id）

    # 回执卡片（dry-run 捕获）：✅ GMP 标题 + record_id + 批号补填提示
    result_cards = _cards_with_title(captured_sends, GMP_RESULT_CARD_TITLE_OK)
    assert result_cards, "GMP 回执卡片未被捕获"
    result_content = _card_content(result_cards[-1])
    assert record_id in result_content
    assert "物料批号需在 Base 人工补填" in result_content


async def test_live_gmp_missing_field_asks(
    agent_db: AsyncSession,
    captured_sends: list[dict[str, str]],
    fresh_redis: aioredis.Redis,
) -> None:
    """缺生产批号：工具返回 missing → LLM 追问，不建草稿、不写 Base。"""
    open_id = "ou_live_gmp_ask"
    chat_id = f"oc_live_gmp_ask_{uuid.uuid4().hex[:8]}"
    event = _im_message_event(
        chat_id=chat_id,
        sender_open_id=open_id,
        text="三氯甲烷 10423-260601 出库 25kg",
    )
    await gateway.handle_im_message(event)

    # 无 GMP 草稿落库（工具 incomplete 分支不建稿；LLM 不应硬写）
    assert await _gmp_drafts(agent_db, open_id) == []

    # 回复含追问（问句或明确点名缺失字段）
    assert len(captured_sends) >= 2
    reply = _card_of(captured_sends[-1])
    text = reply["elements"][0]["content"]
    assert "？" in text or "?" in text or "生产批号" in text, (
        f"应追问缺失的生产批号，实际回复: {text[:120]}"
    )
    print(f"\n[live GMP 追问] 回复: {text[:160]}")
