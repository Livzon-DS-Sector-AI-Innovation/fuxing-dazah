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
    # 零流水（按本测试物资圈定——活库有真实流水，全表绝对计数会假红）
    _, mv_t1 = await hw.list_movements(db_session, keyword="·T1")
    assert mv_t1 == 0
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
    # 按本测试物资圈定（活库有真实 inbound 流水，绝对计数会假红）
    _, in_total = await hw.list_movements(db_session, direction="inbound", keyword="·T2")
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
    # （hardware_urgent_overdue 2026-11-20 随补办链退役）
    # 渲染纯函数冒烟
    card = EVENT_RENDERERS["hardware_direct_pickup"]({
        "dept": "发酵", "supplier": "供应商A", "receipt_no": "WJK-RK-261104-002",
        "rows": [{"name": "精密压力表", "spec": "YS-100", "quantity": 2, "unit": "台"}],
    })
    assert "五金库到货待领" in str(card)


# ── 入库方式2：截图解析自动填单（纯解析不落库 + 留痕透传）──


async def test_parse_receipt_image_creates_nothing(db_session):
    """parse_receipt_image 红线：纯解析零写库（无草稿/无流水/无库存）。"""
    from app.modules.warehouse.hardware import receipt_pipeline as rp

    m1 = HardwareMaterial(name="304不锈钢球阀·P1", spec="DN25", unit="个", category="金属阀门",
                          managed_class="stocked", safety_stock=Decimal("0"), no_expiry=True)
    db_session.add(m1)
    await db_session.flush()

    synthetic = _synthetic_payload()
    synthetic["rows"] = [
        {"code": None, "name": "304不锈钢球阀·P1", "spec": "DN25", "quantity": 10, "unit": "个"},
        {"code": None, "name": "车间专用温度计·P1", "spec": "WSS-411", "quantity": 2, "unit": "台"},
    ]

    async def fake_recognize(image_b64, content_type="image/jpeg"):
        from app.modules.warehouse.hardware.recognizer import build_hardware_receipt
        return build_hardware_receipt(synthetic)

    async def fake_rotate(b64, ct="image/jpeg"):
        return b64, ct

    # 零写库红线（差分口径——dev 库有历史真实入库单，断言本调用零新增）
    before = len((await db_session.execute(select(HardwareReceipt.id))).scalars().all())
    with patch.object(rp.hw_recognizer, "recognize_hardware_receipt", fake_recognize), \
         patch.object(rp.hw_recognizer, "rotate_image_if_needed", fake_rotate):
        parsed = await rp.parse_receipt_image(db_session, image_b64="fake")
    after = len((await db_session.execute(select(HardwareReceipt.id))).scalars().all())
    assert after == before  # 解析不产生任何草稿

    # 解析契约：单头 + 逐行匹配标记 + mode 预判
    assert parsed.supplier == "上海XX阀门制造有限公司"
    assert parsed.delivery_note_no == "SH-20261104-001"
    assert parsed.mode == "stocked"  # 有 stocked 命中行
    assert len(parsed.items) == 2
    assert parsed.items[0].material_id == str(m1.id)
    assert parsed.matched_names[0] == "304不锈钢球阀·P1"
    assert parsed.matched_names[1] is None  # 清单外未匹配
    assert parsed.low_confidences[1] is True  # 标黄不代改
    assert parsed.matched_stocked == 1 and parsed.unmatched == 1
    # 留痕 JSON 与直落草稿口径一致（rows 原样 + match_summary）
    trace = parsed.ocr_result()
    assert trace["supplier"] == synthetic["supplier"]
    assert len(trace["rows"]) == 2 and len(trace["match_summary"]) == 2


async def test_manual_create_with_ocr_result_passthrough(db_session):
    """方式2提交：source=ocr + ocr_result 回传 → 草稿留痕落库（纯手动=None）。"""
    m1 = HardwareMaterial(name="UPVC球阀·P2", spec="DN25", unit="个", category="金属阀门",
                          managed_class="stocked", safety_stock=Decimal("0"), no_expiry=True)
    db_session.add(m1)
    await db_session.flush()

    trace = {"supplier": "测试供应商", "rows": [{"name": "UPVC球阀·P2", "quantity": 5}],
             "match_summary": [{"matched": "UPVC球阀·P2", "score": 92.0}]}
    payload = ReceiptCreate(
        source="ocr", mode="stocked",
        supplier_name="测试供应商",
        ocr_result=trace,
        items=[ReceiptItemIn(material_id=str(m1.id), name="UPVC球阀·P2",
                             quantity=Decimal("5"), match_confidence="name_spec_exact")],
    )
    receipt = await hw.create_receipt(db_session, payload)
    assert receipt.status == "draft" and receipt.source == "ocr"
    assert receipt.ocr_result == trace  # 透传落库

    manual = ReceiptCreate(
        source="manual", mode="stocked",
        items=[ReceiptItemIn(material_id=str(m1.id), name="UPVC球阀·P2", quantity=Decimal("1"))],
    )
    receipt2 = await hw.create_receipt(db_session, manual)
    assert receipt2.ocr_result is None  # 纯手动无留痕


# ── 入库方式②：Excel 解析自动填单（2026-11-12 替代截图解析）──


def _xlsx_bytes(rows: list[list]) -> bytes:
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["物资名称", "规格型号", "数量", "单位", "供应商", "送货单号", "备注"])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_erp_export_headers_parse():
    """ERP 导出直传口径（2026-11-19）：ERP 列名（物料名称/入库数量/主计量单位/
    入库单号）经 COLUMN_ALIASES 归一解析；行级入库单号供网关分单。"""
    import io

    from openpyxl import Workbook

    from app.modules.warehouse.hardware.excel_io import parse_receipt_excel

    wb = Workbook()
    ws = wb.active
    ws.append(["入库单号", "入库日期", "物料名称", "主计量单位", "入库数量"])
    ws.append(["CGRK-001", "2026-11-19", "304不锈钢球阀", "个", 10])
    ws.append(["CGRK-001", "2026-11-19", "ABS管道", "米", 20])
    ws.append(["CGRK-002", "2026-11-19", "UPVC三通", "个", 5])
    buf = io.BytesIO()
    wb.save(buf)
    parsed = parse_receipt_excel(buf.getvalue(), "erp.xlsx")
    assert len(parsed["items"]) == 3
    by_name = {r["name"]: r for r in parsed["items"]}
    # ERP 列名归一：物料名称/入库数量/主计量单位 全部落位
    assert by_name["304不锈钢球阀"]["quantity"] == "10"
    assert by_name["304不锈钢球阀"]["unit"] == "个"
    # 行级入库单号（gateway 按此分单）
    assert by_name["UPVC三通"]["delivery_note_no"] == "CGRK-002"
    assert by_name["304不锈钢球阀"]["delivery_note_no"] == "CGRK-001"

    data = _xlsx_bytes([
        ["ABS管道", "dn40*3.7mm", 20, "米", "供应商A", "SH-9", ""],
        ["UPVC三通", "dn50", "abc", "个", "", "", ""],  # 数量非法 → errors
        ["", "", 5, "", "", "", ""],  # 空行忽略
    ])
    parsed = parse_receipt_excel(data, "r.xlsx")
    assert parsed["header"]["supplier_name"] == "供应商A"
    assert parsed["header"]["delivery_note_no"] == "SH-9"
    assert len(parsed["items"]) == 1 and parsed["items"][0]["quantity"] == "20"
    assert len(parsed["errors"]) == 1 and parsed["errors"][0]["row"] == 3


def test_receipt_excel_parse_structural_error():
    from app.modules.warehouse.hardware.excel_io import ExcelParseError, parse_receipt_excel

    # 缺「物资名称/数量」列（raw Workbook 直造：绕开 _xlsx_bytes 固定标准表头）
    import io as _io

    from openpyxl import Workbook as _Wb

    _wb = _Wb()
    _wb.active.append(["名称", "规格"])
    _wb.active.append(["X", "Y"])
    _buf = _io.BytesIO()
    _wb.save(_buf)
    with pytest.raises(ExcelParseError):
        parse_receipt_excel(_buf.getvalue(), "bad.xlsx")
    with pytest.raises(ExcelParseError):
        parse_receipt_excel(b"binary-not-excel", "x.xlsx")  # 损坏内容


async def test_excel_parse_matches_materials_and_source_persists(db_session):
    """excel/parse 匹配主数据 + source=excel 提交落库留痕（excel_result→ocr_result 列）。"""
    from app.modules.warehouse.hardware.excel_io import parse_receipt_excel
    from unittest.mock import patch

    m1 = HardwareMaterial(name="304不锈钢球阀·E1", spec="DN25", unit="个", category="金属阀门",
                          managed_class="stocked", safety_stock=Decimal("0"), no_expiry=True)
    db_session.add(m1)
    await db_session.flush()

    data = _xlsx_bytes([["304不锈钢球阀·E1", "DN25", 8, "个", "供应商E", "SH-E1", ""]])
    parsed = parse_receipt_excel(data, "r.xlsx")

    from app.modules.warehouse.hardware import matcher as hw_matcher
    from app.modules.warehouse.hardware.receipt_pipeline import load_active_materials

    materials = await load_active_materials(db_session)
    result = hw_matcher.match_one(
        name=parsed["items"][0]["name"], spec=parsed["items"][0]["spec"], materials=materials
    )
    assert result.material is not None and result.material.id == m1.id

    payload = ReceiptCreate(
        source="excel", mode="stocked",
        supplier_name="供应商E", delivery_note_no="SH-E1",
        excel_result=parsed,
        items=[ReceiptItemIn(material_id=str(m1.id), name="304不锈钢球阀·E1",
                             spec="DN25", unit="个", quantity=Decimal("8"),
                             match_confidence=result.method)],
    )
    receipt = await hw.create_receipt(db_session, payload)
    assert receipt.status == "draft" and receipt.source == "excel"
    assert receipt.ocr_result == parsed  # Excel 留痕复用 ocr_result 列


# ── 按入库单号分单 + 未匹配不可建单（2026-11-20 拍板：Web 对齐机器人通道口径）──


class _ItemStub:
    """build_parse_documents 桩：只暴露 managed_class（getattr 取值）。"""

    def __init__(self, managed_class=None):
        self.managed_class = managed_class


def test_build_parse_documents_grouping():
    """多单号分组：单号→单据、无单号兜底组、mode 规则（有 stocked 行=stocked）。"""
    from app.modules.warehouse.hardware.excel_io import build_parse_documents

    rows = [
        {"name": "A", "supplier": "供应商A", "delivery_note_no": " CGRK-001 "},
        {"name": "B", "supplier": "供应商A", "delivery_note_no": "CGRK-001"},
        {"name": "C", "supplier": "供应商B", "delivery_note_no": "CGRK-002"},
        {"name": "D", "supplier": None, "delivery_note_no": None},  # 无单号组
    ]
    items = [
        _ItemStub("stocked"),
        _ItemStub("direct"),
        _ItemStub(None),  # 未匹配
        _ItemStub("stocked"),
    ]
    docs = build_parse_documents(rows, items)
    by_key = {d["key"]: d for d in docs}
    assert set(by_key) == {"CGRK-001", "CGRK-002", ""}
    # 单号两侧空白归一
    assert by_key["CGRK-001"]["item_indexes"] == [0, 1]
    assert by_key["CGRK-001"]["supplier_name"] == "供应商A"
    # direct 行已匹配——unmatched 只数 managed_class=None
    assert by_key["CGRK-001"]["unmatched_count"] == 0
    assert by_key["CGRK-001"]["all_matched"] is True
    assert by_key["CGRK-001"]["stocked_count"] == 1 and by_key["CGRK-001"]["direct_count"] == 1
    assert by_key["CGRK-001"]["mode"] == "stocked"  # 有 stocked 行=stocked
    assert by_key["CGRK-002"]["unmatched_count"] == 1 and not by_key["CGRK-002"]["all_matched"]
    assert by_key["CGRK-002"]["mode"] == "direct"  # 无 stocked 行=direct
    # 无单号兜底组：delivery_note_no=None、单号空白归 key=""
    assert by_key[""]["item_indexes"] == [3] and by_key[""]["delivery_note_no"] is None


async def test_excel_create_rejects_unmatched_rows(db_session):
    """守卫：source=excel 含未匹配行（material_id=None）→ 422 不可建单。"""
    m1 = HardwareMaterial(name="304不锈钢球阀·U1", spec="DN25", unit="个", category="金属阀门",
                          managed_class="stocked", safety_stock=Decimal("0"), no_expiry=True)
    db_session.add(m1)
    await db_session.flush()

    bad = ReceiptCreate(
        source="excel", mode="stocked",
        items=[
            ReceiptItemIn(material_id=str(m1.id), name="304不锈钢球阀·U1",
                          spec="DN25", unit="个", quantity=Decimal("8")),
            ReceiptItemIn(name="清单外神秘物料", spec=None, unit="个", quantity=Decimal("2")),
        ],
    )
    with pytest.raises(hw.HardwareError) as exc_info:
        await hw.create_receipt(db_session, bad)
    assert "未匹配" in exc_info.value.message

    # 全匹配同行 → 通过（守卫不误伤）
    good = ReceiptCreate(
        source="excel", mode="stocked",
        items=[ReceiptItemIn(material_id=str(m1.id), name="304不锈钢球阀·U1",
                             spec="DN25", unit="个", quantity=Decimal("8"))],
    )
    receipt = await hw.create_receipt(db_session, good)
    assert receipt.status == "draft"


async def test_manual_source_allows_unmatched_rows(db_session):
    """manual 来源行为不变：未匹配行可建草稿（accept 门兜底），守卫只管 excel。"""
    bad = ReceiptCreate(
        source="manual", mode="stocked",
        items=[ReceiptItemIn(name="手动登记未匹配行", spec=None, unit="个", quantity=Decimal("1"))],
    )
    receipt = await hw.create_receipt(db_session, bad)
    assert receipt.status == "draft" and receipt.source == "manual"
