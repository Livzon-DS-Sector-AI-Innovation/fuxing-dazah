"""S3 ticket 02 验收：成品出库对话登记 + 快递推送（create_finished_outbound_draft
→ 确认 → submit_outbound → send_card 推送链）。

单测（真库 whdev + 事务回滚隔离；Base/选项集刷新/发送全部注入假件不触网）：
- build_finished_fields：字段映射（产品名称/批号/出库量/单位/客户/用途/
  温度计/备注）、出库日期=当天毫秒时间戳、公式/lookup/created_user 拒写
  字段（品规/各品种库存/质量状态/库存数量/出库人）不入 fields、快递号
  附件字段降级开关默认跳过（degraded 标注）、用途不在选项集跳过、数量
  数字化、validate_write_fields 通过；
- create_finished_outbound_draft 工具：必收字段缺失 → missing + hint
  （无草稿落库）、产品名称不在选项集 → error 引导（product_not_found）、
  单位不在选项集 → error（unit_invalid）、齐全 → 草稿 + 用途默认「销售」
  + 单位归一 + 确认卡片（成品分支文案，dry-run 捕获）+ 用途/温度计选集
  未命中附 warning（不阻断）；
- SCENE_CONFIG：finished_outbound 已注册确认回调（票02 落地）；
- submit_outbound：状态前置（非 confirmed 拒绝）；快递号为空 → 回执 note
  无推送提示（FakeAdapter，不触网）；
- update_draft 成品场景：出库量/销售客户别名写入 aligned + 重发成品卡片；
- 确认/回执卡片成品分支：标题「📦 成品出库登记」/「✅ 成品出库已登记」，
  receipt 零变化对照。

live 主接缝 + 推送链（真 LLM + 真 Base，单会话串行两段）：
- 全链：gateway 文本「登记成品出库：硫酸黏菌素 批号 TEST-X2609 出库
  225000 十亿，客户 can，快递 SF123456」→ 草稿 → 确认卡片（dry-run 捕获，
  成品分支）→ 点确认 → 写成品出库台账（record_id 精记 finally 删）→
  读回一致（批号/出库量/单位/客户/出库日期）→ 回执 note 含快递推送引导
  「要推送给谁？回复 group:群ID 或 user:open_id」；⚠ 快递号为附件字段
  写入 API 专用文本字段「快递号(API)」（2026-09-07 新建，原字段为附件类型
  type 17 无法写文本）；
- 推送链：用户回复「推送给 group:oc_test_target」→ LLM 调 send_card
  （S1 确认门）→ 预览卡片（dry-run 捕获，内容含快递号）→ 点确认发送 →
  「📦 发货通知」外发卡片捕获（含快递号）。

数据安全纪律：live 写入仅经 submit_outbound create_record，record_id 取
draft.target_record_id 精确 finally 删除，严禁按批号等业务字段模糊清理。

运行：cd "E:\\dazah(仓储)\\backend" &&
      DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/dazah_whdev"
      uv run pytest tests/modules/warehouse/test_live_finished.py -v
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

import pytest
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.redis as app_core_redis
from app.modules.warehouse.agent import confirm, gateway
from app.modules.warehouse.agent import runner as runner_module
from app.modules.warehouse.agent.cards import (
    FINISHED_CHECK_OK_LINE,
    FINISHED_CONFIRM_CARD_TITLE,
    FINISHED_OUTBOUND_SCENE,
    FINISHED_RESULT_CARD_TITLE_MISMATCH,
    FINISHED_RESULT_CARD_TITLE_OK,
    RECEIPT_CONFIRM_CARD_TITLE,
    SEND_PREVIEW_CARD_TITLE,
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
    FINISHED_CHECK_FIELDS,
    FINISHED_OUTBOUND_TABLE,
    _today_ms,
    build_finished_fields,
    submit_outbound,
)
from app.modules.warehouse.agent.tools import draft_update
from app.modules.warehouse.agent.tools import finished as finished_module
from app.modules.warehouse.agent.tools import office as office_module
from app.modules.warehouse.agent.tools.draft_update import update_draft
from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter
from app.modules.warehouse.bitable_schema import (
    FIELD_TYPE_ATTACHMENT,
    FIELD_TYPE_SELECT,
    FieldMeta,
    validate_write_fields,
)
from app.modules.warehouse.feishu import notification
from app.modules.warehouse.models import WarehouseAgentAudit, WarehouseAgentDraft

# ── fixtures：db 注入 / 发送捕获 / Runner 单例 / Redis ──


@pytest.fixture
def agent_db(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> AsyncSession:
    """gateway/runner/draft_update/finished/office 五处 _db_session → 测试 session。

    create_finished_outbound_draft 在 Runner 工具循环内自开事务
    （finished._db_session）；推送链 send_card → request_card_send 走
    office._db_session——同指一个测试 session（不 commit），随 fixture
    回滚隔离。
    """

    @asynccontextmanager
    async def _patched() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(gateway, "_db_session", _patched)
    monkeypatch.setattr(runner_module, "_db_session", _patched)
    monkeypatch.setattr(draft_update, "_db_session", _patched)
    monkeypatch.setattr(finished_module, "_db_session", _patched)
    monkeypatch.setattr(office_module, "_db_session", _patched)
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
def finished_unit_env(
    agent_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> dict[str, FieldMeta]:
    """单测环境：成品选项集注入静态假件（不触网、不污染全局选项缓存）。

    返回注入的字段元数据（含 产品名称/单位/用途/温度计 选项集 + 快递号
    附件类型），使工具校验行为确定（与 live 侧真实 refresh_table_fields
    解耦）。
    """
    table_fields = _finished_fields_for_test()

    async def _fake_table_fields() -> dict[str, FieldMeta]:
        return table_fields

    monkeypatch.setattr(finished_module, "_finished_table_fields", _fake_table_fields)
    monkeypatch.setattr(submit_module, "_finished_table_fields", _fake_table_fields)
    return table_fields


# ── 测试数据工厂 ──


def _finished_fields_for_test() -> dict[str, FieldMeta]:
    """finished_outbound 字段元数据（单测注入；选项集为受控子集）。

    快递号按 Base 实测为附件字段（type 17，见 bitable_schema 快照）。
    """
    return {
        "产品名称": FieldMeta(
            type=FIELD_TYPE_SELECT,
            options=("硫酸黏菌素", "盐酸万古霉素", "达托霉素"),
        ),
        "产品批号": FieldMeta(type=1),
        "出库量": FieldMeta(type=2),
        "单位": FieldMeta(type=FIELD_TYPE_SELECT, options=("kg", "十亿", "g")),
        "销售客户": FieldMeta(type=1),
        "用途": FieldMeta(
            type=FIELD_TYPE_SELECT,
            options=("车间分装", "QC/注册", "销售", "生产领用", "客户小样"),
        ),
        "温度计": FieldMeta(
            type=FIELD_TYPE_SELECT, options=("已开启", "未开启", "无")
        ),
        "快递号(API)": FieldMeta(type=1),  # 2026-09-07 新建 API 专用文本字段
        "快递号": FieldMeta(type=FIELD_TYPE_ATTACHMENT),  # 原附件字段（保留）
        "备注": FieldMeta(type=1),
    }


def _finished_draft_row(
    aligned: dict[str, Any], *, status: str = "confirmed"
) -> WarehouseAgentDraft:
    """成品草稿 ORM 对象（aligned 即对话收集 working set；不入库的纯单元用）。"""
    return WarehouseAgentDraft(
        draft_no="WR20990101-201",
        scene=FINISHED_OUTBOUND_SCENE,
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


def _card_title_of(card: dict[str, Any]) -> str:
    return str(card.get("header", {}).get("title", {}).get("content") or "")


async def _list_audits(
    db: AsyncSession, *, tool_name: str, draft_id: Any | None = None
) -> list[WarehouseAgentAudit]:
    stmt = select(WarehouseAgentAudit).where(WarehouseAgentAudit.tool_name == tool_name)
    if draft_id is not None:
        stmt = stmt.where(WarehouseAgentAudit.draft_id == draft_id)
    rows = await db.execute(stmt)
    return list(rows.scalars().all())


async def _finished_drafts(db: AsyncSession, open_id: str) -> list[WarehouseAgentDraft]:
    rows = await db.execute(
        select(WarehouseAgentDraft).where(
            WarehouseAgentDraft.scene == FINISHED_OUTBOUND_SCENE,
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


class FakeAdapter:
    """submit_outbound 依赖的最小 adapter 面：create 自回显 + get 读回。

    read_override 覆盖指定字段的读回值（mismatch 注入口）；其余字段读回
    即写入值（规范化后一致）。
    """

    record_id = "rec_fake_finished_001"

    def __init__(self, read_override: dict[str, Any] | None = None) -> None:
        self.created: dict[str, Any] | None = None
        self.read_override = read_override or {}

    async def refresh_table_fields(self, table_key: str) -> dict[str, Any]:
        return {}

    async def create_record(
        self, table_key: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        self.created = dict(fields)
        return {"record_id": self.record_id, "fields": {}}

    async def get_record(self, table_key: str, record_id: str) -> dict[str, Any]:
        fields = dict(self.created or {})
        fields.update(self.read_override)
        return {"record_id": record_id, "fields": fields}


# ── 1. build_finished_fields：映射 / 拒写过滤 / 降级 / 日期 ──


def test_build_finished_fields_mapping_full(monkeypatch: pytest.MonkeyPatch) -> None:
    """全字段映射（快递号开关置 True）：数量数字化、只读字段拒写、日期=当天。"""
    draft = _finished_draft_row(
        {
            "product_name": "硫酸黏菌素",
            "product_batch_no": "TEST-X2609",
            "quantity": "225,000",
            "unit": "十亿",
            "customer": "can",
            "purpose": "销售",
            "express_no": "SF123456",
            "thermometer": "已开启",
            "remark": "备注文本",
        }
    )
    fields, degraded = build_finished_fields(
        draft,
        table_fields=_finished_fields_for_test(),
        today=date(2026, 9, 7),
    )

    assert degraded == []
    assert fields["产品名称"] == "硫酸黏菌素"
    assert fields["产品批号"] == "TEST-X2609"
    assert fields["出库量"] == 225000 and isinstance(fields["出库量"], int)
    assert fields["单位"] == "十亿"
    assert fields["销售客户"] == "can"
    assert fields["用途"] == "销售"
    assert fields["快递号(API)"] == "SF123456"  # 开关置 True：透传
    assert fields["温度计"] == "已开启"
    assert fields["备注"] == "备注文本"
    assert fields["出库日期"] == _today_ms(date(2026, 9, 7))
    # 公式/lookup/created_user 拒写——不进入写入字段（bitable_schema 快照口径）
    for readonly in ("品规", "各品种库存", "质量状态", "库存数量", "出库人"):
        assert readonly not in fields
    # S0 写契约本地校验通过
    validate_write_fields(FINISHED_OUTBOUND_TABLE, fields)


def test_build_finished_fields_express_writes_new_text_field() -> None:
    """快递号写入 API 专用文本字段「快递号(API)」（原字段为附件类型不可写文本）。"""
    draft = _finished_draft_row(
        {
            "product_name": "硫酸黏菌素",
            "product_batch_no": "TEST-X2609",
            "quantity": 225000,
            "unit": "十亿",
            "customer": "can",
            "express_no": "SF123456",
        }
    )
    fields, degraded = build_finished_fields(
        draft, table_fields=_finished_fields_for_test(), today=date(2026, 9, 7)
    )
    assert fields["快递号(API)"] == "SF123456"
    assert "快递号(API)" not in degraded
    assert degraded == []
    validate_write_fields(FINISHED_OUTBOUND_TABLE, fields)


def test_build_finished_fields_purpose_mismatch_degraded() -> None:
    """用途不在选项集 → 跳过写入 + degraded 标注（submit 侧人工补填口径）。"""
    draft = _finished_draft_row(
        {
            "product_name": "硫酸黏菌素",
            "quantity": 100,
            "unit": "kg",
            "customer": "can",
            "purpose": "内销",
        }
    )
    fields, degraded = build_finished_fields(
        draft, table_fields=_finished_fields_for_test(), today=date(2026, 9, 7)
    )
    assert "用途" in degraded and "用途" not in fields
    assert fields["产品名称"] == "硫酸黏菌素" and fields["销售客户"] == "can"
    validate_write_fields(FINISHED_OUTBOUND_TABLE, fields)


def test_build_finished_fields_unit_mismatch_and_bad_quantity() -> None:
    """单位不在选项集 → 跳过 + degraded；出库量非数字 → 跳过 + degraded。"""
    draft = _finished_draft_row(
        {
            "product_name": "硫酸黏菌素",
            "product_batch_no": "TEST-X2609",
            "quantity": "二十五",
            "unit": "吨",
            "customer": "can",
        }
    )
    fields, degraded = build_finished_fields(
        draft, table_fields=_finished_fields_for_test(), today=date(2026, 9, 7)
    )
    assert "单位" in degraded and "单位" not in fields
    assert "出库量" in degraded and "出库量" not in fields
    assert fields["产品批号"] == "TEST-X2609"
    assert fields["出库日期"] == _today_ms(date(2026, 9, 7))
    validate_write_fields(FINISHED_OUTBOUND_TABLE, fields)


def test_build_finished_fields_empty_fields_only_date() -> None:
    """aligned 为空 → 仅恒写出库日期（当日），无 degraded。"""
    draft = _finished_draft_row({})
    fields, degraded = build_finished_fields(
        draft, table_fields=_finished_fields_for_test(), today=date(2026, 9, 7)
    )
    assert degraded == []
    assert fields == {"出库日期": _today_ms(date(2026, 9, 7))}


# ── 2. create_finished_outbound_draft 工具：缺失/非法/成功 ──


async def test_create_finished_draft_missing_fields_returns_missing(
    agent_db: AsyncSession, finished_unit_env: Any
) -> None:
    """缺销售客户 → missing + hint（LLM 追问），不建草稿。"""
    result = await finished_module.create_finished_outbound_draft(
        {
            "产品名称": "硫酸黏菌素",
            "产品批号": "TEST-X2609",
            "出库量": "225000",
            "单位": "十亿",
        },
        _ctx={"open_id": "ou_fin_miss", "chat_id": "oc_fin_miss"},
    )
    assert result["status"] == "incomplete"
    assert result["missing"] == ["销售客户"]
    assert "请补充" in result["hint"]
    assert "销售客户" in result["hint"]
    assert await _finished_drafts(agent_db, "ou_fin_miss") == []


async def test_create_finished_draft_unknown_field_error(
    agent_db: AsyncSession, finished_unit_env: Any
) -> None:
    """未知字段 → error 引导（列出可收集字段），不建草稿。"""
    result = await finished_module.create_finished_outbound_draft(
        {"产品名称": "硫酸黏菌素", "件数": "10"},
        _ctx={"open_id": "ou_fin_unk", "chat_id": "oc_fin_unk"},
    )
    assert "error" in result
    assert "件数" in result["error"]
    assert await _finished_drafts(agent_db, "ou_fin_unk") == []


async def test_create_finished_draft_invalid_product_error(
    agent_db: AsyncSession, finished_unit_env: Any
) -> None:
    """产品名称不在选项集 → error 引导核对（不猜测），不建草稿。"""
    result = await finished_module.create_finished_outbound_draft(
        {
            "产品名称": "不存在的产品",
            "产品批号": "TEST-X2609",
            "出库量": 225000,
            "单位": "十亿",
            "销售客户": "can",
        },
        _ctx={"open_id": "ou_fin_bad", "chat_id": "oc_fin_bad"},
    )
    assert "error" in result
    assert result["error_code"] == "product_not_found"
    assert "核对" in result["error"]
    assert await _finished_drafts(agent_db, "ou_fin_bad") == []


async def test_create_finished_draft_invalid_unit_error(
    agent_db: AsyncSession, finished_unit_env: Any
) -> None:
    """单位不在选项集 → error 引导（可选 kg/十亿/g）。"""
    result = await finished_module.create_finished_outbound_draft(
        {
            "产品名称": "硫酸黏菌素",
            "产品批号": "TEST-X2609",
            "出库量": 225000,
            "单位": "吨",
            "销售客户": "can",
        },
        _ctx={"open_id": "ou_fin_unit", "chat_id": "oc_fin_unit"},
    )
    assert "error" in result and result["error_code"] == "unit_invalid"
    assert await _finished_drafts(agent_db, "ou_fin_unit") == []


async def test_create_finished_draft_success_with_card(
    agent_db: AsyncSession,
    finished_unit_env: Any,
    captured_sends: list[dict[str, str]],
) -> None:
    """齐全 → 草稿 + 用途默认「销售」+ 单位归一 + 成品确认卡片 + 降级预告。"""
    result = await finished_module.create_finished_outbound_draft(
        {
            "产品名称": "硫酸黏菌素",
            "产品批号": "TEST-X2609",
            "出库量": "225000",
            "单位": "十亿",
            "销售客户": "can",
            "快递号": "SF123456",
            "温度计": "不存在的档位",
        },
        _ctx={"open_id": "ou_fin_ok", "chat_id": "oc_fin_ok"},
    )
    assert "error" not in result, result
    assert result["status"] == "pending_confirm"
    assert result["draft_no"]
    # 用途缺省「销售」（在选项集内）；温度计选集未命中仅保留原文
    assert result["fields"]["purpose"] == "销售"
    assert result["fields"]["thermometer"] == "不存在的档位"
    # 预告：快递号附件字段人工补填 + 温度计选集未命中（均不阻断登记）
    assert not any("快递号需在 Base 人工补填" in w for w in result["warnings"])
    assert any("温度计" in w for w in result["warnings"])

    drafts = await _finished_drafts(agent_db, "ou_fin_ok")
    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.status == "pending_confirm"
    assert draft.aligned["product_name"] == "硫酸黏菌素"
    assert float(draft.aligned["quantity"]) == 225000
    assert draft.aligned["unit"] == "十亿"
    assert draft.aligned["customer"] == "can"
    assert draft.aligned["express_no"] == "SF123456"
    assert draft.recognized == draft.aligned  # 收集值留底 = working set

    # 确认卡片（成品分支）：标题/字段行/按钮 value.scene
    cards = _cards_with_title(captured_sends, FINISHED_CONFIRM_CARD_TITLE)
    assert len(cards) == 1
    card = cards[0]
    content = _card_content(card)
    assert "1. 产品名称：硫酸黏菌素" in content
    assert "2. 产品批号：TEST-X2609" in content
    assert "3. 出库量：225000" in content
    assert "4. 单位：十亿" in content
    assert "5. 销售客户：can" in content
    assert "快递号：SF123456" in content
    buttons = card["elements"][2]["actions"]
    assert buttons[0]["value"]["scene"] == FINISHED_OUTBOUND_SCENE
    assert buttons[0]["value"]["draft_id"] == str(draft.id)
    assert buttons[1]["value"]["action"] == "cancel"

    # 状态机审计：create / mark_aligned / send_confirm_card
    audits = await _list_audits(agent_db, tool_name="draft_flow", draft_id=draft.id)
    assert sorted(a.args_summary["action"] for a in audits) == [
        "create",
        "mark_aligned",
        "send_confirm_card",
    ]


# ── 3. SCENE_CONFIG / submit_outbound 前置 / 卡片分支 ──


def test_scene_config_finished_registration() -> None:
    """SCENE_CONFIG：finished_outbound 已注册确认回调（票02 落地）。"""
    assert set(SCENE_CONFIG) == {"receipt", "gmp_outbound", "finished_outbound"}
    assert confirm.is_registered_scene("finished_outbound")

    config = SCENE_CONFIG["finished_outbound"]
    assert config.required_fields == (
        "product_name",
        "product_batch_no",
        "quantity",
        "unit",
        "customer",
    )
    # 可写字段集：10 个（出库日期恒写 + 9 收集字段，含 快递号(API)）
    # 与 品规/各品种库存/质量状态/库存数量/出库人（公式/lookup/created_user）
    assert set(config.writable_fields) == {
        "出库日期",
        "产品名称",
        "产品批号",
        "出库量",
        "单位",
        "销售客户",
        "用途",
        "温度计",
        "备注",
        "快递号(API)",
    }


async def test_submit_outbound_requires_confirmed(db_session: AsyncSession) -> None:
    """状态前置：非 confirmed（aligned）直接提交 → DraftFlowError。"""
    draft = _finished_draft_row({"product_name": "硫酸黏菌素"}, status="aligned")
    with pytest.raises(DraftFlowError):
        await submit_outbound(db_session, draft)
    assert draft.status == "aligned"  # 未被改动


def test_render_finished_confirm_card_branch_and_defensive() -> None:
    """scene=finished_outbound → 成品卡片；字段缺失降级（—），不抛错。"""
    draft = WarehouseAgentDraft(
        draft_no="WR20990101-210",
        scene=FINISHED_OUTBOUND_SCENE,
        recognized={},
        aligned={},
    )
    card = render_receipt_confirm_card(draft)
    assert card["header"]["title"]["content"] == FINISHED_CONFIRM_CARD_TITLE
    content = _card_content(card)
    assert "1. 产品名称：— ⚠" in content  # 必收缺失提醒
    assert "1. 用途：—" in content  # 选填缺省无 ⚠（分区独立编号）

    # receipt 零变化对照：同函数 scene=receipt 走入库卡片
    receipt_draft = WarehouseAgentDraft(
        draft_no="WR20990101-211", scene="receipt", recognized={}, aligned={}
    )
    receipt_card = render_receipt_confirm_card(receipt_draft)
    assert receipt_card["header"]["title"]["content"] == RECEIPT_CONFIRM_CARD_TITLE


def test_render_finished_result_card_titles() -> None:
    """回执卡片：finished 用成品标题/核对文案/快递号降级提示；receipt 不变。"""
    draft = WarehouseAgentDraft(
        draft_no="WR20990101-220", scene=FINISHED_OUTBOUND_SCENE
    )
    check = {
        "consistent": True,
        "mismatches": [],
        "written": {
            "产品批号": "TEST-X2609",
            "出库量": 225000,
            "单位": "十亿",
            "销售客户": "can",
        },
        "record_id": "recFIN001",
        "degraded": [],
    }
    card = render_receipt_result_card(draft, check)
    assert card["header"]["title"]["content"] == FINISHED_RESULT_CARD_TITLE_OK
    assert card["header"]["template"] == "green"
    content = _card_content(card)
    assert FINISHED_CHECK_OK_LINE in content
    assert "快递号需在 Base 人工补填" not in content  # 新字段写入，无降级提示

    mismatch = render_receipt_result_card(
        draft,
        {
            **check,
            "consistent": False,
            "mismatches": [{"field": "出库量", "written": "225000", "read_back": "0"}],
        },
    )
    assert mismatch["header"]["title"]["content"] == FINISHED_RESULT_CARD_TITLE_MISMATCH
    assert mismatch["header"]["template"] == "red"


# ── 4. submit_outbound：快递号为空回执无推送提示（FakeAdapter 不触网）──


async def test_submit_outbound_note_without_express_no_push_hint(
    agent_db: AsyncSession,
    finished_unit_env: Any,
    captured_sends: list[dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """快递号为空：提交成功 → 回执 note 无「推送」引导；回执卡片成品标题。"""
    draft = await create_dialog_draft(
        agent_db,
        scene=FINISHED_OUTBOUND_SCENE,
        fields={
            "product_name": "硫酸黏菌素",
            "product_batch_no": "TEST-X2609",
            "quantity": 225000,
            "unit": "十亿",
            "customer": "can",
        },
        open_id="ou_fin_noexp",
        chat_id="oc_fin_noexp",
    )
    draft.status = "confirmed"  # 模拟确认门已置位（S1 语义）

    fake = FakeAdapter()
    monkeypatch.setattr(submit_module, "get_adapter", lambda: fake)

    note = await submit_outbound(agent_db, draft)
    assert note is not None
    assert "成品出库已登记" in note
    assert "推送" not in note and "快递" not in note
    assert draft.status == "submitted"
    assert draft.target_record_id == FakeAdapter.record_id
    # 快递号未收集 → 不写入（含新字段）
    assert "快递号(API)" not in fake.created
    # 写入字段：出库日期 + 8 收集字段中的 5 必收；无快递号
    assert fake.created is not None
    assert fake.created["出库量"] == 225000

    # 审计 + 回执卡片
    audits = await _list_audits(
        agent_db, tool_name="submit_outbound", draft_id=draft.id
    )
    assert len(audits) == 1 and audits[0].result_status == "ok"
    result_cards = _cards_with_title(captured_sends, FINISHED_RESULT_CARD_TITLE_OK)
    assert result_cards, "成品回执卡片未被捕获"


# ── 5. update_draft 成品场景 ──


async def test_update_draft_finished_scene_fields_and_resend(
    agent_db: AsyncSession,
    finished_unit_env: Any,
    captured_sends: list[dict[str, str]],
) -> None:
    """成品草稿对话修改：出库量/销售客户别名 → aligned + 重发成品确认卡片。"""
    draft = await create_dialog_draft(
        agent_db,
        scene=FINISHED_OUTBOUND_SCENE,
        fields={
            "product_name": "硫酸黏菌素",
            "product_batch_no": "TEST-X2609",
            "quantity": 225000,
            "unit": "十亿",
            "customer": "can",
            "purpose": "销售",
        },
        open_id="ou_fin_upd",
        chat_id="oc_fin_upd",
    )
    await send_confirm_card(agent_db, draft, chat_id="oc_fin_upd")
    assert len(_cards_with_title(captured_sends, FINISHED_CONFIRM_CARD_TITLE)) == 1

    result = await update_draft(
        draft.draft_no,
        {"出库量": "200", "销售客户": "new_customer"},
        _ctx={"open_id": "ou_fin_upd", "chat_id": "oc_fin_upd"},
    )
    assert "error" not in result, result
    assert result["updated"]["quantity"] == 200  # 数字化
    assert result["updated"]["customer"] == "new_customer"
    assert float(draft.aligned["quantity"]) == 200
    assert draft.aligned["customer"] == "new_customer"
    assert draft.status == "pending_confirm"

    # 重发的是成品分支卡片（出库量 200 上卡）
    cards = _cards_with_title(captured_sends, FINISHED_CONFIRM_CARD_TITLE)
    assert len(cards) == 2
    assert "出库量：200" in _card_content(cards[-1])

    # submit 真身对应的 CHECK_FIELDS 口径（批号/出库量/单位/客户）
    assert FINISHED_CHECK_FIELDS == (
    ("产品批号", "出库量", "单位", "销售客户", "快递号(API)")
)


# ── 6. live 主接缝 + 推送链：对话 → 草稿 → 确认 → 写 Base → 推送 ──


async def test_live_finished_dialog_submit_push_full_flow(
    agent_db: AsyncSession,
    captured_sends: list[dict[str, str]],
    fresh_redis: aioredis.Redis,
) -> None:
    """真 LLM + 真 Base 全链（单会话串行）：

    ① 登记：文本 → 草稿 → 确认卡片 → 确认 → 写成品出库台账 → 读回一致
       → 回执 note 含快递推送引导；
    ② 推送：用户回复目标 → send_card 确认门预览 → 确认发送 → 外发卡片。

    数据安全：仅经 submit_outbound 写入，record_id 取 draft.target_record_id
    精确 finally 删除（严禁按批号模糊清理）。
    """
    open_id = "ou_live_finished"
    chat_id = f"oc_live_finished_{uuid.uuid4().hex[:8]}"
    event = _im_message_event(
        chat_id=chat_id,
        sender_open_id=open_id,
        text=(
            "登记成品出库：硫酸黏菌素 批号 TEST-X2609 出库 225000 十亿，"
            "客户 can，快递 SF123456"
        ),
    )
    await gateway.handle_im_message(event)

    # ── ① 登记 ──
    # 工具被调用且成功（Runner 工具审计）
    tool_audits = await _list_audits(
        agent_db, tool_name="create_finished_outbound_draft"
    )
    assert tool_audits, "create_finished_outbound_draft 未被 Runner 调用（LLM 行为偏离）"
    assert any(a.result_status == "ok" for a in tool_audits)

    # 草稿落库：对话收集字段（无识别步骤，created→aligned→pending_confirm）
    drafts = await _finished_drafts(agent_db, open_id)
    assert len(drafts) == 1, f"应恰好一张成品草稿，实际 {len(drafts)}"
    draft = drafts[0]
    assert draft.status == "pending_confirm"
    aligned = draft.aligned
    assert aligned["product_name"] == "硫酸黏菌素"
    assert aligned["product_batch_no"] == "TEST-X2609"
    assert float(aligned["quantity"]) == 225000
    assert aligned["unit"] == "十亿"
    assert aligned["customer"] == "can"
    assert aligned["express_no"] == "SF123456"
    assert aligned.get("purpose", "销售") == "销售"  # 缺省按销售

    # 确认卡片（dry-run 捕获，成品分支文案）
    cards = _cards_with_title(captured_sends, FINISHED_CONFIRM_CARD_TITLE)
    assert cards, "成品确认卡片未被捕获"
    content = _card_content(cards[-1])
    assert "产品名称：硫酸黏菌素" in content
    assert "产品批号：TEST-X2609" in content
    assert "快递号：SF123456" in content

    # 点确认 → submit_outbound → 写成品出库台账
    adapter = WarehouseBitableAdapter()
    outcome = await confirm.handle_action(
        agent_db,
        value={
            "scene": FINISHED_OUTBOUND_SCENE,
            "action": "confirm",
            "draft_id": str(draft.id),
        },
        operator_open_id=open_id,
    )
    assert outcome.ok is True, f"submit 失败: {outcome.message}"
    assert "成品出库已登记" in outcome.message
    # 回执含快递推送引导（票02 验收口径）
    assert "要推送给谁？回复 group:群ID 或 user:open_id" in outcome.message
    assert "SF123456" in outcome.message
    assert draft.status == "submitted"
    record_id = draft.target_record_id
    assert record_id and record_id.startswith("rec")

    try:
        # 读回核对：批号/出库量/单位/客户/出库日期 落库且读回一致；
        # 快递号写入 API 专用文本字段（新字段可写可读回）
        record = await adapter.get_record(FINISHED_OUTBOUND_TABLE, record_id)
        read_fields = record["fields"]
        assert "TEST-X2609" in str(read_fields.get("产品批号"))
        assert float(read_fields.get("出库量")) == 225000
        assert "十亿" in str(read_fields.get("单位"))
        assert "can" in str(read_fields.get("销售客户"))
        assert read_fields.get("出库日期") is not None
        assert read_fields.get("快递号(API)"), "新字段应写入并可读回"
        # 读回一致（audit 无 mismatch + degraded 标注快递号）
        assert "不一致" not in outcome.message.split("\n")[0]
        submit_audits = await _list_audits(
            agent_db, tool_name="submit_outbound", draft_id=draft.id
        )
        assert len(submit_audits) == 1
        assert submit_audits[0].result_status == "ok"
        assert submit_audits[0].error_code is None
        # 只读字段拒写：不进入写入字段
        assert "品规" not in submit_audits[0].args_summary["fields"]
        assert "出库人" not in submit_audits[0].args_summary["fields"]
        assert "快递号" not in submit_audits[0].args_summary.get("degraded", [])  # 不再降级
        print(
            f"\n[live 成品出库] draft_no={draft.draft_no} record_id={record_id} "
            f"fields={submit_audits[0].args_summary['fields']} "
            f"degraded={submit_audits[0].args_summary['degraded']}"
        )
    finally:
        await adapter.delete_record(
            FINISHED_OUTBOUND_TABLE, record_id
        )  # 测试清理（精确 id）

    # 回执卡片（dry-run 捕获）：✅ 成品标题 + record_id + 快递号补填提示
    result_cards = _cards_with_title(captured_sends, FINISHED_RESULT_CARD_TITLE_OK)
    assert result_cards, "成品回执卡片未被捕获"
    result_content = _card_content(result_cards[-1])
    assert record_id in result_content
    assert "快递号需在 Base 人工补填" not in result_content

    # ── ② 推送链：用户回复目标 → send_card 确认门 → 确认发送 ──
    push_event = _im_message_event(
        chat_id=chat_id,
        sender_open_id=open_id,
        text="推送给 group:oc_test_target",
    )
    await gateway.handle_im_message(push_event)

    # LLM 调用 send_card（S1 确认门，不直接发送）
    send_audits = await _list_audits(agent_db, tool_name="send_card")
    assert send_audits, "send_card 未被 Runner 调用（LLM 行为偏离）"
    assert any(a.result_status == "ok" for a in send_audits)

    # 预览卡片（dry-run 捕获）：内容含快递号（发货通知数据来自登记结果）
    previews = _cards_with_title(captured_sends, SEND_PREVIEW_CARD_TITLE)
    assert previews, "send_card 预览卡片未被捕获"
    preview = previews[-1]
    preview_content = _card_content(preview)
    assert "SF123456" in preview_content
    buttons = preview["elements"][2]["actions"]
    assert buttons[0]["value"]["scene"] == "send_card"
    send_draft_id = buttons[0]["value"]["draft_id"]
    assert buttons[0]["value"]["action"] == "confirm"

    # 点「确认发送」→ _execute_send_card → 真实外发（dry-run 捕获）
    send_outcome = await confirm.handle_action(
        agent_db,
        value={"scene": "send_card", "action": "confirm", "draft_id": send_draft_id},
        operator_open_id=open_id,
    )
    assert send_outcome.ok is True, f"send_card 确认失败: {send_outcome.message}"
    assert "oc_test_target" in (send_outcome.message or "")

    # 外发卡片：📦 发货通知（标题含「发货通知」），内容含快递号
    outgoing = [
        c
        for c in _interactive_cards(captured_sends)
        if "发货通知" in _card_title_of(c)
    ]
    assert outgoing, "发货通知外发卡片未被捕获"
    outgoing_content = _card_content(outgoing[-1])
    assert "SF123456" in outgoing_content
    assert "硫酸黏菌素" in outgoing_content
    print(f"\n[live 快递推送] 外发卡片标题={_card_title_of(outgoing[-1])!r}")
