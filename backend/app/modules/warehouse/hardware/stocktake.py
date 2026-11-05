"""五金库盘点 + 退库 service（二期 M4，设计 §2.6）。

盘点闭环：生成（book 快照自当前批次余额）→ 手机实盘直填 → 差异表导出 →
差异说明+确认（Web 确认门，人确认才生效）→ stocktake_adj movements 入账：
- 盘盈行：生成「盘点盘盈入库单」（receipt source=stocktake 直接 accepted，
  行 remaining=quantity=新批次）+ inbound adjust 流水 → on_hand 增加；
- 盘亏行：FIFO 扣批次 remaining + outbound adjust 流水。

期初校准（P4）：take_type=calibration——零库存起步后首次全面盘点的存量盘盈
入账，走同一确认链路。

退库：draft（退库人）→ 部门负责人签 → 仓管员验收：accepted=批次回加
（优先回原 lot 增 remaining；原 lot 不存在则新建 return 来源批次）+
return_in 流水；rejected=不合格拒退留证不动账。
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.hardware import service as hw
from app.modules.warehouse.hardware.models import (
    HardwareMaterial,
    HardwareMovement,
    HardwareReceipt,
    HardwareReceiptItem,
    HardwareReturn,
    HardwareStocktake,
    HardwareStocktakeItem,
)

logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")
ZERO = Decimal("0")

_TAKE_NO_COLUMN = HardwareStocktake.__table__.c.take_no
_RETURN_NO_COLUMN = HardwareReturn.__table__.c.return_no


def _now() -> datetime:
    return datetime.now(CN_TZ)


# ── 盘点单 ──


async def create_stocktake(
    db: AsyncSession,
    *,
    take_type: str = "monthly",
    creator: str | None = None,
    note: str | None = None,
    user: Any = None,
) -> HardwareStocktake:
    """生成盘点单：全 active stocked 物料逐行 book 快照（Σ accepted 批次余额）。"""
    if take_type not in ("monthly", "annual", "special", "calibration"):
        raise hw.HardwareError(f"未知盘点类型: {take_type}", status_code=422)
    now = _now()
    take = HardwareStocktake(
        take_no=await hw.generate_doc_no(
            db, HardwareStocktake, "WJK-PD", column=_TAKE_NO_COLUMN
        ),
        take_type=take_type,
        status="draft",
        snapshot_at=now,
        summary_note=note,
        created_by=user.id if user is not None else None,
    )
    db.add(take)
    await db.flush()

    on_hand = (
        select(
            HardwareReceiptItem.material_id.label("material_id"),
            func.sum(HardwareReceiptItem.remaining_quantity).label("qty"),
        )
        .join(HardwareReceipt, HardwareReceipt.id == HardwareReceiptItem.receipt_id)
        .where(
            HardwareReceipt.status == "accepted",
            HardwareReceipt.is_deleted.is_(False),
            HardwareReceiptItem.is_deleted.is_(False),
            HardwareReceiptItem.remaining_quantity.isnot(None),
        )
        .group_by(HardwareReceiptItem.material_id)
        .subquery()
    )
    materials = (
        await db.execute(
            select(HardwareMaterial, func.coalesce(on_hand.c.qty, ZERO))
            .outerjoin(on_hand, on_hand.c.material_id == HardwareMaterial.id)
            .where(
                HardwareMaterial.is_deleted.is_(False),
                HardwareMaterial.active.is_(True),
                HardwareMaterial.managed_class == "stocked",
            )
            .order_by(HardwareMaterial.category, HardwareMaterial.name)
        )
    ).all()
    for material, qty in materials:
        db.add(
            HardwareStocktakeItem(
                stocktake_id=take.id,
                material_id=material.id,
                code=material.code,
                name=material.name,
                spec=material.spec,
                unit=material.unit,
                unit_price=material.unit_price,
                book_qty=qty or ZERO,
            )
        )
    await db.flush()
    return take


async def get_stocktake(db: AsyncSession, stocktake_id: UUID) -> HardwareStocktake:
    take = await db.get(HardwareStocktake, stocktake_id)
    if take is None:
        raise hw.HardwareError("盘点单不存在", status_code=404)
    return take


async def list_stocktakes(
    db: AsyncSession,
    *,
    status: str | None = None,
    take_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[HardwareStocktake], int]:
    stmt = select(HardwareStocktake).where(HardwareStocktake.is_deleted.is_(False))
    if status:
        stmt = stmt.where(HardwareStocktake.status == status)
    if take_type:
        stmt = stmt.where(HardwareStocktake.take_type == take_type)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = (
        await db.execute(
            stmt.order_by(HardwareStocktake.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return list(items), int(total or 0)


async def list_stocktake_items(
    db: AsyncSession, stocktake_id: UUID
) -> list[HardwareStocktakeItem]:
    return list(
        (
            await db.execute(
                select(HardwareStocktakeItem)
                .where(
                    HardwareStocktakeItem.stocktake_id == stocktake_id,
                    HardwareStocktakeItem.is_deleted.is_(False),
                )
                .order_by(HardwareStocktakeItem.created_at.asc())
            )
        ).scalars().all()
    )


async def fill_stocktake_item(
    db: AsyncSession,
    stocktake_id: UUID,
    item_id: UUID,
    *,
    actual_qty: Decimal,
    explanation: str | None = None,
) -> HardwareStocktakeItem:
    """实盘直填：填数即算差异；首次实盘把单据推进 counting。"""
    take = await get_stocktake(db, stocktake_id)
    if take.status not in ("draft", "counting"):
        raise hw.HardwareError(
            f"盘点单状态 {take.status} 不可实盘（仅 draft/counting 可填）"
        )
    item = await db.get(HardwareStocktakeItem, item_id)
    if item is None or item.stocktake_id != stocktake_id:
        raise hw.HardwareError("盘点行不存在", status_code=404)
    if actual_qty < ZERO:
        raise hw.HardwareError("实盘数量不可为负", status_code=422)
    item.actual_qty = actual_qty
    item.diff_qty = actual_qty - item.book_qty
    item.diff_amount = (
        (item.unit_price * item.diff_qty) if item.unit_price is not None else None
    )
    if explanation is not None:
        item.explanation = explanation
    if take.status == "draft":
        take.status = "counting"
    await db.flush()
    return item


async def export_stocktake_excel(db: AsyncSession, stocktake_id: UUID) -> bytes:
    """差异表导出 Excel（编码/名称/账存/实存/差异数/差异金额；供财务）。"""
    from openpyxl import Workbook

    take = await get_stocktake(db, stocktake_id)
    items = await list_stocktake_items(db, stocktake_id)

    wb = Workbook()
    ws = wb.active
    ws.title = "盘点差异表"
    ws.append(["物料编码", "物资名称", "账存数量", "实存数量", "差异数量", "差异金额"])
    for i in items:
        ws.append([
            i.code or "",
            i.name,
            float(i.book_qty),
            float(i.actual_qty) if i.actual_qty is not None else None,
            float(i.diff_qty) if i.diff_qty is not None else None,
            float(i.diff_amount) if i.diff_amount is not None else None,
        ])
    ws.append([f"盘点单 {take.take_no}", "", "", "", "", ""])
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


# ── 确认门（Web，人确认才入账；AI 永不自动动账红线）──


async def review_stocktake(
    db: AsyncSession, stocktake_id: UUID, *, explained_by: str, note: str | None = None
) -> HardwareStocktake:
    """counting → reviewed：全行盘完才可复核（差异表口径=全行已盘）。"""
    take = await get_stocktake(db, stocktake_id)
    if take.status != "counting":
        raise hw.HardwareError(f"盘点单状态 {take.status} 不可复核（实盘后才能复核）")
    items = await list_stocktake_items(db, stocktake_id)
    uncounted = [i.name for i in items if i.actual_qty is None]
    if uncounted:
        raise hw.HardwareError(
            f"尚有 {len(uncounted)} 行未盘（如 {uncounted[:3]}），盘完才能复核"
        )
    take.status = "reviewed"
    take.explained_by = explained_by
    take.explained_at = _now()
    if note:
        take.summary_note = note
    await db.flush()
    return take


async def confirm_stocktake(
    db: AsyncSession, stocktake_id: UUID, *, confirmed_by: str
) -> HardwareStocktake:
    """reviewed → confirmed：ADJ 入账唯一动账点（同事务）。

    - 盘盈行：汇总生成「盘点盘盈入库单」（receipt source=stocktake 直接
      accepted，行 remaining=quantity=新批次）+ inbound stocktake_adj 流水；
    - 盘亏行：FIFO 扣批次 remaining + outbound stocktake_adj 流水；
    - 差异行数/金额合计回写单头。
    """
    take = await get_stocktake(db, stocktake_id)
    if take.status != "reviewed":
        raise hw.HardwareError(
            f"盘点单状态 {take.status} 不可确认（差异复核后负责人确认才入账）"
        )
    items = await list_stocktake_items(db, stocktake_id)
    now = _now()

    surplus_receipt: HardwareReceipt | None = None
    surplus_rows: list[HardwareStocktakeItem] = []
    deficit_rows: list[HardwareStocktakeItem] = []
    for item in items:
        if item.diff_qty is None or item.diff_qty == ZERO:
            continue
        if item.diff_qty > ZERO:
            surplus_rows.append(item)
        else:
            deficit_rows.append(item)

    # 盘盈：一张载体单汇总全部盘盈行
    if surplus_rows:
        surplus_receipt = HardwareReceipt(
            receipt_no=await hw.generate_doc_no(db, HardwareReceipt, "WJK-PD"),
            source="stocktake",
            mode="stocked",
            status="accepted",
            arrived_at=now,
            accepted_at=now,
            inspected_by_warehouse=confirmed_by,
            inspected_by_dept=take.explained_by,
            remark=f"盘点盘盈入账：{take.take_no}",
        )
        db.add(surplus_receipt)
        await db.flush()

    for item in surplus_rows:
        material = await db.get(HardwareMaterial, item.material_id)
        row = HardwareReceiptItem(
            receipt_id=surplus_receipt.id,
            material_id=item.material_id,
            name=item.name,
            spec=item.spec,
            unit=item.unit,
            quantity=item.diff_qty,
            remaining_quantity=item.diff_qty,
            unit_price=item.unit_price,
            arrived_at=now,
            match_confidence="manual",
        )
        db.add(row)
        await db.flush()
        row.lot_no = hw.build_lot_no(row.id)
        await hw._write_movement(
            db,
            direction="inbound",
            business_type="stocktake_adj",
            material=material,
            name=item.name,
            spec=item.spec,
            unit=item.unit,
            quantity=item.diff_qty,
            lot=row,
            operator=confirmed_by,
            ref_table="hardware_stocktakes",
            ref_id=take.id,
            remark=f"盘盈入账（{take.take_no}）：{item.explanation or '无说明'}",
        )

    # 盘亏：FIFO 扣批次
    for item in deficit_rows:
        material = await db.get(HardwareMaterial, item.material_id)
        qty = abs(item.diff_qty)
        lots = await hw.get_fifo_lots(db, item.material_id)
        allocs = hw._consume_fifo(lots, qty)
        for lot, take_qty in allocs:
            await hw._write_movement(
                db,
                direction="outbound",
                business_type="stocktake_adj",
                material=material,
                name=item.name,
                spec=item.spec,
                unit=item.unit,
                quantity=take_qty,
                lot=lot,
                operator=confirmed_by,
                ref_table="hardware_stocktakes",
                ref_id=take.id,
                remark=f"盘亏出账（{take.take_no}）：{item.explanation or '无说明'}",
            )

    take.status = "confirmed"
    take.confirmed_by = confirmed_by
    take.confirmed_at = now
    take.diff_surplus_items = len(surplus_rows)
    take.diff_deficit_items = len(deficit_rows)
    take.diff_total_amount = sum(
        (i.diff_amount for i in items if i.diff_amount is not None), Decimal("0"),
    ).quantize(Decimal("0.01"))
    await db.flush()
    return take


async def cancel_stocktake(db: AsyncSession, stocktake_id: UUID) -> HardwareStocktake:
    """confirmed 前作废（不动账）。"""
    take = await get_stocktake(db, stocktake_id)
    if take.status == "confirmed":
        raise hw.HardwareError("已确认入账的盘点单不可作废")
    if take.status == "cancelled":
        raise hw.HardwareError("盘点单已是取消状态")
    take.status = "cancelled"
    take.cancelled_at = _now()
    await db.flush()
    return take


# ── 退库单 ──


def _qty(value: Any) -> Decimal:
    return Decimal(str(value))


async def create_return(
    db: AsyncSession,
    *,
    dept_name: str,
    returned_by: str,
    returned_by_open_id: str | None = None,
    items: list[dict[str, Any]],
    remark: str | None = None,
) -> HardwareReturn:
    """退库草稿：行快照校验（仅 stocked；数量>0）。"""
    rows: list[dict[str, Any]] = []
    for raw in items or []:
        qty = _qty(raw.get("quantity"))
        if qty <= ZERO:
            raise hw.HardwareError("退库数量必须大于 0", status_code=422)
        material = await db.get(HardwareMaterial, UUID(str(raw.get("material_id"))))
        if material is None:
            raise hw.HardwareError(f"物料不存在: {raw.get('material_id')}", status_code=404)
        if material.managed_class != "stocked":
            raise hw.HardwareError(
                f"{material.name} 是车间单独需求类（不占库存），无退库概念"
            )
        rows.append({
            "material_id": str(material.id),
            "code": material.code,
            "name": material.name,
            "spec": material.spec,
            "unit": material.unit,
            "quantity": str(qty),
            "preferred_lot_id": raw.get("preferred_lot_id"),
        })
    if not rows:
        raise hw.HardwareError("退库单无明细行", status_code=422)
    ret = HardwareReturn(
        return_no=await hw.generate_doc_no(
            db, HardwareReturn, "WJK-TK", column=_RETURN_NO_COLUMN
        ),
        dept_name=dept_name,
        returned_by=returned_by,
        returned_by_open_id=returned_by_open_id,
        items=rows,
        status="draft",
        remark=remark,
    )
    db.add(ret)
    await db.flush()
    return ret


async def _load_return(db: AsyncSession, return_id: UUID) -> HardwareReturn:
    ret = await db.get(HardwareReturn, return_id)
    if ret is None:
        raise hw.HardwareError("退库单不存在", status_code=404)
    return ret


async def get_return(db: AsyncSession, return_id: UUID) -> HardwareReturn:
    return await _load_return(db, return_id)


async def list_returns(
    db: AsyncSession,
    *,
    status: str | None = None,
    dept_name: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[HardwareReturn], int]:
    stmt = select(HardwareReturn).where(HardwareReturn.is_deleted.is_(False))
    if status:
        stmt = stmt.where(HardwareReturn.status == status)
    if dept_name:
        stmt = stmt.where(HardwareReturn.dept_name == dept_name)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        await db.execute(
            stmt.order_by(HardwareReturn.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return list(rows), int(total or 0)


async def sign_return(
    db: AsyncSession, return_id: UUID, *, leader: str
) -> HardwareReturn:
    """draft 阶段部门负责人签收（验收前置）。"""
    ret = await _load_return(db, return_id)
    if ret.status != "draft":
        raise hw.HardwareError(f"退库单状态 {ret.status} 不可签收")
    ret.leader_signed = True
    ret.leader_signed_by = leader
    ret.leader_signed_at = _now()
    await db.flush()
    return ret


async def _return_carrier_receipt(
    db: AsyncSession, ret: HardwareReturn, now: datetime
) -> HardwareReceipt:
    """退库回加载体单（source=return，一单多行，直接 accepted）。"""
    receipt = HardwareReceipt(
        receipt_no=await hw.generate_doc_no(db, HardwareReceipt, "WJK-TK"),
        source="return",
        mode="stocked",
        status="accepted",
        arrived_at=now,
        accepted_at=now,
        inspected_by_warehouse=ret.accepted_by or "仓管员",
        remark=f"退库回加：{ret.return_no}",
    )
    db.add(receipt)
    await db.flush()
    return receipt


async def accept_return(
    db: AsyncSession, return_id: UUID, *, accepted_by: str
) -> HardwareReturn:
    """仓管员验收：批次回加（优先回原 lot；原 lot 无效则新建 return 批次）。"""
    ret = await _load_return(db, return_id)
    if ret.status != "draft":
        raise hw.HardwareError(f"退库单状态 {ret.status} 不可验收")
    if not ret.leader_signed:
        raise hw.HardwareError("部门负责人未签收，不可验收")
    now = _now()
    ret.accepted_by = accepted_by
    carrier: HardwareReceipt | None = None
    adjustments: list[dict[str, Any]] = []

    for row in ret.items:
        material = await db.get(HardwareMaterial, UUID(row["material_id"]))
        qty = _qty(row["quantity"])
        preferred = row.get("preferred_lot_id")
        lot: HardwareReceiptItem | None = None
        if preferred:
            candidate = await db.get(HardwareReceiptItem, UUID(str(preferred)))
            parent = await db.get(HardwareReceipt, candidate.receipt_id) if candidate else None
            if (
                candidate is not None
                and not candidate.is_deleted
                and parent is not None
                and parent.status == "accepted"
                and candidate.material_id == material.id
                and candidate.remaining_quantity is not None
            ):
                lot = candidate
        if lot is not None:
            lot.remaining_quantity = (lot.remaining_quantity or ZERO) + qty
            mode = "preferred"
        else:
            if carrier is None:
                carrier = await _return_carrier_receipt(db, ret, now)
            lot = HardwareReceiptItem(
                receipt_id=carrier.id,
                material_id=material.id,
                name=row["name"],
                spec=row["spec"],
                unit=row["unit"],
                quantity=qty,
                remaining_quantity=qty,
                arrived_at=now,
                match_confidence="manual",
            )
            db.add(lot)
            await db.flush()
            lot.lot_no = hw.build_lot_no(lot.id)
            mode = "new"
        await hw._write_movement(
            db,
            direction="inbound",
            business_type="return_in",
            material=material,
            name=row["name"],
            spec=row["spec"],
            unit=row["unit"],
            quantity=qty,
            lot=lot,
            operator=accepted_by,
            dept_name=ret.dept_name,
            ref_table="hardware_returns",
            ref_id=ret.id,
        )
        adjustments.append({
            "material": row["name"],
            "material_id": row["material_id"],
            "lot_no": lot.lot_no,
            "mode": mode,
            "qty": float(qty),
            **({"carrier_receipt_id": str(carrier.id)} if mode == "new" else {}),
        })

    ret.status = "accepted"
    ret.accepted_at = now
    ret.lot_adjustments = adjustments
    await db.flush()
    return ret


async def reject_return(
    db: AsyncSession, return_id: UUID, *, reason: str
) -> HardwareReturn:
    """不合格拒退：留证不动账（无批次回加、无流水）。"""
    ret = await _load_return(db, return_id)
    if ret.status != "draft":
        raise hw.HardwareError(f"退库单状态 {ret.status} 不可拒退")
    ret.status = "rejected"
    ret.rejected_reason = reason
    await db.flush()
    return ret
