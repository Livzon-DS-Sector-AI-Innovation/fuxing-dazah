"""成品入库识别测试（V3.0 §4.6，C 期欠账补票）。

接缝（沿 test_live_finished 样板）：
- build_finished_receipt_fields 纯函数（aligned 优先/recognized 兜底、
  入库日期默认今天、质量状态恒待检、车间写备注前缀）；
- create_finished_receipt_draft 工具（missing 追问不落草稿 / 未知字段 /
  成功建草稿+确认卡）；
- submit_finished_receipt（confirmed 前置 / FakeAdapter 全链 create→读回→
  submitted→审计 / mismatch 标注）；
- 卡片分支（确认卡 🏭 成品入库登记 / 回执卡 ✅ 成品入库已登记）；
- classify_document 失败回落原辅料 + recognize_finished_receipt JSON 容错；
- gateway 图片路由：分类=成品 → finished_receipt 草稿（独立审计作用域）→
  确认 → FakeAdapter 提交全链（不触真 Base）。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.redis as app_core_redis
from app.modules.warehouse.agent import cards, gateway
from app.modules.warehouse.agent import runner as runner_module
from app.modules.warehouse.agent.pipeline import (
    FINISHED_RECEIPT_SCENE,
    SCENE_CONFIG,
    RecognizedField,
    RecognizedFinishedReceipt,
    build_finished_receipt_fields,
)
from app.modules.warehouse.agent.pipeline import draft_flow as df
from app.modules.warehouse.agent.pipeline import submit as submit_module
from app.modules.warehouse.agent.pipeline.recognizer import (
    DOC_TYPE_RAW,
    recognize_finished_receipt,
)
from app.modules.warehouse.agent.tools import finished_receipt as fr_module
from app.modules.warehouse.bitable_schema import (
    FIELD_TYPE_SELECT,
    FieldMeta,
)
from app.modules.warehouse.models import WarehouseAgentAudit, WarehouseAgentDraft

# ── fixtures（test_live_finished 同款注入口）──


@pytest.fixture
def agent_db(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> AsyncSession:
    @asynccontextmanager
    async def _patched() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(gateway, "_db_session", _patched)
    monkeypatch.setattr(runner_module, "_db_session", _patched)
    monkeypatch.setattr(fr_module, "_db_session", _patched)
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


def _fr_fields_for_test() -> dict[str, FieldMeta]:
    """finished_receipt 字段元数据（单测受控选项集；质量状态含待检）。"""
    return {
        "入库日期": FieldMeta(type=5),
        "产品名称": FieldMeta(
            type=FIELD_TYPE_SELECT, options=("达托霉素", "替考拉宁", "硫酸黏菌素")
        ),
        "产品批号": FieldMeta(type=1),
        "品规": FieldMeta(
            type=FIELD_TYPE_SELECT, options=("DA低规", "DT高规二期（AB线）")
        ),
        "入库数量": FieldMeta(type=2),
        "单位": FieldMeta(type=FIELD_TYPE_SELECT, options=("kg", "十亿", "g")),
        "库区位置": FieldMeta(type=1),
        "质量状态": FieldMeta(
            type=FIELD_TYPE_SELECT, options=("合格", "待检", "待处理", "退货")
        ),
        "生产日期": FieldMeta(type=1),  # 该表文本列
        "有效期": FieldMeta(type=1),
        "备注": FieldMeta(type=1),
    }


@pytest.fixture
def fr_unit_env(
    agent_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> dict[str, FieldMeta]:
    table_fields = _fr_fields_for_test()

    async def _fake_table_fields() -> dict[str, FieldMeta]:
        return table_fields

    monkeypatch.setattr(fr_module, "_finished_receipt_table_fields", _fake_table_fields)
    monkeypatch.setattr(
        submit_module, "_finished_receipt_table_fields", _fake_table_fields
    )
    return table_fields


# ── 工厂 ──


def _fr_draft_row(
    aligned: dict[str, Any],
    recognized: dict[str, Any] | None = None,
    *,
    status: str = "confirmed",
) -> WarehouseAgentDraft:
    return WarehouseAgentDraft(
        draft_no="WR20990101-301",
        scene=FINISHED_RECEIPT_SCENE,
        status=status,
        recognized=recognized if recognized is not None else dict(aligned),
        aligned=dict(aligned),
    )


def _card_of(payload: dict[str, str]) -> dict[str, Any]:
    return json.loads(payload["content"])


def _interactive_cards(sends: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [_card_of(p) for p in sends if p.get("msg_type") == "interactive"]


def _card_content(card: dict[str, Any]) -> str:
    return "\n".join(
        element.get("content") or ""
        for element in card.get("body", {}).get("elements", [])
        if isinstance(element, dict)
    )


def _confirm_buttons(card: dict[str, Any]) -> list[dict[str, Any]]:
    """按钮行=column_set（2.0 卡片按钮约定）：遍历 columns 收集按钮。"""
    buttons: list[dict[str, Any]] = []
    for element in card.get("body", {}).get("elements", []):
        if isinstance(element, dict) and element.get("tag") == "column_set":
            for column in element.get("columns") or []:
                buttons.extend(column.get("elements") or [])
    return buttons


async def _drain_gateway_tasks() -> None:
    tasks = [t for t in list(gateway._background_tasks) if not t.done()]
    for t in tasks:
        await t


class FakeAdapter:
    """submit_finished_receipt 最小 adapter 面（create 自回显 + get 读回）。

    多行提交按序返回 rec_fake_fr_001… 并逐行记录 created_rows（按 record_id 读回）。
    """

    record_id = "rec_fake_fr_001"

    def __init__(self, read_override: dict[str, Any] | None = None) -> None:
        self.created: dict[str, Any] | None = None
        self.created_rows: list[dict[str, Any]] = []
        self.read_override = read_override or {}
        self._seq = 0

    async def refresh_table_fields(self, table_key: str) -> dict[str, Any]:
        return {}

    async def create_record(
        self, table_key: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        self._seq += 1
        rid = f"rec_fake_fr_{self._seq:03d}"
        self.created_rows.append({"record_id": rid, "fields": dict(fields)})
        self.created = dict(fields)
        return {"record_id": rid, "fields": {}}

    async def get_record(self, table_key: str, record_id: str) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        for row in self.created_rows:
            if row["record_id"] == record_id:
                fields = dict(row["fields"])
                break
        else:
            fields = dict(self.created or {})
        for name, value in self.read_override.items():
            fields[name] = value
        return {"record_id": record_id, "fields": fields}


# ═══════════════════════════════════════════════════════════════
# 字段组装（纯函数）
# ═══════════════════════════════════════════════════════════════


class TestBuildFinishedReceiptFields:
    def test_mapping_defaults_and_constant_quality(
        self, fr_unit_env: dict[str, FieldMeta]
    ) -> None:
        draft = _fr_draft_row(
            {
                "product_name": "达托霉素",
                "product_batch_no": "DA2609001",
                "quantity": "100",
                "unit": "kg",
            }
        )
        fields, degraded = build_finished_receipt_fields(
            draft, table_fields=fr_unit_env, today=datetime(2026, 9, 21)
        )
        assert degraded == []
        assert fields["产品名称"] == "达托霉素"
        assert fields["产品批号"] == "DA2609001"
        assert fields["入库数量"] == 100  # 整值 int 化
        assert fields["单位"] == "kg"
        # 质量状态恒写待检；入库日期默认当天毫秒时间戳
        assert fields["质量状态"] == "待检"
        assert fields["入库日期"] == int(
            datetime(2026, 9, 21, tzinfo=UTC).timestamp() * 1000
        )
        assert "备注" not in fields  # 无车间无备注

    def test_aligned_overrides_recognized(
        self, fr_unit_env: dict[str, FieldMeta]
    ) -> None:
        """识别值带置信度落 recognized、对话修改落 aligned——aligned 覆盖优先。"""
        draft = _fr_draft_row(
            aligned={"quantity": 55},
            recognized={
                "product_name": {"value": "达托霉素", "confidence": 0.9},
                "product_batch_no": {"value": "DA2609001", "confidence": 0.85},
                "quantity": {"value": "500", "confidence": 0.8},
                "unit": {"value": "kg", "confidence": 0.9},
            },
        )
        fields, _ = build_finished_receipt_fields(
            draft, table_fields=fr_unit_env, today=datetime(2026, 9, 21)
        )
        assert fields["入库数量"] == 55

    def test_workshop_goes_to_remark_prefix(
        self, fr_unit_env: dict[str, FieldMeta]
    ) -> None:
        draft = _fr_draft_row(
            {
                "product_name": "达托霉素",
                "product_batch_no": "DA2609001",
                "quantity": "10",
                "unit": "kg",
                "workshop": "提炼工程一部",
                "remark": "外包装完好",
            }
        )
        fields, _ = build_finished_receipt_fields(
            draft, table_fields=fr_unit_env, today=datetime(2026, 9, 21)
        )
        assert fields["备注"] == "入库车间：提炼工程一部；外包装完好"
        # 入库车间列（lookup 只读）绝不出现在写入字段
        assert "入库车间" not in fields

    def test_receipt_date_parsed_or_fallback(
        self, fr_unit_env: dict[str, FieldMeta]
    ) -> None:
        draft_ok = _fr_draft_row(
            {
                "product_name": "达托霉素",
                "product_batch_no": "B",
                "quantity": "1",
                "unit": "kg",
                "receipt_date": "2026-09-20",
            }
        )
        fields, degraded = build_finished_receipt_fields(
            draft_ok, table_fields=fr_unit_env, today=datetime(2026, 9, 21)
        )
        assert degraded == []
        assert fields["入库日期"] == int(
            datetime(2026, 9, 20, tzinfo=UTC).timestamp() * 1000
        )

        draft_bad = _fr_draft_row(
            {
                "product_name": "达托霉素",
                "product_batch_no": "B",
                "quantity": "1",
                "unit": "kg",
                "receipt_date": "不是日期",
            }
        )
        fields_bad, degraded_bad = build_finished_receipt_fields(
            draft_bad, table_fields=fr_unit_env, today=datetime(2026, 9, 21)
        )
        assert degraded_bad == ["入库日期"]
        assert fields_bad["入库日期"] == int(
            datetime(2026, 9, 21, tzinfo=UTC).timestamp() * 1000
        )

    def test_bad_select_degrades_not_raises(
        self, fr_unit_env: dict[str, FieldMeta]
    ) -> None:
        draft = _fr_draft_row(
            {
                "product_name": "不存在的产品",
                "product_batch_no": "B",
                "quantity": "1",
                "unit": "吨",
            }
        )
        fields, degraded = build_finished_receipt_fields(
            draft, table_fields=fr_unit_env, today=datetime(2026, 9, 21)
        )
        assert set(degraded) == {"产品名称", "单位"}
        assert "产品名称" not in fields and "单位" not in fields
        assert fields["质量状态"] == "待检"  # 恒写不受降级影响


# ═══════════════════════════════════════════════════════════════
# 场景注册 / 对话工具
# ═══════════════════════════════════════════════════════════════


class TestSceneRegistration:
    def test_scene_config_wiring(self) -> None:
        config = SCENE_CONFIG[FINISHED_RECEIPT_SCENE]
        assert config.name_cn == "成品入库登记"
        assert config.required_fields == (
            "product_name",
            "product_batch_no",
            "quantity",
            "unit",
        )
        assert "入库车间" not in config.writable_fields  # lookup 只读
        assert "件数" not in config.writable_fields  # 公式只读
        assert "包装规格" not in config.writable_fields  # 多选无写入先例


class TestCreateFinishedReceiptDraft:
    async def test_missing_fields_ask_not_create(
        self, agent_db: AsyncSession
    ) -> None:
        result = await fr_module.create_finished_receipt_draft(
            {"product_name": "达托霉素", "product_batch_no": "DA2609001"},
            _ctx={"open_id": "ou_test_missing_fr", "chat_id": "oc_1"},
        )
        assert result["status"] == "incomplete"
        assert set(result["missing"]) == {"入库数量", "单位"}
        # 未落草稿（按本测试 open_id 圈定——共享库存在真机/验收产生的真实草稿）
        rows = (
            await agent_db.execute(
                select(WarehouseAgentDraft).where(
                    WarehouseAgentDraft.scene == FINISHED_RECEIPT_SCENE,
                    WarehouseAgentDraft.created_by_open_id == "ou_test_missing_fr",
                )
            )
        ).scalars().all()
        assert rows == []

    async def test_unknown_field_rejected(self, agent_db: AsyncSession) -> None:
        result = await fr_module.create_finished_receipt_draft(
            {
                "product_name": "达托霉素",
                "product_batch_no": "B",
                "quantity": "1",
                "unit": "kg",
                "不存在字段XYZ": "值",
            },
            _ctx={"open_id": "ou_1"},
        )
        assert "error" in result
        assert "不支持的字段" in result["error"]

    async def test_success_creates_draft_and_card(
        self, agent_db: AsyncSession, captured_sends: list[dict[str, str]]
    ) -> None:
        result = await fr_module.create_finished_receipt_draft(
            {
                "product_name": "达托霉素",
                "product_batch_no": "DA2609001",
                "quantity": "100",
                "unit": "kg",
                "workshop": "提炼工程一部",
            },
            _ctx={"open_id": "ou_fr_create", "chat_id": "oc_fr_create"},
        )
        assert result["status"] == "pending_confirm"
        card = _card_of(captured_sends[-1])
        assert card["header"]["title"]["content"] == "🏭 成品入库登记"
        buttons = _confirm_buttons(card)
        assert buttons and buttons[0]["value"]["scene"] == FINISHED_RECEIPT_SCENE
        content = _card_content(card)
        assert "生产车间" in content  # 车间按收集字段名展示
        assert "待检" in content  # 质量状态静态行


# ═══════════════════════════════════════════════════════════════
# 提交
# ═══════════════════════════════════════════════════════════════


class TestSubmitFinishedReceipt:
    async def test_rejects_non_confirmed(self, db_session: AsyncSession) -> None:
        draft = _fr_draft_row({}, status="pending_confirm")
        with pytest.raises(df.DraftFlowError, match="仅 confirmed"):
            await submit_module.submit_finished_receipt(db_session, draft)

    async def test_full_submit_with_fake_adapter(
        self,
        fr_unit_env: dict[str, FieldMeta],
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        adapter = FakeAdapter()
        monkeypatch.setattr(submit_module, "get_adapter", lambda: adapter)
        draft = _fr_draft_row(
            {
                "product_name": "达托霉素",
                "product_batch_no": "DA2609001",
                "quantity": "100",
                "unit": "kg",
                "spec": "DA低规",
            }
        )
        db_session.add(draft)
        await db_session.flush()

        note = await submit_module.submit_finished_receipt(db_session, draft)
        assert draft.status == "submitted"
        assert draft.target_record_id == FakeAdapter.record_id
        assert adapter.created is not None
        assert adapter.created["质量状态"] == "待检"
        assert adapter.created["入库数量"] == 100
        assert "入库日期" in adapter.created
        # 读回核对一致 → 回执 note 成功口径
        assert "✅ 成品入库已登记" in note
        # 审计
        audits = (
            await db_session.execute(
                select(WarehouseAgentAudit).where(
                    WarehouseAgentAudit.tool_name == "submit_finished_receipt",
                    WarehouseAgentAudit.draft_id == draft.id,
                )
            )
        ).scalars().all()
        assert len(audits) == 1
        assert audits[0].result_status == "ok"

    async def test_mismatch_marks_audit(
        self,
        fr_unit_env: dict[str, FieldMeta],
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        adapter = FakeAdapter(read_override={"入库数量": 999})
        monkeypatch.setattr(submit_module, "get_adapter", lambda: adapter)
        draft = _fr_draft_row(
            {
                "product_name": "达托霉素",
                "product_batch_no": "B",
                "quantity": "1",
                "unit": "kg",
            }
        )
        db_session.add(draft)
        await db_session.flush()

        note = await submit_module.submit_finished_receipt(db_session, draft)
        assert draft.status == "submitted"  # mismatch 不算失败
        assert "⚠" in note and "不一致" in note
        audits = (
            await db_session.execute(
                select(WarehouseAgentAudit).where(
                    WarehouseAgentAudit.draft_id == draft.id
                )
            )
        ).scalars().all()
        assert audits[-1].error_code == "mismatch"


# ═══════════════════════════════════════════════════════════════
# 卡片分支
# ═══════════════════════════════════════════════════════════════


class TestCards:
    def test_confirm_card_branch(self) -> None:
        draft = _fr_draft_row(
            {
                "product_name": "达托霉素",
                "product_batch_no": "DA2609001",
                "quantity": "100",
                "unit": "kg",
            },
            status="aligned",
        )
        card = cards.render_receipt_confirm_card(draft)
        assert card["header"]["title"]["content"] == "🏭 成品入库登记"
        buttons = _confirm_buttons(card)
        assert buttons[0]["value"]["scene"] == FINISHED_RECEIPT_SCENE
        content = _card_content(card)
        assert "质量状态**：待检" in content

    def test_result_card_branch(self) -> None:
        draft = _fr_draft_row({})
        check = {
            "consistent": True,
            "mismatches": [],
            "written": {"产品名称": "达托霉素", "质量状态": "待检"},
            "record_id": "rec_x",
            "degraded": ["品规"],
        }
        card = cards.render_receipt_result_card(draft, check)
        assert card["header"]["title"]["content"] == "✅ 成品入库已登记"
        content = _card_content(card)
        assert "✅ 产品/批号/数量/单位 与 Base 读回一致" in content
        assert "品规需在 Base 人工补填" in content


# ═══════════════════════════════════════════════════════════════
# 分类路由与识别容错
# ═══════════════════════════════════════════════════════════════


class _BoomClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a: Any) -> None:
        return None

    async def chat_with_tools(self, *a: Any, **k: Any) -> Any:
        raise RuntimeError("gateway down")


class TestClassifyAndRecognize:
    async def test_classify_failure_falls_back_to_raw(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.modules.warehouse.agent.pipeline import recognizer

        def _client():
            return _BoomClient()

        monkeypatch.setattr(recognizer, "get_llm_client", lambda: _client())
        result = await recognizer.classify_document("not-a-real-image")
        assert result == DOC_TYPE_RAW

    async def test_finished_json_retry_then_llm_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """两次输出都非法 JSON → 抛 WarehouseLLMError（与原辅料同口径）。"""
        from app.modules.warehouse.agent.llm_client import WarehouseLLMError
        from app.modules.warehouse.agent.pipeline import recognizer

        class _BadClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a: Any) -> None:
                return None

            async def chat_with_tools(self, *a: Any, **k: Any) -> Any:
                class _Msg:
                    content = "不是 JSON"
                    usage = None
                    finish_reason = None

                return _Msg()

        def _client():
            return _BadClient()

        monkeypatch.setattr(recognizer, "get_llm_client", lambda: _client())
        with pytest.raises(WarehouseLLMError):
            await recognize_finished_receipt("fake-image")


# ═══════════════════════════════════════════════════════════════
# gateway 图片路由：成品分支全链（识别假件 → 草稿 → 确认 → FakeAdapter 提交）
# ═══════════════════════════════════════════════════════════════


def _im_image_event(*, chat_id: str, sender_open_id: str) -> dict[str, Any]:
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
            "message_type": "image",
            "content": json.dumps({"image_key": "img_v2_fake"}),
            "mentions": [],
        },
    }


class TestGatewayFinishedRoute:
    async def test_classified_finished_creates_draft_and_submits(
        self,
        agent_db: AsyncSession,
        captured_sends: list[dict[str, str]],
        fresh_redis: aioredis.Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def fake_download(message_id: str, file_key: str) -> bytes:
            return b"\x89PNG\r\n\x1a\n" + b"img" * 8

        async def fake_classify(image_b64: str, content_type: str = "image/jpeg") -> str:
            return "finished_receipt"

        async def fake_detect(image_b64: str, content_type: str = "image/jpeg") -> int:
            return 0

        async def fake_upload(content: bytes, name: str) -> str:
            return "file_token_fake"

        recognized = RecognizedFinishedReceipt(
            product_name=RecognizedField(value="达托霉素", confidence=0.95),
            product_batch_no=RecognizedField(value="DA2609001", confidence=0.9),
            quantity=RecognizedField(value="100", confidence=0.9),
            unit=RecognizedField(value="kg", confidence=0.95),
            workshop=RecognizedField(value="提炼工程一部", confidence=0.7),
        )

        async def fake_recognize_finished(
            image_b64: str, content_type: str = "image/jpeg"
        ) -> RecognizedFinishedReceipt:
            return recognized

        # 原图上传走 Base（识别链路降级不阻断）——桩掉避免真实上传
        monkeypatch.setattr(gateway.media, "download_im_image", fake_download)
        monkeypatch.setattr(gateway.media, "upload_image", fake_upload)
        monkeypatch.setattr(gateway, "classify_document", fake_classify)
        monkeypatch.setattr(gateway, "detect_rotation", fake_detect)
        monkeypatch.setattr(
            gateway, "recognize_finished_receipt", fake_recognize_finished
        )

        chat_id = f"oc_fr_{uuid.uuid4().hex[:8]}"
        open_id = f"ou_fr_{uuid.uuid4().hex[:6]}"
        await gateway.handle_im_message(
            _im_image_event(chat_id=chat_id, sender_open_id=open_id)
        )
        await _drain_gateway_tasks()

        # 占位 + 确认卡（🏭 成品入库登记，scene=finished_receipt）
        interactive = _interactive_cards(captured_sends)
        assert len(interactive) == 2
        confirm_card = interactive[-1]
        assert confirm_card["header"]["title"]["content"] == "🏭 成品入库登记"
        buttons = _confirm_buttons(confirm_card)
        assert buttons and buttons[0]["value"]["scene"] == FINISHED_RECEIPT_SCENE

        # 草稿 scene/status/recognized 落库；直接对齐（aligned 空）
        draft_id = buttons[0]["value"]["draft_id"]
        draft = await agent_db.get(WarehouseAgentDraft, uuid.UUID(draft_id))
        assert draft is not None and draft.scene == FINISHED_RECEIPT_SCENE
        assert draft.status == "pending_confirm"
        rec = draft.recognized if isinstance(draft.recognized, dict) else {}
        assert (rec.get("product_batch_no") or {}).get("value") == "DA2609001"
        assert draft.aligned == {}

        # 模拟点确认（确认置 confirmed → 后台 submit 走 FakeAdapter）
        adapter = FakeAdapter()
        monkeypatch.setattr(submit_module, "get_adapter", lambda: adapter)
        from app.modules.warehouse.agent import confirm

        outcome = await confirm.handle_action(
            agent_db,
            value={
                "scene": FINISHED_RECEIPT_SCENE,
                "draft_id": draft_id,
                "action": "confirm",
            },
            operator_open_id=open_id,
        )
        assert outcome.ok is True
        await _drain_gateway_tasks()

        assert adapter.created is not None
        assert adapter.created["质量状态"] == "待检"
        assert adapter.created["入库数量"] == 100
        assert adapter.created["备注"] == "入库车间：提炼工程一部"
        # 回执卡（后台 submit 完成后发送）
        titles = [
            c.get("header", {}).get("title", {}).get("content")
            for c in _interactive_cards(captured_sends)
        ]
        assert "✅ 成品入库已登记" in titles
