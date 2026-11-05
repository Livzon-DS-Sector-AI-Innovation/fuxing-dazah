"""五金库 M4 验收测试：盘点闭环（生成/实盘/差异/确认 ADJ/期初校准/差异表导出）
+ 退库链（验收/拒退/批次回加）。

设计依据：docs/DESIGN-五金库系统原生模块-20261104.md §2.6（二期表模型）§十一 二期
（验收标准原文）；spec .scratch/hardware-store-p2/spec.md。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from io import BytesIO
from uuid import uuid4

import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select

from app.modules.warehouse.hardware import service as hw
from app.modules.warehouse.hardware import stocktake as st
from app.modules.warehouse.hardware.models import (
    HardwareMovement,
    HardwareReceipt,
    HardwareReceiptItem,
    HardwareReturn,
    HardwareStocktake,
    HardwareStocktakeItem,
)


# ── 造数工具（沿 M1 模式：uuid 后缀隔离共享开发库存量）──


async def _mk_material(db, *, name="304不锈钢球阀", spec="DN25", unit="个",
                       safety=Decimal("10"), price=Decimal("10.0000")):
    m = type("M", (), {})  # placeholder for type hint only
    from app.modules.warehouse.hardware.models import HardwareMaterial

    material = HardwareMaterial(
        name=f"{name}·{uuid4().hex[:6].upper()}", spec=spec, unit=unit,
        category="金属阀门", managed_class="stocked", safety_stock=safety,
        no_expiry=True, unit_price=price,
    )
    db.add(material)
    await db.flush()
    return material


async def _mk_inbound(db, material, qty: Decimal, *, arrived=None) -> None:
    """直接造 accepted 批次（绕过 receipt 全流程，测试聚焦盘点/退库本身）。"""
    from app.modules.warehouse.hardware.schemas import (
        ReceiptCreate,
        ReceiptItemIn,
    )

    payload = ReceiptCreate(
        source="manual", mode="stocked", supplier_name="测试供应商",
        arrived_at=arrived,
        items=[ReceiptItemIn(
            material_id=str(material.id), name=material.name,
            spec=material.spec, unit=material.unit, quantity=qty,
            match_confidence="manual", unit_price=material.unit_price,
        )],
    )
    receipt = await hw.create_receipt(db, payload)
    await hw.accept_receipt(
        db, receipt.id, inspected_by_warehouse="ou_warehouse", inspected_by_dept="ou_dept",
    )


# ── Ticket 01：盘点底座 ──


async def test_stocktake_create_snapshots_book(db_session):
    """生成盘点单：book 快照自当前批次余额（有批次=Σremaining，零库存=0）。"""
    m1 = await _mk_material(db_session, name="盘点物料甲")
    m2 = await _mk_material(db_session, name="盘点物料乙")
    await _mk_inbound(db_session, m1, Decimal("15"))
    await _mk_inbound(db_session, m1, Decimal("10"))

    take = await st.create_stocktake(db_session, take_type="monthly", creator="仓管员甲")
    assert take.take_no.startswith("WJK-PD-")
    assert take.status == "draft"
    items = await st.list_stocktake_items(db_session, take.id)
    by_material = {str(i.material_id): i for i in items}
    assert len(items) >= 2
    assert by_material[str(m1.id)].book_qty == Decimal("25")
    assert by_material[str(m2.id)].book_qty == Decimal("0")
    # 快照列冗余主数据
    assert by_material[str(m1.id)].name == m1.name
    assert by_material[str(m1.id)].unit == m1.unit


async def test_stocktake_fill_actual_and_diff(db_session):
    """实盘直填：填数即算差异（diff=actual−book，金额=unit_price×diff）。"""
    m1 = await _mk_material(db_session, name="盘点物料丙")
    await _mk_inbound(db_session, m1, Decimal("25"))

    take = await st.create_stocktake(db_session, take_type="monthly", creator="仓管员甲")
    items = await st.list_stocktake_items(db_session, take.id)
    target = next(i for i in items if i.material_id == m1.id)

    updated = await st.fill_stocktake_item(
        db_session, take.id, target.id, actual_qty=Decimal("23"),
        explanation="领用未登记 2 个",
    )
    assert updated.actual_qty == Decimal("23")
    assert updated.diff_qty == Decimal("-2")
    assert updated.diff_amount == Decimal("-20.000")  # 单价 10 × −2
    # 首次实盘把单据推进 counting
    await db_session.refresh(take)
    assert take.status == "counting"

    # 未盘行 actual 为 NULL，diff 不算
    others = [i for i in items if i.id != target.id]
    for i in others:
        assert i.actual_qty is None and i.diff_qty is None


async def test_stocktake_export_excel_columns(db_session):
    """差异表导出 Excel：6 列中文表头无乱码，行数据与 items 一致。"""
    m1 = await _mk_material(db_session, name="盘点物料丁")
    await _mk_inbound(db_session, m1, Decimal("25"))
    take = await st.create_stocktake(db_session, take_type="monthly", creator="仓管员甲")
    items = await st.list_stocktake_items(db_session, take.id)
    target = next(i for i in items if i.material_id == m1.id)
    await st.fill_stocktake_item(
        db_session, take.id, target.id, actual_qty=Decimal("26"),
    )

    xlsx_bytes = await st.export_stocktake_excel(db_session, take.id)
    wb = load_workbook(BytesIO(xlsx_bytes))
    ws = wb.active
    headers = [c.value for c in ws[1]]
    assert headers == ["物料编码", "物资名称", "账存数量", "实存数量", "差异数量", "差异金额"]
    # 找到 m1 行
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    row = next(r for r in rows if r[1] == m1.name)
    # code 留空（P2 定案）：导出空串，openpyxl 回读为 None
    assert row[0] in (m1.code, None, "")
    assert row[2] == 25 and row[3] == 26 and row[4] == 1
    assert row[5] == 10  # 10 × 1


# ── Ticket 02：确认门 + 期初校准链 ──


async def _fill_all(db, take, actual_map: dict) -> None:
    items = await st.list_stocktake_items(db, take.id)
    for i in items:
        actual = actual_map.get(str(i.material_id))
        if actual is not None:
            await st.fill_stocktake_item(db, take.id, i.id, actual_qty=actual)


async def test_stocktake_confirm_adj_full_flow(db_session):
    """确认门全流程：盘盈→盘点入库单批次+inbound ADJ；盘亏→FIFO 扣+outbound ADJ。"""
    m_surplus = await _mk_material(db_session, name="盘盈物料")
    m_deficit = await _mk_material(db_session, name="盘亏物料")
    await _mk_inbound(db_session, m_deficit, Decimal("30"))

    take = await st.create_stocktake(db_session, take_type="monthly", creator="仓管员甲")
    await _fill_all(
        db_session, take,
        {str(m_surplus.id): Decimal("8"), str(m_deficit.id): Decimal("28")},
    )
    # 未盘完（其余存量物料未填）不可 review —— 用独立小单断言门，本单先填齐
    items = await st.list_stocktake_items(db_session, take.id)
    for i in items:
        if i.actual_qty is None:
            await st.fill_stocktake_item(db_session, take.id, i.id, actual_qty=i.book_qty)

    reviewed = await st.review_stocktake(db_session, take.id, explained_by="仓管员甲")
    assert reviewed.status == "reviewed"
    confirmed = await st.confirm_stocktake(db_session, take.id, confirmed_by="仓储负责人乙")
    assert confirmed.status == "confirmed"

    # 盘盈：on_hand=8（新盘点批次），inbound stocktake_adj 流水
    avail_s = await hw.get_material_stock(db_session, m_surplus.id)
    assert avail_s["on_hand"] == Decimal("8")
    assert avail_s["available"] == Decimal("8")
    adj_in = await db_session.scalar(
        select(func.count()).select_from(HardwareMovement).where(
            HardwareMovement.material_id == m_surplus.id,
            HardwareMovement.business_type == "stocktake_adj",
            HardwareMovement.direction == "inbound",
            HardwareMovement.ref_table == "hardware_stocktakes",
            HardwareMovement.ref_id == take.id,
        )
    )
    assert adj_in == 1
    # 盘盈载体批次可查（source=stocktake 的 accepted 入库单行）
    lot_row = await db_session.scalar(
        select(HardwareReceiptItem.remaining_quantity).join(
            HardwareReceipt, HardwareReceipt.id == HardwareReceiptItem.receipt_id
        ).where(
            HardwareReceiptItem.material_id == m_surplus.id,
            HardwareReceipt.source == "stocktake",
            HardwareReceipt.status == "accepted",
        )
    )
    assert lot_row == Decimal("8")

    # 盘亏：on_hand=28，outbound stocktake_adj 流水
    avail_d = await hw.get_material_stock(db_session, m_deficit.id)
    assert avail_d["on_hand"] == Decimal("28")
    adj_out = await db_session.scalar(
        select(func.count()).select_from(HardwareMovement).where(
            HardwareMovement.material_id == m_deficit.id,
            HardwareMovement.business_type == "stocktake_adj",
            HardwareMovement.direction == "outbound",
            HardwareMovement.ref_id == take.id,
        )
    )
    assert adj_out == 1
    # 单头汇总回写
    await db_session.refresh(confirmed)
    assert confirmed.diff_surplus_items == 1
    assert confirmed.diff_deficit_items == 1
    # 已确认不可重复确认/不可作废
    with pytest.raises(hw.HardwareError):
        await st.confirm_stocktake(db_session, take.id, confirmed_by="再确认")


async def test_stocktake_calibration_chain(db_session):
    """期初校准链（P4）：零库存+实物盘盈→确认→ADJ 入账→available 正确。"""
    m = await _mk_material(db_session, name="期初校准物料")
    take = await st.create_stocktake(
        db_session, take_type="calibration", creator="仓管员甲",
        note="上线首次全面盘点（存量盘盈校准）",
    )
    items = await st.list_stocktake_items(db_session, take.id)
    for i in items:
        actual = Decimal("10") if i.material_id == m.id else i.book_qty
        await st.fill_stocktake_item(db_session, take.id, i.id, actual_qty=actual)
    await st.review_stocktake(db_session, take.id, explained_by="仓管员甲")
    await st.confirm_stocktake(db_session, take.id, confirmed_by="仓储负责人乙")

    stock = await hw.get_material_stock(db_session, m.id)
    assert stock["on_hand"] == Decimal("10")
    assert stock["available"] == Decimal("10")
    # 批次可见（盘点入库单批次，FIFO 可发）
    assert stock["lots"] and stock["lots"][0]["remaining_quantity"] == Decimal("10")


async def test_stocktake_review_requires_full_count(db_session):
    """未盘完不可 review（差异表口径=全行已盘）。"""
    m1 = await _mk_material(db_session, name="门禁物料")
    await _mk_inbound(db_session, m1, Decimal("5"))
    take = await st.create_stocktake(db_session, take_type="special", creator="仓管员甲")
    items = await st.list_stocktake_items(db_session, take.id)
    target = next(i for i in items if i.material_id == m1.id)
    await st.fill_stocktake_item(db_session, take.id, target.id, actual_qty=Decimal("5"))
    # 其余行未盘 → review 拒绝
    with pytest.raises(hw.HardwareError):
        await st.review_stocktake(db_session, take.id, explained_by="仓管员甲")
    # 非 reviewed 不可 confirm
    with pytest.raises(hw.HardwareError):
        await st.confirm_stocktake(db_session, take.id, confirmed_by="仓储负责人乙")
    # cancelled 不动账
    cancelled = await st.cancel_stocktake(db_session, take.id)
    assert cancelled.status == "cancelled"
    stock = await hw.get_material_stock(db_session, m1.id)
    assert stock["on_hand"] == Decimal("5")


# ── Ticket 03：退库链 ──


async def test_return_accept_back_to_preferred_lot(db_session):
    """退库验收：优先回原 lot 增 remaining + return_in 流水（恒正 inbound）。"""
    m = await _mk_material(db_session, name="退库物料甲")
    await _mk_inbound(db_session, m, Decimal("20"))
    lot = (await hw.get_fifo_lots(db_session, m.id))[0]

    ret = await st.create_return(
        db_session,
        dept_name="发酵", returned_by="张三",
        items=[{
            "material_id": str(m.id), "quantity": float(5),
            "preferred_lot_id": str(lot.id),
        }],
    )
    assert ret.return_no.startswith("WJK-TK-")
    # 未负责人签 → 验收被拒
    with pytest.raises(hw.HardwareError):
        await st.accept_return(db_session, ret.id, accepted_by="仓管员甲")
    await st.sign_return(db_session, ret.id, leader="李主管")

    accepted = await st.accept_return(db_session, ret.id, accepted_by="仓管员甲")
    assert accepted.status == "accepted"
    await db_session.refresh(lot)
    assert lot.remaining_quantity == Decimal("25")  # 20+5 回原批次
    mv = (
        await db_session.execute(
            select(HardwareMovement).where(
                HardwareMovement.material_id == m.id,
                HardwareMovement.business_type == "return_in",
                HardwareMovement.ref_table == "hardware_returns",
            )
        )
    ).scalars().all()
    assert len(mv) == 1 and mv[0].direction == "inbound"
    assert mv[0].quantity == Decimal("5")
    # 回加结果留痕
    assert accepted.lot_adjustments[0]["mode"] == "preferred"


async def test_return_accept_new_lot_when_preferred_missing(db_session):
    """原 lot 不存在 → 新建 return 来源批次（receipt source=return）。"""
    m = await _mk_material(db_session, name="退库物料乙")
    ghost_lot_id = uuid4()  # 不存在的批次

    ret = await st.create_return(
        db_session,
        dept_name="提炼一期", returned_by="王五",
        items=[{
            "material_id": str(m.id), "quantity": float(3),
            "preferred_lot_id": str(ghost_lot_id),
        }],
    )
    await st.sign_return(db_session, ret.id, leader="李主管")
    accepted = await st.accept_return(db_session, ret.id, accepted_by="仓管员甲")

    stock = await hw.get_material_stock(db_session, m.id)
    assert stock["on_hand"] == Decimal("3")
    lots = [l for l in stock["lots"] if l["remaining_quantity"] == Decimal("3")]
    assert lots, "应新建 return 来源批次"
    assert accepted.lot_adjustments[0]["mode"] == "new"
    # 载体单 source=return 且直接 accepted
    carrier = await db_session.get(
        HardwareReceipt, accepted.lot_adjustments[0]["carrier_receipt_id"]
    )
    assert carrier is not None and carrier.source == "return" and carrier.status == "accepted"


async def test_return_rejected_no_stock_change(db_session):
    """不合格拒退：留原因、不动账、无流水。"""
    m = await _mk_material(db_session, name="退库物料丙")
    await _mk_inbound(db_session, m, Decimal("10"))
    ret = await st.create_return(
        db_session,
        dept_name="动力机修", returned_by="赵六",
        items=[{"material_id": str(m.id), "quantity": float(2)}],
    )
    await st.sign_return(db_session, ret.id, leader="李主管")
    rejected = await st.reject_return(
        db_session, ret.id, reason="包装破损无法回库"
    )
    assert rejected.status == "rejected"
    assert rejected.rejected_reason == "包装破损无法回库"
    stock = await hw.get_material_stock(db_session, m.id)
    assert stock["on_hand"] == Decimal("10")
    cnt = await db_session.scalar(
        select(func.count()).select_from(HardwareMovement).where(
            HardwareMovement.business_type == "return_in",
            HardwareMovement.ref_table == "hardware_returns",
            HardwareMovement.ref_id == ret.id,
        )
    )
    assert cnt == 0
    # 已拒退不可再验收
    with pytest.raises(hw.HardwareError):
        await st.accept_return(db_session, ret.id, accepted_by="仓管员甲")
