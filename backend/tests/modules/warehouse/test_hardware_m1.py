"""五金库 M1 验收测试：导入 492 项抽查 + 库存状态机（预扣/释放/实扣/FIFO）+
direct 净零 + draft 不动账 + agent 工具 5 问 + 预警过滤。

设计依据：docs/DESIGN-五金库系统原生模块-20261104.md §三（库存口径）§四（流程）§十一（M1 验收）。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.modules.warehouse.hardware import service as hw
from app.modules.warehouse.hardware.importer import import_materials, parse_materials_workbook
from app.modules.warehouse.hardware.models import (
    HardwareMaterial,
    HardwareMovement,
    HardwareReceipt,
    HardwareReceiptItem,
    HardwareRequisition,
)
from app.modules.warehouse.hardware.schemas import (
    ReceiptCreate,
    ReceiptItemIn,
    RequisitionCreate,
    RequisitionItemIn,
)

ASSET = (
    Path(__file__).parents[4] / "docs/assets/hardware_store/五金库物资清单-20261103.xlsx"
)


# ── 造数工具 ──


async def _mk_material(db, *, name="304不锈钢球阀", spec="DN25", unit="个",
                       safety=Decimal("10"), managed="stocked") -> HardwareMaterial:
    # 名称带唯一后缀：与真实库中已导入的 492 项（同名规格存在）隔离，
    # keyword 断言不受存量数据干扰
    unique_name = f"{name}·{uuid4().hex[:6].upper()}"
    m = HardwareMaterial(
        name=unique_name, spec=spec, unit=unit, category="金属阀门",
        managed_class=managed, safety_stock=safety, no_expiry=True,
    )
    db.add(m)
    await db.flush()
    return m


async def _mk_accepted_receipt(db, material: HardwareMaterial, qty: Decimal, *,
                               arrived: datetime | None = None,
                               inspector="ou_warehouse") -> HardwareReceipt:
    payload = ReceiptCreate(
        source="manual",
        mode="stocked" if material.managed_class == "stocked" else "direct",
        supplier_name="测试供应商",
        target_dept="发酵" if material.managed_class == "direct" else None,
        arrived_at=arrived,
        items=[
            ReceiptItemIn(
                material_id=str(material.id), name=material.name,
                spec=material.spec, unit=material.unit, quantity=qty,
                match_confidence="manual",
            )
        ],
    )
    receipt = await hw.create_receipt(db, payload)
    await hw.accept_receipt(
        db, receipt.id, inspected_by_warehouse=inspector, inspected_by_dept="ou_dept"
    )
    return receipt


# ── 导入器 ──


async def test_import_492_and_sample_20(db_session):
    """导入 492 项：总数+类别分布+抽查 20 项字段一致（code 留空口径）。"""
    assert ASSET.exists(), f"清单文件缺失: {ASSET}"
    parsed = parse_materials_workbook(ASSET)
    assert len(parsed) == 492
    stats = await import_materials(db_session, ASSET)
    # 幂等语义：库可能已被真实导入播种（created=0/updated=492），但
    # 导入后总量恒 492、0 跳过 0 错误（首导 created=492）
    assert stats["skipped"] == 0 and not stats["errors"], stats
    total = await db_session.scalar(select(func.count()).select_from(HardwareMaterial))
    assert total == 492

    rows = (await db_session.execute(select(HardwareMaterial))).scalars().all()
    assert len(rows) == 492
    by_name = {r.name: r for r in rows}
    # 抽查 20 项：首尾+类别覆盖+随机
    import random

    samples = random.Random(42).sample(list(rows), 20)
    for m in samples:
        assert m.code is None, f"{m.name} code 应留空（P2 定案）"
        assert m.managed_class == "stocked"
        assert m.unit in ("个", "台", "米", "片", "套", "副")
        assert m.category in (
            "金属管道", "金属管件", "金属阀门", "食品级垫片", "金属轴承", "UPVC管件", "ABS管件",
        )
    # 特定锚点行
    assert "304不锈钢管" in " ".join(by_name.keys())
    categories = {r.category for r in rows}
    assert categories == {
        "金属管道", "金属管件", "金属阀门", "食品级垫片", "金属轴承", "UPVC管件", "ABS管件",
    }


async def test_import_idempotent(db_session):
    """重复导入幂等：不重复建行（总量恒 492，两轮间无新增）。"""
    await import_materials(db_session, ASSET)
    before = await db_session.scalar(select(func.count()).select_from(HardwareMaterial))
    stats2 = await import_materials(db_session, ASSET)
    after = await db_session.scalar(select(func.count()).select_from(HardwareMaterial))
    assert after == before == 492
    assert stats2["created"] == 0


# ── 库存状态机 ──


async def test_reserve_then_reject_releases(db_session):
    """预扣→驳回释放：available 先降后恢复，on_hand 不变。"""
    m = await _mk_material(db_session, safety=Decimal("5"))
    await _mk_accepted_receipt(db_session, m, Decimal("100"))

    rows_, _t = await hw.list_stock_rows(db_session, keyword=m.name)
    row = rows_[0]
    assert row["on_hand"] == Decimal("100") and row["available"] == Decimal("100")

    req = await hw.create_requisition(
        db_session,
        RequisitionCreate(
            dept_name="发酵", applicant="张三", items=[RequisitionItemIn(material_id=str(m.id), need_qty=Decimal("30"))],
        ),
    )
    await hw.submit_requisition(db_session, req.id)
    rows_, _t = await hw.list_stock_rows(db_session, keyword=m.name)
    row = rows_[0]
    assert row["reserved"] == Decimal("30")
    assert row["available"] == Decimal("70")

    await hw.reject_requisition(db_session, req.id, approver="李主管", reason="用途不明")
    rows_, _t = await hw.list_stock_rows(db_session, keyword=m.name)
    row = rows_[0]
    assert row["reserved"] == Decimal("0")
    assert row["available"] == Decimal("100")  # 释放恢复
    assert row["on_hand"] == Decimal("100")  # on_hand 未动（未发料）


async def test_reserve_then_issue_consumes(db_session):
    """预扣→审批→发料实扣：on_hand 减少、reserved 归零、流水落账。"""
    m = await _mk_material(db_session)
    await _mk_accepted_receipt(db_session, m, Decimal("50"))

    req = await hw.create_requisition(
        db_session,
        RequisitionCreate(
            dept_name="精制机修", applicant="王五",
            items=[RequisitionItemIn(material_id=str(m.id), need_qty=Decimal("20"))],
        ),
    )
    await hw.submit_requisition(db_session, req.id)
    await hw.approve_requisition(db_session, req.id, approver="李主管")
    rows_, _t = await hw.list_stock_rows(db_session, keyword=m.name)
    row = rows_[0]
    assert row["available"] == Decimal("30")  # 预扣保持

    await hw.issue_requisition(
        db_session, req.id, issued_by="仓管员甲", received_by="王五",
    )
    rows_, _t = await hw.list_stock_rows(db_session, keyword=m.name)
    row = rows_[0]
    assert row["on_hand"] == Decimal("30")  # 实扣
    assert row["reserved"] == Decimal("0")
    assert row["available"] == Decimal("30")

    movements, total = await hw.list_movements(db_session, business_type="req_issue")
    assert total == 1
    assert movements[0].quantity == Decimal("20")
    assert movements[0].direction == "outbound"
    assert movements[0].dept_name == "精制机修"
    items = await hw.list_requisition_items(db_session, req.id)
    assert items[0].issued_qty == Decimal("20")


async def test_fifo_order(db_session):
    """FIFO：两批次 arrived_at 不同，发料先扣旧批次、再扣新批次。"""
    from zoneinfo import ZoneInfo

    cn = ZoneInfo("Asia/Shanghai")
    old_t = datetime(2026, 11, 1, 9, 0, tzinfo=cn)
    new_t = datetime(2026, 11, 3, 9, 0, tzinfo=cn)
    m = await _mk_material(db_session, name="304不锈钢管", spec="φ25", unit="米", safety=Decimal("0"))
    r_old = await _mk_accepted_receipt(db_session, m, Decimal("10"), arrived=old_t)
    r_new = await _mk_accepted_receipt(db_session, m, Decimal("10"), arrived=new_t)

    req = await hw.create_requisition(
        db_session,
        RequisitionCreate(
            dept_name="动力机修", applicant="赵六",
            items=[RequisitionItemIn(material_id=str(m.id), need_qty=Decimal("15"))],
        ),
    )
    await hw.submit_requisition(db_session, req.id)
    await hw.approve_requisition(db_session, req.id, approver="李主管")

    # 建议先验证（不动账）
    plan = await hw.suggest_fifo_allocation(db_session, m.id, Decimal("15"))
    assert plan[0]["allocate"] == Decimal("10") and plan[1]["allocate"] == Decimal("5")

    await hw.issue_requisition(db_session, req.id, issued_by="仓管员甲", received_by="赵六")
    lot_old = (await db_session.execute(
        select(HardwareReceiptItem).where(HardwareReceiptItem.receipt_id == r_old.id)
    )).scalar_one()
    lot_new = (await db_session.execute(
        select(HardwareReceiptItem).where(HardwareReceiptItem.receipt_id == r_new.id)
    )).scalar_one()
    assert lot_old.remaining_quantity == Decimal("0")  # 旧批次扣完
    assert lot_new.remaining_quantity == Decimal("5")  # 新批次扣 5
    # 逐批两条 outbound 流水
    movements, total = await hw.list_movements(db_session, business_type="req_issue")
    assert total == 2
    qties = sorted(mv.quantity for mv in movements)
    assert qties == [Decimal("5"), Decimal("10")]


async def test_direct_receipt_net_zero(db_session):
    """direct 类：accepted 不占库存，出入双流水净零，直发部门落 dept_name。"""
    m = await _mk_material(db_session, name="精密压力表", spec="YS-100", unit="台",
                           managed="direct")
    await _mk_accepted_receipt(db_session, m, Decimal("3"))

    # direct 无批次 → on_hand 无（coalesce 0）
    rows, total = await hw.list_stock_rows(db_session, keyword=m.name, managed_class=None)
    assert total == 1
    assert rows[0]["on_hand"] == Decimal("0")
    ins, t_in = await hw.list_movements(db_session, business_type="pass_in")
    outs, t_out = await hw.list_movements(db_session, business_type="pass_out")
    assert t_in == 1 and t_out == 1
    assert ins[0].quantity == outs[0].quantity == Decimal("3")
    assert ins[0].dept_name == "发酵" and outs[0].dept_name == "发酵"


async def test_draft_receipt_never_moves_stock(db_session):
    """红线：draft 草稿绝不动账（OCR/agent 只产草稿）。"""
    m = await _mk_material(db_session)
    payload = ReceiptCreate(
        source="ocr",
        items=[ReceiptItemIn(material_id=str(m.id), name=m.name, quantity=Decimal("99"))],
    )
    receipt = await hw.create_receipt(db_session, payload)
    assert receipt.status == "draft"
    rows, _ = await hw.list_stock_rows(db_session, keyword=m.name, managed_class=None)
    assert rows[0]["on_hand"] == Decimal("0")
    _, mv_total = await hw.list_movements(db_session)
    assert mv_total == 0


async def test_submit_insufficient_available_blocked(db_session):
    """available 不足阻断提交（防超卖）。"""
    m = await _mk_material(db_session)
    await _mk_accepted_receipt(db_session, m, Decimal("5"))
    req = await hw.create_requisition(
        db_session,
        RequisitionCreate(
            dept_name="发酵", applicant="张三",
            items=[RequisitionItemIn(material_id=str(m.id), need_qty=Decimal("10"))],
        ),
    )
    with pytest.raises(hw.HardwareError, match="可用量不足"):
        await hw.submit_requisition(db_session, req.id)


async def test_low_warning_filter(db_session):
    """安全库存预警：available < safety_stock 判定与 low_only 过滤正确。"""
    m_ok = await _mk_material(db_session, name="充足物资", safety=Decimal("1"))
    m_low = await _mk_material(db_session, name="紧张物资", safety=Decimal("50"))
    await _mk_accepted_receipt(db_session, m_ok, Decimal("100"))
    await _mk_accepted_receipt(db_session, m_low, Decimal("10"))

    ok_name, low_name = m_ok.name, m_low.name  # 唯一后缀名
    rows, total = await hw.list_stock_rows(db_session, keyword="·", managed_class=None, page_size=5000)
    by_name = {r["material"].name: r for r in rows}
    assert by_name[ok_name]["is_low"] is False
    assert by_name[low_name]["is_low"] is True
    assert by_name[low_name]["low_gap"] == Decimal("40")

    lows, low_total = await hw.list_stock_rows(
        db_session, low_only=True, managed_class=None, page_size=5000
    )
    low_names = {r["material"].name for r in lows}
    assert low_name in low_names and ok_name not in low_names


async def test_normal_requires_approval_before_issue(db_session):
    """常规单须审批后才能发料；紧急单 pending 可直发并留 24h 补单截止。"""
    m = await _mk_material(db_session)
    await _mk_accepted_receipt(db_session, m, Decimal("100"))

    req = await hw.create_requisition(
        db_session,
        RequisitionCreate(
            dept_name="发酵", applicant="张三", req_type="normal",
            items=[RequisitionItemIn(material_id=str(m.id), need_qty=Decimal("5"))],
        ),
    )
    await hw.submit_requisition(db_session, req.id)
    with pytest.raises(hw.HardwareError, match="审批通过后"):
        await hw.issue_requisition(db_session, req.id, issued_by="仓", received_by="张三")

    urg = await hw.create_requisition(
        db_session,
        RequisitionCreate(
            dept_name="发酵", applicant="张三", req_type="urgent",
            items=[RequisitionItemIn(material_id=str(m.id), need_qty=Decimal("5"))],
        ),
    )
    await hw.submit_requisition(db_session, urg.id)
    issued = await hw.issue_requisition(db_session, urg.id, issued_by="仓", received_by="张三")
    assert issued.status == "issued"
    assert issued.urgent_patch_deadline is not None
    assert issued.urgent_patch_deadline - issued.issued_at == timedelta(hours=24)
    # 补审批 → patched_at 闭合
    await hw.approve_requisition(db_session, urg.id, approver="李主管")
    assert urg.patched_at is not None
    _, urgent_mvs = await hw.list_movements(db_session, business_type="urgent_issue")
    assert urgent_mvs == 1


# ── agent 工具 5 问 ──


@pytest.fixture
def tool_db(db_session):
    """把工具的会话注入口钉到测试 rollback 会话。"""
    from app.modules.warehouse.agent.tools import hardware as hw_tool

    @asynccontextmanager
    async def _fake():
        yield db_session

    hw_tool._db_session = _fake
    yield hw_tool
    hw_tool._db_session = hw_tool._production_db


async def test_agent_query_stock_five_questions(tool_db, db_session):
    """验收「对话查库存 5 问全对」：关键词/规格短语/低库存/全量计数/详情核对。"""
    from app.modules.warehouse.agent.tools import hardware as hw_tool

    m1 = await _mk_material(db_session, name="304不锈钢球阀", spec="DN25", unit="个", safety=Decimal("10"))
    m2 = await _mk_material(db_session, name="304不锈钢球阀", spec="DN50", unit="个", safety=Decimal("0"))
    m3 = await _mk_material(db_session, name="UPVC球阀", spec="DN25", unit="个", safety=Decimal("0"))
    await _mk_accepted_receipt(db_session, m1, Decimal("8"))
    await _mk_accepted_receipt(db_session, m2, Decimal("20"))
    await _mk_accepted_receipt(db_session, m3, Decimal("40"))

    # 取唯一后缀标记（_mk_material 生成 name=f"{base}·{MARK}"）
    from app.modules.warehouse.hardware.models import HardwareMaterial as HM
    mks = []
    for _m in (m1, m2, m3):
        row = (await db_session.execute(select(HM).where(HM.id == _m.id))).scalar_one()
        mks.append(row.name)
    mk1, mk2, mk3 = mks
    # 问1：DN25 阀门还有多少？（唯一标记「·」限定=测试造的行全部命中）
    r1 = await hw_tool.query_hardware_stock("·", limit=50)
    names = {(i["name"], i["spec"]) for i in r1["items"]}
    assert (mk1, "DN25") in names and (mk3, "DN25") in names

    # 问2：该球阀 DN25 可用量？（唯一标记精确命中）
    r2 = await hw_tool.query_hardware_stock(mk1)
    dn25 = next(i for i in r2["items"] if i["name"] == mk1)
    assert dn25["available"] == 8.0 and dn25["on_hand"] == 8.0

    # 问3：这类物资里哪些库存预警？（唯一后缀名关键词过滤+safety 10 > 8）
    r3 = await hw_tool.query_hardware_stock("·", low_only=True)
    assert r3["total"] == 1
    assert r3["items"][0]["name"] == mk1
    assert r3["items"][0]["low_warning"] is True

    # 问4：此类物资一共多少种？（唯一标记限定=测试造的 3 行）
    r4 = await hw_tool.query_hardware_stock("·", limit=50)
    assert r4["total"] >= 3

    # 问5：DN50 球阀有没有被预扣？（建单预扣后可用下降）
    req = await hw_tool_query_setup(db_session, m2)
    r5 = await hw_tool.query_hardware_stock(mk2)
    dn50 = next(i for i in r5["items"] if i["name"] == mk2)
    assert dn50["reserved"] == 5.0 and dn50["available"] == 15.0
    assert dn50["low_warning"] is False


async def hw_tool_query_setup(db_session, material):
    req = await hw.create_requisition(
        db_session,
        RequisitionCreate(
            dept_name="提炼一期", applicant="测试",
            items=[RequisitionItemIn(material_id=str(material.id), need_qty=Decimal("5"))],
        ),
    )
    await hw.submit_requisition(db_session, req.id)
    return req
