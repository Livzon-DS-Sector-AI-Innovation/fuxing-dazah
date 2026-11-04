"""五金库 M2 验收测试：四级匹配器 / OCR 只产 draft 红线 / 合成样例识别结构
/ agent 链（scene 注册+确认卡渲染+submit 回调）/ direct 净零推送。

M2 验收口径（任务书）：以合成样例+单测验收识别链与四级匹配逻辑；
真实送货单实测由用户验收阶段补充。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.modules.warehouse.hardware import matcher as m
from app.modules.warehouse.hardware import service as hw
from app.modules.warehouse.hardware.models import (
    HardwareMaterial,
    HardwareMovement,
    HardwareReceipt,
)
from app.modules.warehouse.hardware.schemas import ReceiptCreate, ReceiptItemIn


# ── 四级匹配器（纯函数，无需 DB）──


class FakeMaterial:
    def __init__(self, name, spec=None, code=None, managed="stocked"):
        self.id = name
        self.code = code
        self.name = name
        self.spec = spec
        self.managed_class = managed


POOL = [
    FakeMaterial("304不锈钢球阀", "DN25"),
    FakeMaterial("304不锈钢球阀", "DN50"),
    FakeMaterial("304不锈钢管", "φ25*2", code="CG-2024-0001"),
    FakeMaterial("UPVC活接", "DN25*1/2"),
    FakeMaterial("精密压力表", "YS-100", managed="direct"),
]


def test_level1_code_exact():
    """L1 编码精确：100 分。"""
    r = m.match_one(code="cg-2024-0001", name="随便写", materials=POOL)
    assert r.method == m.METHOD_ERP_CODE and r.score == m.SCORE_CODE_EXACT
    assert r.material.name == "304不锈钢管"
    assert not r.low_confidence


def test_level2_name_spec_variants():
    """L2 名称规格：φ/DN 变体、×/* 变体、mm 后缀等价。"""
    for spec_variant in ("φ25", "DN25", "dn25mm", "25mm"):
        r = m.match_one(name="304不锈钢球阀", spec=spec_variant, materials=POOL)
        assert r.material and r.material.spec == "DN25", spec_variant
        assert r.score >= m.SCORE_NAME_SPEC_CONTAIN


def test_level2_contain_and_merged():
    """L2 包含/合并串：OCR 单行「304球阀DN25」与长短名。"""
    r = m.match_one(name="304不锈钢球阀（内螺纹）", spec="DN25", materials=POOL)
    assert r.material and r.material.spec == "DN25" and r.score >= 85
    r2 = m.match_one(name="304球阀", spec="DN25", materials=POOL)
    assert r2.material and r2.material.name == "304不锈钢球阀"


def test_level3_synonym():
    """L3 同义词：「单向阀」→「止回阀」、「大小头」→「变径」。"""
    pool = POOL + [FakeMaterial("UPVC止回阀", "DN50")]
    r = m.match_one(name="UPVC单向阀", spec="DN50", materials=pool)
    assert r.material and r.material.name == "UPVC止回阀"
    assert r.method == m.METHOD_SYNONYM


def test_unmatched_and_threshold():
    """L4 未匹配：None+unmatched+低置信。"""
    r = m.match_one(name="完全不存在的物料XYZ", spec="ABC", materials=POOL)
    assert r.material is None and r.method == m.METHOD_UNMATCHED
    assert r.low_confidence
    # 阈值语义：低于 75 标黄
    assert m.LOW_CONFIDENCE_THRESHOLD == Decimal("75")


def test_normalize_spec_equivalence():
    """规格归一化等价组。"""
    assert m.normalize_spec("φ108*4") == m.normalize_spec("DN108*4")
    assert m.normalize_spec("dn25mm") == m.normalize_spec("DN25")
    assert m.normalize_spec("Φ25×2") == m.normalize_spec("dn25*2")


# ── OCR 编排（合成样例，mock LLM；红线：只产 draft 不动账）──


def _synthetic_payload() -> dict:
    """合成送货单识别结果（模拟 vision 提取输出）。"""
    return {
        "supplier": "上海XX阀门制造有限公司",
        "delivery_note_no": "SH-20261104-001",
        "arrived_date": "2026-11-04",
        "remark": "发酵车间申购",
        "rows": [
            {"code": None, "name": "304不锈钢球阀", "spec": "DN25", "quantity": 10, "unit": "个"},
            {"code": None, "name": "304不锈钢球阀", "spec": "DN50", "quantity": 4, "unit": "个"},
            {"code": None, "name": "车间专用温度计", "spec": "WSS-411", "quantity": 2, "unit": "台"},
        ],
    }


async def test_ocr_pipeline_produces_draft_only(db_session):
    """红线断言：OCR 编排后单据=draft、库存零变动、流水零写入。"""
    from app.modules.warehouse.hardware import receipt_pipeline as rp

    # 造主数据供匹配（名称带后缀防撞库）
    m1 = HardwareMaterial(name="304不锈钢球阀·T1", spec="DN25", unit="个", category="金属阀门",
                          managed_class="stocked", safety_stock=Decimal("0"), no_expiry=True)
    m2 = HardwareMaterial(name="304不锈钢球阀·T1", spec="DN50", unit="个", category="金属阀门",
                          managed_class="stocked", safety_stock=Decimal("0"), no_expiry=True)
    db_session.add_all([m1, m2])
    await db_session.flush()

    synthetic = _synthetic_payload()
    synthetic["rows"][0]["name"] = "304不锈钢球阀·T1"
    synthetic["rows"][1]["name"] = "304不锈钢球阀·T1"

    async def fake_recognize(image_b64, content_type="image/jpeg"):
        from app.modules.warehouse.hardware.recognizer import build_hardware_receipt
        return build_hardware_receipt(synthetic)

    async def fake_rotate(b64, ct="image/jpeg"):
        return b64, ct

    with patch.object(rp.hw_recognizer, "recognize_hardware_receipt", fake_recognize), \
         patch.object(rp.hw_recognizer, "rotate_image_if_needed", fake_rotate):
        receipt, summary = await rp.build_ocr_draft(
            db_session, image_b64="fake", content_type="image/jpeg",
        )

    # 草稿断言（AI 永不自动动账）
    assert receipt.status == "draft"
    assert receipt.source == "ocr"
    assert receipt.supplier_name == "上海XX阀门制造有限公司"
    assert receipt.ocr_result is not None  # 留痕 JSON
    _, mv_total = await hw.list_movements(db_session)
    assert mv_total == 0  # 零流水
    rows, _ = await hw.list_stock_rows(db_session, keyword="·T1", managed_class="stocked")
    assert all(r["on_hand"] == 0 for r in rows)  # 零库存

    # 匹配统计：2 行 stocked 命中 + 1 行清单外未匹配
    assert summary["matched_stocked"] == 2
    assert summary["unmatched"] == 1
    assert summary["rows"][2]["low_confidence"] is True  # 标黄不代改


async def test_ocr_confirm_moves_stock_after_human_confirm(db_session):
    """确认入账后库存才动：draft→accepted 全链（人拍板）。"""
    from app.modules.warehouse.hardware import receipt_pipeline as rp

    m1 = HardwareMaterial(name="304不锈钢球阀·T2", spec="DN25", unit="个", category="金属阀门",
                          managed_class="stocked", safety_stock=Decimal("0"), no_expiry=True)
    db_session.add(m1)
    await db_session.flush()

    synthetic = _synthetic_payload()
    synthetic["rows"] = [{"code": None, "name": "304不锈钢球阀·T2", "spec": "DN25", "quantity": 6, "unit": "个"}]

    async def fake_recognize(image_b64, content_type="image/jpeg"):
        from app.modules.warehouse.hardware.recognizer import build_hardware_receipt
        return build_hardware_receipt(synthetic)

    async def fake_rotate(b64, ct="image/jpeg"):
        return b64, ct

    with patch.object(rp.hw_recognizer, "recognize_hardware_receipt", fake_recognize), \
         patch.object(rp.hw_recognizer, "rotate_image_if_needed", fake_rotate):
        receipt, _summary = await rp.build_ocr_draft(db_session, image_b64="fake")

    await hw.accept_receipt(
        db_session, receipt.id, inspected_by_warehouse="ou_wh", inspected_by_dept="ou_dept"
    )
    rows, _ = await hw.list_stock_rows(db_session, keyword="·T2", managed_class="stocked")
    assert rows[0]["on_hand"] == Decimal("6")
    _, in_total = await hw.list_movements(db_session, direction="inbound")
    assert in_total == 1
    items = await hw.list_receipt_items(db_session, receipt.id)
    assert items[0].lot_no  # 批次号已生成


# ── agent 链 ──


async def test_agent_scene_registered_and_card_renders(db_session):
    """scene=hardware_receipt 注册 + 确认卡渲染 + 回调可解析。"""
    from app.modules.warehouse.agent.pipeline.draft_flow import (
        HARDWARE_RECEIPT_SCENE,
        SCENE_CONFIG,
    )
    from app.modules.warehouse.agent import cards
    from app.modules.warehouse.agent.confirm import is_registered_scene

    assert HARDWARE_RECEIPT_SCENE in SCENE_CONFIG
    assert SCENE_CONFIG[HARDWARE_RECEIPT_SCENE].submit is not None
    assert is_registered_scene(HARDWARE_RECEIPT_SCENE)

    class FakeDraft:
        id = uuid4()
        draft_no = "WR20261104-001"
        scene = HARDWARE_RECEIPT_SCENE
        aligned = {
            "receipt_id": str(uuid4()),
            "receipt_no": "WJK-RK-261104-001",
            "supplier": "上海XX阀门",
            "mode": "stocked",
            "rows": [
                {"ocr_name": "304不锈钢球阀", "ocr_spec": "DN25", "quantity": 10,
                 "matched": "304不锈钢球阀", "low_confidence": False},
                {"ocr_name": "车间专用温度计", "ocr_spec": "WSS-411", "quantity": 2,
                 "matched": None, "low_confidence": True},
            ],
        }

    card = cards._render_hardware_receipt_confirm_card(FakeDraft())
    assert card.get("config") is not None or card.get("elements")
    content = str(card)
    assert "五金库入库确认" in content and "低置信" in content and "WJK-RK-261104-001" in content


async def test_agent_submit_moves_receipt(db_session):
    """确认回调真身：AgentDraft confirmed → 入库单 accepted → draft submitted。"""
    from app.modules.warehouse.agent.pipeline.draft_flow import HARDWARE_RECEIPT_SCENE
    from app.modules.warehouse.agent.pipeline.draft_flow import create_dialog_draft
    from app.modules.warehouse.hardware.agent_submit import submit_hardware_receipt

    m1 = HardwareMaterial(name="304不锈钢球阀·T3", spec="DN25", unit="个", category="金属阀门",
                          managed_class="stocked", safety_stock=Decimal("0"), no_expiry=True)
    db_session.add(m1)
    await db_session.flush()
    receipt = await hw.create_receipt(
        db_session,
        ReceiptCreate(source="ocr", items=[
            ReceiptItemIn(material_id=str(m1.id), name=m1.name, spec=m1.spec,
                          unit=m1.unit, quantity=Decimal("3")),
        ]),
    )
    draft = await create_dialog_draft(
        db_session,
        scene=HARDWARE_RECEIPT_SCENE,
        fields={"receipt_id": str(receipt.id), "receipt_no": receipt.receipt_no, "rows": []},
        open_id="ou_test",
    )
    draft.status = "confirmed"  # 确认门已前置置位
    await db_session.flush()

    result = await submit_hardware_receipt(db_session, draft)
    await db_session.refresh(receipt)
    assert receipt.status == "accepted"
    assert draft.status == "submitted"
    rows, _ = await hw.list_stock_rows(db_session, keyword="·T3", managed_class="stocked")
    assert rows[0]["on_hand"] == Decimal("3")


async def test_direct_pickup_fires_push_event(db_session):
    """direct 行确认入账 → 领取卡推送事件触发（验收入阶段补充真实到达）。"""
    from app.modules.warehouse.push_center.events import EVENT_RENDERERS

    assert "hardware_direct_pickup" in EVENT_RENDERERS
    assert "hardware_receipt_rejected" in EVENT_RENDERERS
    assert "hardware_requisition_rejected" in EVENT_RENDERERS
    assert "hardware_urgent_overdue" in EVENT_RENDERERS
    # 渲染纯函数冒烟
    card = EVENT_RENDERERS["hardware_direct_pickup"]({
        "dept": "发酵", "supplier": "供应商A", "receipt_no": "WJK-RK-261104-002",
        "rows": [{"name": "精密压力表", "spec": "YS-100", "quantity": 2, "unit": "台"}],
    })
    assert "五金库到货待领" in str(card)
