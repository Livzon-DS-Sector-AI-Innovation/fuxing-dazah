"""S2 ticket 04 验收：Submit 写入 + 附件上传 + 读回核对（识别入库最后一公里）。

单测（真库 whdev + 事务回滚隔离；Base/附件/发送全部注入假件不触网）：
- build_receipt_fields：物料名称降级（fields 无该键 + degraded 标注）、
  单选大小写归一（kg→Kg）与选项集不匹配跳过、数量数字化、生产日期转
  毫秒时间戳、到货情况固定「到货物料」；
- render_receipt_result_card：成功态「✅ 入库已登记」/ mismatch 态 ⚠ 标题
  + 写入值 vs 读回值对照行 + 降级提示；
- submit_receipt（confirm.handle_action 触发真回调，fake adapter/media）：
  happy path（附件列写入 + submitted + record_id 回填 + audit + 回执含
  「人工补选」）、mismatch 注入（读回数量不同 → 回执 ⚠ + audit
  error_code=mismatch）、状态前置（非 confirmed 拒绝）+ 终态幂等。

live 主接缝（真图 + 真 LLM + 真 Base，数据集缺失自动 skip）：
- 附件上传：dataset 图 → upload_image → file_token 非空 → 临时记录写入
  附件列 → get_record 读回含该 token → delete_record 清理；
- submit 全流程：真图 → recognize→align→create_draft→mark_aligned→
  send_confirm_card→confirm.handle_action（触发真回调）→ Base 新记录
  （record_id 有批号）→ 读回核对一致 → draft=submitted → 回执卡片
  （dry-run 捕获含「已登记」）→ 测试后按 record_id 删除 Base 记录。

运行：cd "E:\\dazah(仓储)\\backend" &&
      DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/dazah_whdev"
      uv run pytest tests/modules/warehouse/test_live_submit.py -v
"""

from __future__ import annotations

import base64
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent import confirm
from app.modules.warehouse.agent.cards import (
    RECEIPT_DEGRADE_MATERIAL_HINT,
    RECEIPT_RESULT_CARD_TITLE_MISMATCH,
    RECEIPT_RESULT_CARD_TITLE_OK,
    render_receipt_result_card,
)
from app.modules.warehouse.agent.pipeline import aligner as aligner_module
from app.modules.warehouse.agent.pipeline import submit as submit_module
from app.modules.warehouse.agent.pipeline.draft_flow import (
    DraftFlowError,
    create_receipt_draft,
    mark_aligned,
    send_confirm_card,
)
from app.modules.warehouse.agent.pipeline.recognizer import (
    build_receipt,
    recognize_receipt,
)
from app.modules.warehouse.agent.pipeline.submit import (
    ARRIVAL_STATUS_VALUE,
    ATTACHMENT_FIELD,
    RECEIPT_TABLE,
    SUBMIT_MATERIAL_NAME_ENABLED,
    build_receipt_fields,
    submit_receipt,
)
from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter
from app.modules.warehouse.bitable_schema import TABLES
from app.modules.warehouse.feishu import media, notification
from app.modules.warehouse.models import WarehouseAgentAudit, WarehouseAgentDraft

# 仓库根 = tests/modules/warehouse/test_x.py 往上 4 级
REPO_ROOT = Path(__file__).resolve().parents[4]
IMAGES_DIR = REPO_ROOT / ".scratch" / "s2-recognition" / "dataset" / "images"

RECEIPT_SCENE = "receipt"


# ── fixtures：发送捕获 ──


@pytest.fixture
def captured_sends(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    """捕获 notification 全部发送 payload（构建路径真实执行，不触网）。"""
    sent: list[dict[str, str]] = []

    async def fake_send(payload: dict[str, str]) -> str | None:
        sent.append(payload)
        return "om_fake_id"

    monkeypatch.setattr(notification, "_send_create", fake_send)
    return sent


# ── 测试数据工厂 ──


def _recognized_payload() -> dict[str, Any]:
    """识别 JSON dict（model_dump 同构；单选值均取 Base 选项集内合法值）。"""
    return {
        "material_name": {"value": "硫酸铵", "confidence": 0.95},
        "vendor_batch_no": {"value": "2511", "confidence": 0.85},
        "quantity": {"value": "32000", "confidence": 0.9},
        "unit": {"value": "kg", "confidence": 0.92},  # 小写 → 归一到选项 Kg
        "supplier": {"value": "福州优傲材料科技有限公司", "confidence": 0.85},
        "manufacturer": {"value": "福建天辰耀隆新材料有限公司", "confidence": 0.8},
        "plate_no": {"value": "闽A12345", "confidence": 0.8},
        "contract_no": {"value": "PO2501150179", "confidence": 0.88},
        "package_spec": {"value": "25Kg/包", "confidence": 0.75},
        "produced_at": {"value": "2026-05-01", "confidence": 0.7},
    }


def _aligned_receipt(recognized: Any, *, match: str = "exact") -> Any:
    """构造 AlignedReceipt（假主数据，单测不依赖真 Base）。"""
    return aligner_module.AlignedReceipt(
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


async def _seed_pending_draft(
    db: AsyncSession, *, open_id: str, quantity: Any = "32000"
) -> WarehouseAgentDraft:
    """种子：识别落库 + 对齐落库 + 确认卡片发送（status=pending_confirm）。"""
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
    await send_confirm_card(db, draft, chat_id="oc_seed")
    return draft


async def _submit_via_confirm(
    db: AsyncSession, draft: WarehouseAgentDraft
) -> confirm.ConfirmOutcome:
    """确认门点击确认（走真回调 submit_receipt）。"""
    return await confirm.handle_action(
        db,
        value={"scene": RECEIPT_SCENE, "action": "confirm", "draft_id": str(draft.id)},
        operator_open_id=draft.created_by_open_id or "",
    )


async def _submit_audits(db: AsyncSession, draft_id: Any) -> list[WarehouseAgentAudit]:
    rows = await db.execute(
        select(WarehouseAgentAudit).where(
            WarehouseAgentAudit.tool_name == "submit_receipt",
            WarehouseAgentAudit.draft_id == draft_id,
        )
    )
    return list(rows.scalars().all())


def _interactive_cards(sends: list[dict[str, str]]) -> list[dict[str, Any]]:
    """捕获 payload → 交互卡片 dict 列表。"""
    cards: list[dict[str, Any]] = []
    for payload in sends:
        if payload.get("msg_type") == "interactive":
            cards.append(json.loads(payload["content"]))
    return cards


def _card_content(card: dict[str, Any]) -> str:
    return "\n".join(
        element.get("content") or ""
        for element in card.get("elements", [])
        if isinstance(element, dict)
    )


class FakeAdapter:
    """submit_receipt 依赖的最小 adapter 面：create 自回显 + get 读回。

    read_override 覆盖指定字段的读回值（mismatch 注入口）；其余字段读回
    即写入值（规范化后一致）。
    """

    record_id = "rec_fake_001"

    def __init__(self, read_override: dict[str, Any] | None = None) -> None:
        self.created: dict[str, Any] | None = None
        self.read_override = read_override or {}

    async def create_record(
        self, table_key: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        self.created = dict(fields)
        return {"record_id": self.record_id, "fields": {}}

    async def get_record(self, table_key: str, record_id: str) -> dict[str, Any]:
        fields = dict(self.created or {})
        fields.update(self.read_override)
        return {"record_id": record_id, "fields": fields}


@pytest.fixture
def fake_backend(monkeypatch: pytest.MonkeyPatch):
    """注入 fake adapter + fake media（download/upload 不触网）。

    返回 holder：``fake_backend["install"](read_override)`` 装指定读回
    覆盖的 FakeAdapter（mismatch 注入口），``fake_backend["adapter"]``
    取该实例断言 created fields。
    """
    holder: dict[str, Any] = {}

    def _install(read_override: dict[str, Any] | None = None) -> FakeAdapter:
        fake = FakeAdapter(read_override)
        holder["adapter"] = fake
        monkeypatch.setattr(submit_module, "get_adapter", lambda: fake)
        return fake

    async def fake_download(file_token: str, **kwargs: Any) -> bytes:
        return b"fake-image-bytes"

    async def fake_upload(file_bytes: bytes, filename: str) -> str:
        return "upl_fake_token"

    monkeypatch.setattr(media, "download_attachment", fake_download)
    monkeypatch.setattr(media, "upload_image", fake_upload)
    holder["install"] = _install
    return holder


# ── 1. build_receipt_fields：映射 / 降级 / 单选适配 ──


def test_build_receipt_fields_degrades_material_name() -> None:
    """spec 决策 6：物料名称降级——fields 无「物料名称」键 + degraded 标注。"""
    payload = _recognized_payload()
    draft = WarehouseAgentDraft(
        draft_no="WR20990101-001",
        scene=RECEIPT_SCENE,
        status="confirmed",
        recognized=payload,
        aligned={"material_name": "硫酸铵", "match_confidence": "exact"},
    )
    fields, degraded = build_receipt_fields(draft)

    assert "物料名称" not in fields
    assert "物料名称" in degraded
    assert SUBMIT_MATERIAL_NAME_ENABLED is False  # 降级开关：治理后置 True
    assert fields["到货情况"] == ARRIVAL_STATUS_VALUE == "到货物料"


def test_build_receipt_fields_mapping_and_select_adaptation() -> None:
    """字段映射 + 单选大小写归一（kg→Kg）+ 数量数字化 + 生产日期毫秒。"""
    draft = WarehouseAgentDraft(
        draft_no="WR20990101-002",
        scene=RECEIPT_SCENE,
        status="confirmed",
        recognized=_recognized_payload(),
        aligned={"material_name": "硫酸铵", "match_confidence": "exact"},
    )
    fields, degraded = build_receipt_fields(draft)

    assert degraded == ["物料名称"]  # 其余字段均合法写入
    assert fields["厂家批号"] == "2511"
    assert fields["入库数量"] == 32000 and isinstance(fields["入库数量"], int)
    assert fields["单位"] == "Kg"  # 识别 kg → 选项集 Kg（大小写归一）
    assert fields["供应商"] == "福州优傲材料科技有限公司"
    assert fields["生产商"] == "福建天辰耀隆新材料有限公司"
    assert fields["车牌"] == "闽A12345"
    assert fields["合同编号或订单号"] == "PO2501150179"
    assert fields["包装规格"] == "25Kg/包"
    # 生产日期 → 毫秒时间戳（飞书 datetime 字段契约）
    from datetime import UTC, datetime

    expected_ms = int(datetime(2026, 5, 1, tzinfo=UTC).timestamp() * 1000)
    assert fields["生产日期"] == expected_ms
    # 写契约本地校验通过（S0：单选均为选项集内纯字符串）
    from app.modules.warehouse.bitable_schema import validate_write_fields

    validate_write_fields(RECEIPT_TABLE, fields)


def test_build_receipt_fields_select_mismatch_skipped_and_aligned_override() -> None:
    """单选值不在选项集 → 跳过 + degraded；aligned 覆盖优先于识别值。"""
    payload = _recognized_payload()
    payload["supplier"] = {"value": "不存在的供应商有限公司", "confidence": 0.6}
    draft = WarehouseAgentDraft(
        draft_no="WR20990101-003",
        scene=RECEIPT_SCENE,
        status="confirmed",
        recognized=payload,
        aligned={
            "material_name": "硫酸铵",
            "quantity": 200,  # 对话修改后的值（update_draft 形态：数字）
            "match_confidence": "exact",
        },
    )
    fields, degraded = build_receipt_fields(draft)

    assert "供应商" not in fields
    assert "供应商" in degraded
    assert fields["入库数量"] == 200  # aligned 覆盖优先


def test_build_receipt_fields_bad_quantity_and_date_skipped() -> None:
    """数量非数字 / 日期不可解析 → 跳过 + degraded（不抛错）。"""
    payload = _recognized_payload()
    payload["quantity"] = {"value": "约三万二", "confidence": 0.3}
    payload["produced_at"] = {"value": "五月初", "confidence": 0.3}
    draft = WarehouseAgentDraft(
        draft_no="WR20990101-004",
        scene=RECEIPT_SCENE,
        status="confirmed",
        recognized=payload,
        aligned={"material_name": "硫酸铵", "match_confidence": "exact"},
    )
    fields, degraded = build_receipt_fields(draft)

    assert "入库数量" not in fields and "入库数量" in degraded
    assert "生产日期" not in fields and "生产日期" in degraded


# ── 2. 回执卡片渲染 ──


def _check_result(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "consistent": True,
        "mismatches": [],
        "written": {"入库数量": 32000, "厂家批号": "2511", "单位": "Kg"},
        "record_id": "recABC123",
        "degraded": ["物料名称"],
    }
    base.update(overrides)
    return base


def test_render_receipt_result_card_ok() -> None:
    """成功态：✅ 标题（green）+ 草稿号/记录 id + 写入摘要 + 一致 + 降级提示。"""
    draft = WarehouseAgentDraft(draft_no="WR20990101-010", scene=RECEIPT_SCENE)
    card = render_receipt_result_card(draft, _check_result())

    assert card["header"]["title"]["content"] == RECEIPT_RESULT_CARD_TITLE_OK
    assert card["header"]["template"] == "green"
    content = _card_content(card)
    assert "**草稿**：WR20990101-010" in content
    assert "**记录 ID**：recABC123" in content  # 无 target 坐标 → 无链接，退化为 ID 行
    assert "1. 入库数量：32000" in content
    assert "✅ 数量/批号/单位/供应商 与 Base 读回一致" in content
    assert RECEIPT_DEGRADE_MATERIAL_HINT in content


def test_render_receipt_result_card_mismatch() -> None:
    """mismatch 态：⚠ 标题（red）+ 写入值 vs 读回值对照行。"""
    draft = WarehouseAgentDraft(draft_no="WR20990101-011", scene=RECEIPT_SCENE)
    card = render_receipt_result_card(
        draft,
        _check_result(
            consistent=False,
            mismatches=[
                {"field": "入库数量", "written": "32000", "read_back": "200"}
            ],
        ),
    )

    assert (
        card["header"]["title"]["content"] == RECEIPT_RESULT_CARD_TITLE_MISMATCH
    )
    assert card["header"]["template"] == "red"
    content = _card_content(card)
    assert "⚠ 入库数量：写入 32000 ≠ 读回 200" in content
    assert "与 Base 读回一致" not in content


def test_render_receipt_result_card_defensive() -> None:
    """防御：check_result 畸形（非 dict/缺键）不抛错，降级渲染。"""
    draft = WarehouseAgentDraft(draft_no="WR20990101-012", scene=RECEIPT_SCENE)
    card = render_receipt_result_card(draft, {})  # type: ignore[arg-type]
    content = _card_content(card)
    assert "**草稿**：WR20990101-012" in content
    assert card["header"]["title"]["content"] == RECEIPT_RESULT_CARD_TITLE_MISMATCH


# ── 3. submit_receipt（confirm.handle_action 触发真回调，fake 后端）──


async def test_submit_receipt_happy_path_with_degradation(
    db_session: AsyncSession, captured_sends: list[dict[str, str]], fake_backend: Any
) -> None:
    """全链 happy path：附件写入 + submitted + 回填 + audit + 回执含降级提示。"""
    fake_backend["install"](read_override=None)
    draft = await _seed_pending_draft(db_session, open_id="ou_submit_ok")

    outcome = await _submit_via_confirm(db_session, draft)

    assert outcome.ok is True
    assert outcome.status == "confirmed"
    assert "✅ 入库已登记" in outcome.message
    assert draft.status == "submitted"
    assert draft.target_record_id == "rec_fake_001"
    assert draft.target_table == TABLES[RECEIPT_TABLE].table_id

    # 写入 fields：物料名称降级（无该键）+ 到货情况固定值 + 附件列 file_token
    fields = fake_backend["adapter"].created
    assert fields is not None
    assert "物料名称" not in fields
    assert fields["到货情况"] == "到货物料"
    assert fields[ATTACHMENT_FIELD] == [{"file_token": "upl_fake_token"}]
    assert fields["厂家批号"] == "2511"

    # audit：tool_name=submit_receipt，一致无 error_code，fields 不含物料名称
    audits = await _submit_audits(db_session, draft.id)
    assert len(audits) == 1
    assert audits[0].result_status == "ok"
    assert audits[0].error_code is None
    assert "物料名称" not in audits[0].args_summary["fields"]
    assert "物料名称" in audits[0].args_summary["degraded"]

    # 回执卡片（dry-run 捕获，发发起人私聊）：✅ 标题 + 人工补选提示
    cards = _interactive_cards(captured_sends)
    assert cards, "回执卡片未被捕获"
    assert cards[-1]["header"]["title"]["content"] == RECEIPT_RESULT_CARD_TITLE_OK
    assert "人工补选" in _card_content(cards[-1])

    # 终态幂等：submitted 后再次提交拒绝
    with pytest.raises(DraftFlowError):
        await submit_receipt(db_session, draft)


async def test_submit_receipt_mismatch_injected(
    db_session: AsyncSession, captured_sends: list[dict[str, str]], fake_backend: Any
) -> None:
    """mismatch 注入：读回数量不同 → 回执 ⚠ + audit error_code=mismatch。"""
    fake_backend["install"](read_override={"入库数量": 200.0})
    draft = await _seed_pending_draft(db_session, open_id="ou_submit_bad")

    outcome = await _submit_via_confirm(db_session, draft)

    # mismatch 不算执行失败：draft 仍 submitted（Base 已有记录），回执/审计标注
    assert outcome.ok is True
    assert "⚠" in outcome.message and "不一致" in outcome.message
    assert draft.status == "submitted"
    assert draft.target_record_id == "rec_fake_001"

    audits = await _submit_audits(db_session, draft.id)
    assert len(audits) == 1
    assert audits[0].error_code == "mismatch"
    assert audits[0].result_status == "ok"

    cards = _interactive_cards(captured_sends)
    assert cards[-1]["header"]["title"]["content"] == RECEIPT_RESULT_CARD_TITLE_MISMATCH
    assert "⚠ 入库数量：写入 32000 ≠ 读回 200" in _card_content(cards[-1])


async def test_submit_receipt_requires_confirmed(db_session: AsyncSession) -> None:
    """状态前置：非 confirmed（aligned）直接提交 → DraftFlowError。"""
    payload = _recognized_payload()
    recognized = build_receipt(payload)
    draft = await create_receipt_draft(
        db_session, recognized=recognized, open_id="ou_submit_guard"
    )
    await mark_aligned(db_session, draft, _aligned_receipt(recognized))

    with pytest.raises(DraftFlowError):
        await submit_receipt(db_session, draft)
    assert draft.status == "aligned"  # 未被改动


# ── 4. live：附件上传 → 写入附件列 → 读回 → 清理 ──


def _first_attachment_token(fields: dict[str, Any]) -> str | None:
    value = fields.get(ATTACHMENT_FIELD)
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and item.get("file_token"):
                return str(item["file_token"])
    return None


@pytest.mark.skipif(
    not IMAGES_DIR.exists() or not any(IMAGES_DIR.glob("*.jpg")),
    reason="识别数据集缺失（scripts/build_recognition_dataset.py 先产出）",
)
async def test_live_attachment_upload_write_read_delete(db_session: AsyncSession) -> None:
    """live 附件上传：图 → file_token → 临时记录写附件列 → 读回含 token → 删除。"""
    image_path = sorted(IMAGES_DIR.glob("*.jpg"))[0]
    file_token = await media.upload_image(
        image_path.read_bytes(), f"pytest_{uuid.uuid4().hex[:8]}.jpg"
    )
    assert file_token, "upload_image 未返回 file_token"

    adapter = WarehouseBitableAdapter()
    created = await adapter.create_record(
        RECEIPT_TABLE,
        {"备注": f"pytest-attach-{uuid.uuid4().hex[:8]}",
         ATTACHMENT_FIELD: [{"file_token": file_token}]},
    )
    record_id = created["record_id"]
    assert record_id
    try:
        record = await adapter.get_record(RECEIPT_TABLE, record_id)
        read_back = _first_attachment_token(record["fields"])
        assert read_back == file_token  # 附件列读回含该 token
        print(f"\n[live 附件上传] file_token={file_token[:24]}… record_id={record_id}")
    finally:
        await adapter.delete_record(RECEIPT_TABLE, record_id)  # 测试清理


# ── 5. live：submit 全流程（真 LLM + 真 Base）──


@pytest.mark.skipif(
    not IMAGES_DIR.exists() or not any(IMAGES_DIR.glob("*.jpg")),
    reason="识别数据集缺失（scripts/build_recognition_dataset.py 先产出）",
)
async def test_live_submit_full_flow(
    db_session: AsyncSession, captured_sends: list[dict[str, str]]
) -> None:
    """真图全链：recognize→align→draft→confirm→写 Base→读回核对→submitted→清理。"""
    adapter = WarehouseBitableAdapter()

    # 原图 file token：从 Base 真实记录取（下载需 bitablePerm 上下文，票01 契约）
    page = await adapter.search_records_page(RECEIPT_TABLE, limit=500)
    source_token = None
    for record in page["records"]:
        token = _first_attachment_token(record["fields"])
        if token:
            source_token = token
            break
    assert source_token, "Base 中未找到附件非空的记录"

    # 真 LLM 识别 + 真主数据对齐（选批号/数量/单位识别完整的样本图，
    # 保证「Base 记录有批号」验收断言；样本缺失回退首张）
    preferred = IMAGES_DIR / "rec0aItKXJ.jpg"
    image_path = preferred if preferred.exists() else sorted(IMAGES_DIR.glob("*.jpg"))[0]
    image_b64 = base64.b64encode(image_path.read_bytes()).decode()
    recognized = await recognize_receipt(image_b64)
    assert recognized.material_name.value
    aligned = await aligner_module.align_receipt(recognized)

    # 草稿流转（真回调经 confirm.handle_action 触发）
    draft = await create_receipt_draft(
        db_session,
        recognized=recognized,
        image_file_token=source_token,
        open_id="ou_live_submit",
        chat_id="oc_live_submit",
    )
    await mark_aligned(db_session, draft, aligned)
    await send_confirm_card(db_session, draft, chat_id="oc_live_submit")
    assert draft.status == "pending_confirm"

    outcome = await _submit_via_confirm(db_session, draft)
    print(
        f"\n[live submit] 图={image_path.name} 物料={recognized.material_name.value} "
        f"match={aligned.match_confidence} outcome={outcome.message}"
    )
    assert outcome.ok is True, f"submit 失败: {outcome.message}"
    assert draft.status == "submitted"
    record_id = draft.target_record_id
    assert record_id and record_id.startswith("rec")

    try:
        # Base 新记录：读回含批号（识别必提字段落库）
        record = await adapter.get_record(RECEIPT_TABLE, record_id)
        assert record["fields"].get("厂家批号"), "Base 记录缺厂家批号"
        assert record["fields"].get("到货情况") is not None

        # 读回核对一致（outcome 无 ⚠ + audit 无 error_code）
        assert "不一致" not in outcome.message

        # 写入 fields 不含物料名称（降级）+ audit 留痕
        audits = await _submit_audits(db_session, draft.id)
        assert len(audits) == 1
        assert audits[0].error_code is None
        assert "物料名称" not in audits[0].args_summary["fields"]
        assert "物料名称" in audits[0].args_summary["degraded"]
        print(
            f"[live submit] record_id={record_id} fields={audits[0].args_summary['fields']}"
        )
    finally:
        await adapter.delete_record(RECEIPT_TABLE, record_id)  # 测试清理

    # 回执卡片（dry-run 捕获）：✅ 已登记（标题）+ 降级提示 + 记录 id
    cards = _interactive_cards(captured_sends)
    assert cards, "回执卡片未被捕获"
    assert cards[-1]["header"]["title"]["content"] == RECEIPT_RESULT_CARD_TITLE_OK
    assert "已登记" in outcome.message  # 确认卡更新文案
    content = _card_content(cards[-1])
    assert "人工补选" in content
    assert record_id in content
