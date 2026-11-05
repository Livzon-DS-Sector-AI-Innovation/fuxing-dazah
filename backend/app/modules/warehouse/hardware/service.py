"""五金库库存引擎与单据 service（设计 §三/§四）。

库存口径（收口原则：无单据不动账）：

    on_hand(m)   = Σ receipt_items.remaining_quantity（accepted 入库批次）
    reserved(m)  = Σ requisition_items.need_qty  WHERE 单头 status ∈ (pending, approved)
    available(m) = on_hand − reserved
    预警          = available < safety_stock

- 预扣=纯状态占用（reserved 由状态派生），驳回/取消即释放；
- 实扣=发料时按 FIFO（arrived_at 升序）扣批次 remaining_quantity，
  逐批写 movements（quantity 恒正 + direction 表方向）；
- 入库 accepted：stocked 生成批次占库存；direct 出入双流水净零不占库存。
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.hardware.models import (
    DEMAND_DEPARTMENTS,
    HardwareLocation,
    HardwareMaterial,
    HardwareMovement,
    HardwareReceipt,
    HardwareReceiptItem,
    HardwareRequisition,
    HardwareRequisitionItem,
)
from app.modules.warehouse.hardware.schemas import (
    ReceiptCreate,
    ReceiptItemIn,
    RequisitionCreate,
)
from app.platform.identity.models import User

logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")
ZERO = Decimal("0")

# 预扣占用状态（reserved 口径）
RESERVING_STATUSES = ("pending", "approved")

_DOC_PREFIX = {
    HardwareReceipt: "WJK-RK",
    HardwareRequisition: "WJK-LY",
    HardwareMovement: "WJK-MV",
}


def _now() -> datetime:
    return datetime.now(CN_TZ)


class HardwareError(HTTPException):
    """业务校验失败（409/422 语义，走 HTTPException 便于 API 层直通）。"""

    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.message = message


# ── 单号：WJK-XX-YYMMDD-NNN 计数式 ──


async def generate_doc_no(
    db: AsyncSession, model: type, prefix: str, *, column: Any = None
) -> str:
    """按当日同前缀计数生成连续单号（仿 safety _gen_hazard_no 模式）。

    column 缺省按模型三分支（一期三表）；二期表显式传列（如
    HardwareStocktake.take_no / HardwareReturn.return_no）。
    """
    if column is None:
        column = (
            model.receipt_no
            if model is HardwareReceipt
            else model.req_no
            if model is HardwareRequisition
            else model.movement_no
        )
    head = f"{prefix}-{_now().strftime('%y%m%d')}-"
    count = await db.scalar(
        select(func.count()).select_from(model).where(column.like(f"{head}%"))
    )
    return f"{head}{(count or 0) + 1:03d}"


def build_lot_no(item_id: UUID) -> str:
    """批次号=入库明细行 id 派生（设计 §2.3：lot_no=本行 id 生成）。"""
    return f"LOT{item_id.hex[:10].upper()}"


# ── 库存口径查询 ──


def _on_hand_subquery():
    return (
        select(
            HardwareReceiptItem.material_id.label("material_id"),
            func.sum(HardwareReceiptItem.remaining_quantity).label("on_hand"),
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


def _reserved_subquery():
    return (
        select(
            HardwareRequisitionItem.material_id.label("material_id"),
            func.sum(HardwareRequisitionItem.need_qty).label("reserved"),
        )
        .join(
            HardwareRequisition,
            HardwareRequisition.id == HardwareRequisitionItem.requisition_id,
        )
        .where(
            HardwareRequisition.status.in_(RESERVING_STATUSES),
            HardwareRequisition.is_deleted.is_(False),
            HardwareRequisitionItem.is_deleted.is_(False),
        )
        .group_by(HardwareRequisitionItem.material_id)
        .subquery()
    )


async def list_stock_rows(
    db: AsyncSession,
    *,
    keyword: str | None = None,
    category: str | None = None,
    managed_class: str | None = "stocked",
    low_only: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """库存总览分页：materials × (on_hand/reserved/available/is_low/low_gap)。"""
    on_hand = _on_hand_subquery()
    reserved = _reserved_subquery()
    stmt = (
        select(
            HardwareMaterial,
            func.coalesce(on_hand.c.on_hand, ZERO).label("on_hand"),
            func.coalesce(reserved.c.reserved, ZERO).label("reserved"),
        )
        .outerjoin(on_hand, on_hand.c.material_id == HardwareMaterial.id)
        .outerjoin(reserved, reserved.c.material_id == HardwareMaterial.id)
        .where(HardwareMaterial.is_deleted.is_(False), HardwareMaterial.active.is_(True))
    )
    if managed_class:
        stmt = stmt.where(HardwareMaterial.managed_class == managed_class)
    if category:
        stmt = stmt.where(HardwareMaterial.category == category)
    if keyword:
        kw = f"%{keyword.strip()}%"
        stmt = stmt.where(
            HardwareMaterial.name.ilike(kw)
            | HardwareMaterial.spec.ilike(kw)
            | func.coalesce(HardwareMaterial.code, "").ilike(kw)
        )
    if low_only:
        # available < safety_stock（负 coalesce 前需表达式过滤）
        avail = func.coalesce(on_hand.c.on_hand, ZERO) - func.coalesce(reserved.c.reserved, ZERO)
        stmt = stmt.where(avail < HardwareMaterial.safety_stock)

    total = await db.scalar(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    )
    rows = (
        await db.execute(
            stmt.order_by(HardwareMaterial.category, HardwareMaterial.name)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    data = []
    for material, on, res in rows:
        available = (on or ZERO) - (res or ZERO)
        gap = material.safety_stock - available
        data.append(
            {
                "material": material,
                "on_hand": on or ZERO,
                "reserved": res or ZERO,
                "available": available,
                "is_low": available < material.safety_stock,
                "low_gap": gap if gap > ZERO else ZERO,
            }
        )
    return data, int(total or 0)


async def get_material_stock(db: AsyncSession, material_id: UUID) -> dict[str, Any]:
    """单物料库存详情：口径行 + 批次（FIFO 序）+ 近流水。"""
    on_hand = _on_hand_subquery()
    reserved = _reserved_subquery()
    row = (
        await db.execute(
            select(
                HardwareMaterial,
                func.coalesce(on_hand.c.on_hand, ZERO),
                func.coalesce(reserved.c.reserved, ZERO),
            )
            .outerjoin(on_hand, on_hand.c.material_id == HardwareMaterial.id)
            .outerjoin(reserved, reserved.c.material_id == HardwareMaterial.id)
            .where(HardwareMaterial.id == material_id)
        )
    ).first()
    if row is None:
        raise HardwareError("物料不存在", status_code=404)
    material, on, res = row
    available = (on or ZERO) - (res or ZERO)
    gap = material.safety_stock - available

    lots = (
        await db.execute(
            select(HardwareReceiptItem, HardwareLocation.code, HardwareReceipt.receipt_no)
            .join(HardwareReceipt, HardwareReceipt.id == HardwareReceiptItem.receipt_id)
            .outerjoin(HardwareLocation, HardwareLocation.id == HardwareReceiptItem.location_id)
            .where(
                HardwareReceiptItem.material_id == material_id,
                HardwareReceipt.status == "accepted",
                HardwareReceiptItem.is_deleted.is_(False),
            )
            .order_by(HardwareReceiptItem.arrived_at.asc(), HardwareReceiptItem.created_at.asc())
        )
    ).all()
    movements = (
        await db.execute(
            select(HardwareMovement)
            .where(HardwareMovement.material_id == material_id)
            .order_by(HardwareMovement.occurred_at.desc())
            .limit(20)
        )
    ).scalars().all()

    return {
        "material": material,
        "on_hand": on or ZERO,
        "reserved": res or ZERO,
        "available": available,
        "is_low": available < material.safety_stock,
        "low_gap": gap if gap > ZERO else ZERO,
        "lots": [
            {
                "lot_id": item.id,
                "lot_no": item.lot_no,
                "receipt_no": receipt_no,
                "arrived_at": item.arrived_at,
                "expiry_date": item.expiry_date,
                "location_code": loc_code,
                "remaining_quantity": item.remaining_quantity or ZERO,
                "quantity": item.quantity,
            }
            for item, loc_code, receipt_no in lots
        ],
        "recent_movements": list(movements),
    }


async def list_materials(
    db: AsyncSession,
    *,
    keyword: str | None = None,
    category: str | None = None,
    managed_class: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[HardwareMaterial], int]:
    stmt = select(HardwareMaterial).where(
        HardwareMaterial.is_deleted.is_(False), HardwareMaterial.active.is_(True)
    )
    if managed_class:
        stmt = stmt.where(HardwareMaterial.managed_class == managed_class)
    if category:
        stmt = stmt.where(HardwareMaterial.category == category)
    if keyword:
        kw = f"%{keyword.strip()}%"
        stmt = stmt.where(
            HardwareMaterial.name.ilike(kw)
            | HardwareMaterial.spec.ilike(kw)
            | func.coalesce(HardwareMaterial.code, "").ilike(kw)
        )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = (
        await db.execute(
            stmt.order_by(HardwareMaterial.category, HardwareMaterial.name)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return list(items), int(total or 0)


# ── FIFO ──


async def get_fifo_lots(db: AsyncSession, material_id: UUID) -> list[HardwareReceiptItem]:
    """FIFO 批次序列：arrived_at 升序（临近效期优先），仅 remaining>0。"""
    return list(
        (
            await db.execute(
                select(HardwareReceiptItem)
                .join(HardwareReceipt, HardwareReceipt.id == HardwareReceiptItem.receipt_id)
                .where(
                    HardwareReceiptItem.material_id == material_id,
                    HardwareReceipt.status == "accepted",
                    HardwareReceiptItem.is_deleted.is_(False),
                    HardwareReceiptItem.remaining_quantity > ZERO,
                )
                .order_by(HardwareReceiptItem.arrived_at.asc(), HardwareReceiptItem.created_at.asc())
            )
        ).scalars().all()
    )


async def suggest_fifo_allocation(
    db: AsyncSession, material_id: UUID, qty: Decimal
) -> list[dict[str, Any]]:
    """发料建议（不动账）：按 FIFO 逐批分配，输出 [{lot_no, location_id, available, allocate}]。"""
    lots = await get_fifo_lots(db, material_id)
    remain = qty
    plan: list[dict[str, Any]] = []
    for lot in lots:
        if remain <= ZERO:
            break
        take = min(lot.remaining_quantity or ZERO, remain)
        plan.append(
            {
                "lot_id": str(lot.id),
                "lot_no": lot.lot_no,
                "location_id": str(lot.location_id) if lot.location_id else None,
                "available": lot.remaining_quantity or ZERO,
                "allocate": take,
            }
        )
        remain -= take
    if remain > ZERO:
        plan.append({"shortage": remain, "message": "批次余额不足，缺口见 shortage"})
    return plan


def _consume_fifo(
    lots: list[HardwareReceiptItem], qty: Decimal
) -> list[tuple[HardwareReceiptItem, Decimal]]:
    """在已取出的批次序列上按序扣减（同事务内已锁行），返回 [(lot, take)]。"""
    remain = qty
    allocs: list[tuple[HardwareReceiptItem, Decimal]] = []
    for lot in lots:
        if remain <= ZERO:
            break
        take = min(lot.remaining_quantity or ZERO, remain)
        if take <= ZERO:
            continue
        lot.remaining_quantity = (lot.remaining_quantity or ZERO) - take
        allocs.append((lot, take))
        remain -= take
    if remain > ZERO:
        raise HardwareError(f"批次余额不足，缺口 {remain.normalize()}")
    return allocs


# ── movements 写入 ──


async def _write_movement(
    db: AsyncSession,
    *,
    direction: str,
    business_type: str,
    material: HardwareMaterial | None,
    name: str,
    spec: str | None,
    unit: str | None,
    quantity: Decimal,
    lot: HardwareReceiptItem | None = None,
    operator: str | None = None,
    dept_name: str | None = None,
    ref_table: str | None = None,
    ref_id: UUID | None = None,
    remark: str | None = None,
) -> HardwareMovement:
    mv = HardwareMovement(
        movement_no=await generate_doc_no(db, HardwareMovement, "WJK-MV"),
        direction=direction,
        business_type=business_type,
        material_id=material.id if material else None,
        material_name=name,
        spec=spec,
        unit=unit,
        lot_id=lot.id if lot else None,
        lot_no=lot.lot_no if lot else None,
        quantity=quantity,
        occurred_at=_now(),
        operator=operator,
        dept_name=dept_name,
        ref_table=ref_table,
        ref_id=ref_id,
        remark=remark,
    )
    db.add(mv)
    return mv


# ── 入库单 ──


async def create_receipt(
    db: AsyncSession, payload: ReceiptCreate, *, user: User | None = None
) -> HardwareReceipt:
    """入库草稿：OCR/manual 共用；只建 draft，不动库存（AI 永不自动动账红线）。"""
    arrived = payload.arrived_at or _now()
    receipt = HardwareReceipt(
        receipt_no=await generate_doc_no(db, HardwareReceipt, "WJK-RK"),
        source=payload.source,
        erp_doc_no=payload.erp_doc_no,
        supplier_name=payload.supplier_name,
        delivery_note_no=payload.delivery_note_no,
        arrived_at=arrived,
        target_dept=payload.target_dept,
        mode=payload.mode,
        status="draft",
        attachments=payload.attachments,
        remark=payload.remark,
        created_by=user.id if user else None,
    )
    db.add(receipt)
    await db.flush()  # 拿 receipt.id

    for item in payload.items:
        material = None
        if item.material_id:
            material = await db.get(HardwareMaterial, UUID(item.material_id))
            if material is None:
                raise HardwareError(f"物料不存在: {item.material_id}", status_code=404)
        db.add(
            HardwareReceiptItem(
                receipt_id=receipt.id,
                material_id=material.id if material else None,
                name=item.name,
                spec=item.spec or (material.spec if material else None),
                unit=item.unit or (material.unit if material else None),
                quantity=item.quantity,
                location_id=UUID(item.location_id) if item.location_id else None,
                expiry_date=item.expiry_date,
                match_confidence=item.match_confidence,
                match_score=item.match_score,
                unit_price=item.unit_price,
                arrived_at=arrived,
            )
        )
    await db.flush()
    return receipt


async def _load_receipt(db: AsyncSession, receipt_id: UUID) -> HardwareReceipt:
    receipt = await db.get(HardwareReceipt, receipt_id)
    if receipt is None:
        raise HardwareError("入库单不存在", status_code=404)
    return receipt


async def get_receipt(db: AsyncSession, receipt_id: UUID) -> HardwareReceipt:
    return await _load_receipt(db, receipt_id)


async def list_receipts(
    db: AsyncSession,
    *,
    status: str | None = None,
    source: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[HardwareReceipt], int]:
    stmt = select(HardwareReceipt).where(HardwareReceipt.is_deleted.is_(False))
    if status:
        stmt = stmt.where(HardwareReceipt.status == status)
    if source:
        stmt = stmt.where(HardwareReceipt.source == source)
    if keyword:
        kw = f"%{keyword.strip()}%"
        stmt = stmt.where(
            HardwareReceipt.receipt_no.ilike(kw)
            | func.coalesce(HardwareReceipt.supplier_name, "").ilike(kw)
            | func.coalesce(HardwareReceipt.delivery_note_no, "").ilike(kw)
        )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = (
        await db.execute(
            stmt.order_by(HardwareReceipt.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return list(items), int(total or 0)


async def list_receipt_items(
    db: AsyncSession, receipt_id: UUID
) -> list[HardwareReceiptItem]:
    return list(
        (
            await db.execute(
                select(HardwareReceiptItem)
                .where(
                    HardwareReceiptItem.receipt_id == receipt_id,
                    HardwareReceiptItem.is_deleted.is_(False),
                )
                .order_by(HardwareReceiptItem.created_at.asc())
            )
        ).scalars().all()
    )


async def accept_receipt(
    db: AsyncSession,
    receipt_id: UUID,
    *,
    inspected_by_warehouse: str,
    inspected_by_dept: str,
    inspect_checklist: dict[str, Any] | None = None,
    items: list[ReceiptItemIn] | None = None,
    user: User | None = None,
    allow_unmatched: bool = False,
) -> HardwareReceipt:
    """draft → accepted：库存唯一增点。

    行级判定（两类边界=物资清单）：挂 stocked 物料的行生成批次
    （remaining=quantity）+ inbound 流水；无主数据/direct 物料行出入双流水
    净零直发 target_dept。mode=stocked 的单出现无主数据行时默认阻断
    （allow_unmatched=False），人工逐行指定或改 direct 单。
    行级人工修正（低置信标黄改后）以 items 覆盖草稿原行。
    """
    receipt = await _load_receipt(db, receipt_id)
    if receipt.status != "draft":
        raise HardwareError(f"入库单状态 {receipt.status} 不可确认（仅 draft 可确认入账）")

    # 人工修正：删除草稿行重建
    if items is not None:
        for old in await list_receipt_items(db, receipt_id):
            await db.delete(old)
        await db.flush()
        for item in items:
            material = None
            if item.material_id:
                material = await db.get(HardwareMaterial, UUID(item.material_id))
            db.add(
                HardwareReceiptItem(
                    receipt_id=receipt.id,
                    material_id=material.id if material else None,
                    name=item.name,
                    spec=item.spec or (material.spec if material else None),
                    unit=item.unit or (material.unit if material else None),
                    quantity=item.quantity,
                    location_id=UUID(item.location_id) if item.location_id else None,
                    expiry_date=item.expiry_date,
                    match_confidence=item.match_confidence or "manual",
                    match_score=item.match_score,
                    unit_price=item.unit_price,
                    arrived_at=receipt.arrived_at,
                )
            )
        await db.flush()

    rows = await list_receipt_items(db, receipt_id)
    if not rows:
        raise HardwareError("入库单无明细行")

    operator = user.display_name if user and hasattr(user, "display_name") else inspected_by_warehouse

    for row in rows:
        material = await db.get(HardwareMaterial, row.material_id) if row.material_id else None
        # 行级判定（两类边界=物资清单本身）：行挂 stocked 物料=批次占库存；
        # 无主数据/挂 direct 物料=出入双流水净零直发 target_dept。
        is_stocked_row = material is not None and material.managed_class == "stocked"
        if is_stocked_row:
            row.remaining_quantity = row.quantity
            row.lot_no = build_lot_no(row.id)
            await _write_movement(
                db,
                direction="inbound",
                business_type="receipt",
                material=material,
                name=row.name,
                spec=row.spec,
                unit=row.unit,
                quantity=row.quantity,
                lot=row,
                operator=operator,
                dept_name=None,
                ref_table="hardware_receipts",
                ref_id=receipt.id,
            )
            # 最近入库单价回写主数据
            if row.unit_price is not None:
                material.unit_price = row.unit_price
        else:
            if material is None and receipt.mode == "stocked" and not allow_unmatched:
                raise HardwareError(
                    f"共用类行必须匹配主数据：{row.name}（请人工指定物料，或整单按车间单独需求登记）"
                )
            # direct：出入双流水净零，直发 target_dept，不占库存
            dept = receipt.target_dept
            await _write_movement(
                db,
                direction="inbound",
                business_type="pass_in",
                material=material,
                name=row.name,
                spec=row.spec,
                unit=row.unit,
                quantity=row.quantity,
                operator=operator,
                dept_name=dept,
                ref_table="hardware_receipts",
                ref_id=receipt.id,
            )
            await _write_movement(
                db,
                direction="outbound",
                business_type="pass_out",
                material=material,
                name=row.name,
                spec=row.spec,
                unit=row.unit,
                quantity=row.quantity,
                operator=operator,
                dept_name=dept,
                ref_table="hardware_receipts",
                ref_id=receipt.id,
            )
            if row.unit_price is not None and material is not None:
                material.unit_price = row.unit_price

    receipt.status = "accepted"
    receipt.inspected_by_warehouse = inspected_by_warehouse
    receipt.inspected_by_dept = inspected_by_dept
    receipt.inspect_checklist = inspect_checklist
    receipt.accepted_at = _now()
    if user:
        receipt.updated_by = user.id
    await db.flush()
    await _fire_direct_pickup(db, receipt, rows)
    return receipt


async def _fire_direct_pickup(
    db: AsyncSession, receipt: HardwareReceipt, rows: list[HardwareReceiptItem]
) -> None:
    """direct 行确认入账 → 推办事员领取卡（失败不影响主业务，设计 §9.5）。"""
    direct_rows = [r for r in rows if not r.lot_no]  # 未生成批次=direct 行
    if not direct_rows or not receipt.target_dept:
        return
    try:
        from app.modules.warehouse.push_center.events import fire_push_event

        await fire_push_event(
            db,
            "hardware_direct_pickup",
            {
                "dept": receipt.target_dept,
                "supplier": receipt.supplier_name,
                "receipt_no": receipt.receipt_no,
                "rows": [
                    {"name": r.name, "spec": r.spec, "quantity": float(r.quantity), "unit": r.unit}
                    for r in direct_rows
                ],
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception("direct 领取卡推送失败（不影响入账主流程）")


async def reject_receipt(
    db: AsyncSession,
    receipt_id: UUID,
    *,
    reason: str,
    user: User | None = None,
) -> HardwareReceipt:
    """draft → rejected：拒收退供应商（留证+通知采购走 push，不动库存）。"""
    receipt = await _load_receipt(db, receipt_id)
    if receipt.status != "draft":
        raise HardwareError(f"入库单状态 {receipt.status} 不可拒收（仅 draft 可拒收）")
    receipt.status = "rejected"
    receipt.rejected_reason = reason
    if user:
        receipt.updated_by = user.id
    await db.flush()
    return receipt


# ── 领用申请（M3 状态机；M1 先落核心供单测）──


async def create_requisition(
    db: AsyncSession, payload: RequisitionCreate, *, user: User | None = None
) -> HardwareRequisition:
    req = HardwareRequisition(
        req_no=await generate_doc_no(db, HardwareRequisition, "WJK-LY"),
        dept_name=payload.dept_name,
        applicant=payload.applicant,
        applicant_open_id=payload.applicant_open_id,
        applicant_user_id=user.id if user else None,
        purpose=payload.purpose,
        req_type=payload.req_type,
        status="draft",
        remark=payload.remark,
        created_by=user.id if user else None,
    )
    db.add(req)
    await db.flush()
    for item in payload.items:
        material = await db.get(HardwareMaterial, UUID(item.material_id))
        if material is None:
            raise HardwareError(f"物料不存在: {item.material_id}", status_code=404)
        if material.managed_class != "stocked":
            raise HardwareError(
                f"{material.name} 是车间单独需求类（不占库存），无需领料审批，到货直接领取"
            )
        db.add(
            HardwareRequisitionItem(
                requisition_id=req.id,
                material_id=material.id,
                need_qty=item.need_qty,
            )
        )
    await db.flush()
    return req


async def _load_requisition(
    db: AsyncSession, requisition_id: UUID
) -> HardwareRequisition:
    req = await db.get(HardwareRequisition, requisition_id)
    if req is None:
        raise HardwareError("领用申请不存在", status_code=404)
    return req


async def get_requisition(
    db: AsyncSession, requisition_id: UUID
) -> HardwareRequisition:
    return await _load_requisition(db, requisition_id)


async def list_requisitions(
    db: AsyncSession,
    *,
    status: str | None = None,
    dept_name: str | None = None,
    req_type: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[HardwareRequisition], int]:
    stmt = select(HardwareRequisition).where(HardwareRequisition.is_deleted.is_(False))
    if status:
        stmt = stmt.where(HardwareRequisition.status == status)
    if dept_name:
        stmt = stmt.where(HardwareRequisition.dept_name == dept_name)
    if req_type:
        stmt = stmt.where(HardwareRequisition.req_type == req_type)
    if keyword:
        kw = f"%{keyword.strip()}%"
        stmt = stmt.where(
            HardwareRequisition.req_no.ilike(kw)
            | HardwareRequisition.applicant.ilike(kw)
        )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = (
        await db.execute(
            stmt.order_by(HardwareRequisition.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return list(items), int(total or 0)


async def list_requisition_items(
    db: AsyncSession, requisition_id: UUID
) -> list[HardwareRequisitionItem]:
    return list(
        (
            await db.execute(
                select(HardwareRequisitionItem)
                .where(
                    HardwareRequisitionItem.requisition_id == requisition_id,
                    HardwareRequisitionItem.is_deleted.is_(False),
                )
                .order_by(HardwareRequisitionItem.created_at.asc())
            )
        ).scalars().all()
    )


async def _available_of(db: AsyncSession, material_id: UUID) -> Decimal:
    on_hand = await db.scalar(
        select(func.coalesce(
            select(func.sum(HardwareReceiptItem.remaining_quantity))
            .select_from(HardwareReceiptItem)
            .join(HardwareReceipt, HardwareReceipt.id == HardwareReceiptItem.receipt_id)
            .where(
                HardwareReceiptItem.material_id == material_id,
                HardwareReceipt.status == "accepted",
                HardwareReceipt.is_deleted.is_(False),
                HardwareReceiptItem.is_deleted.is_(False),
            )
            .scalar_subquery(),
            ZERO,
        ))
    )
    reserved = await db.scalar(
        select(func.coalesce(
            select(func.sum(HardwareRequisitionItem.need_qty))
            .select_from(HardwareRequisitionItem)
            .join(
                HardwareRequisition,
                HardwareRequisition.id == HardwareRequisitionItem.requisition_id,
            )
            .where(
                HardwareRequisitionItem.material_id == material_id,
                HardwareRequisition.status.in_(RESERVING_STATUSES),
                HardwareRequisition.is_deleted.is_(False),
                HardwareRequisitionItem.is_deleted.is_(False),
            )
            .scalar_subquery(),
            ZERO,
        ))
    )
    return (on_hand or ZERO) - (reserved or ZERO)


async def submit_requisition(
    db: AsyncSession, requisition_id: UUID, *, user: User | None = None
) -> HardwareRequisition:
    """draft → pending：提交即预扣（available 校验，防超卖）。"""
    req = await _load_requisition(db, requisition_id)
    if req.status != "draft":
        raise HardwareError(f"申请状态 {req.status} 不可提交（仅 draft 可提交）")
    items = await list_requisition_items(db, requisition_id)
    if not items:
        raise HardwareError("申请无明细行")
    # 逐物料校验可用量（同单同物料合并校验）
    need_by_material: dict[UUID, Decimal] = {}
    for item in items:
        need_by_material[item.material_id] = (
            need_by_material.get(item.material_id, ZERO) + item.need_qty
        )
    for material_id, need in need_by_material.items():
        available = await _available_of(db, material_id)
        if available < need:
            material = await db.get(HardwareMaterial, material_id)
            name = material.name if material else str(material_id)
            raise HardwareError(
                f"{name} 可用量不足：可用 {available.normalize()}，需求 {need.normalize()}"
            )
    req.status = "pending"
    req.submitted_at = _now()
    # 月度核对快照：当月已领 vs 月需求（领用标准数据支撑，设计 §2.4）
    req.monthly_check = await build_monthly_check(db, req.dept_name, need_by_material)
    if user:
        req.updated_by = user.id
    await db.flush()
    return req


async def build_monthly_check(
    db: AsyncSession, dept_name: str, need_by_material: dict[UUID, Decimal]
) -> dict[str, Any]:
    """该部门当月已领量 vs 月需求快照（仓管员核对领用标准支撑）。"""
    month_start = _now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows: dict[str, Any] = {"dept": dept_name, "month": month_start.strftime("%Y-%m"), "items": []}
    for material_id in need_by_material:
        material = await db.get(HardwareMaterial, material_id)
        if material is None:
            continue
        issued = await db.scalar(
            select(func.coalesce(func.sum(HardwareMovement.quantity), ZERO)).where(
                HardwareMovement.material_id == material_id,
                HardwareMovement.direction == "outbound",
                HardwareMovement.business_type.in_(("req_issue", "urgent_issue")),
                HardwareMovement.dept_name == dept_name,
                HardwareMovement.occurred_at >= month_start,
            )
        )
        demand = None
        if material.monthly_demands:
            demand = material.monthly_demands.get(
                _match_demand_dept(material.monthly_demands, dept_name)
            )
        rows["items"].append(
            {
                "material": material.name,
                "month_issued": float(issued or ZERO),
                "monthly_demand": float(demand) if demand is not None else None,
            }
        )
    return rows


def _match_demand_dept(demands: dict[str, Any], dept_name: str) -> str:
    """部门名→月需求键（完全匹配优先，包含匹配兜底）。"""
    if dept_name in demands:
        return dept_name
    for key in demands:
        if key and (key in dept_name or dept_name in key):
            return key
    return dept_name


async def approve_requisition(
    db: AsyncSession,
    requisition_id: UUID,
    *,
    approver: str,
    note: str | None = None,
    user: User | None = None,
) -> HardwareRequisition:
    """pending → approved（预扣保持；超额在审批环节提示需生产总监，manual 通道落备注）。

    紧急单先发后补：status=issued 的 urgent 单补审批只落审批结果与
    patched_at（status 保持 issued，不回退状态机）。
    """
    req = await _load_requisition(db, requisition_id)
    if req.status == "issued" and req.req_type == "urgent":
        req.approval_status = "approved"
        req.approved_by = approver
        req.approved_at = _now()
        req.patched_at = _now()
        if note:
            req.approval_note = note
        if user:
            req.updated_by = user.id
        await db.flush()
        return req
    if req.status != "pending":
        raise HardwareError(f"申请状态 {req.status} 不可审批（仅 pending 可审批）")
    req.status = "approved"
    req.approval_status = "approved"
    req.approved_by = approver
    req.approved_at = _now()
    if note:
        req.approval_note = note
    # 紧急单补审批闭合
    if req.req_type == "urgent" and req.issued_at is not None:
        req.patched_at = _now()
    if user:
        req.updated_by = user.id
    await db.flush()
    return req


async def reject_requisition(
    db: AsyncSession,
    requisition_id: UUID,
    *,
    approver: str,
    reason: str,
    user: User | None = None,
) -> HardwareRequisition:
    """pending → rejected：释放预扣（reserved 状态派生，随状态变更自动释放）。"""
    req = await _load_requisition(db, requisition_id)
    if req.status != "pending":
        raise HardwareError(f"申请状态 {req.status} 不可驳回（仅 pending 可驳回）")
    req.status = "rejected"
    req.approval_status = "rejected"
    req.approved_by = approver
    req.approved_at = _now()
    req.rejected_reason = reason
    if user:
        req.updated_by = user.id
    await db.flush()
    return req


async def cancel_requisition(
    db: AsyncSession, requisition_id: UUID, *, user: User | None = None
) -> HardwareRequisition:
    """draft/pending → cancelled：pending 取消即释放预扣。"""
    req = await _load_requisition(db, requisition_id)
    if req.status not in ("draft", "pending"):
        raise HardwareError(f"申请状态 {req.status} 不可取消")
    req.status = "cancelled"
    if user:
        req.updated_by = user.id
    await db.flush()
    return req


async def issue_requisition(
    db: AsyncSession,
    requisition_id: UUID,
    *,
    issued_by: str,
    received_by: str,
    items: list[dict[str, Any]] | None = None,
    user: User | None = None,
) -> HardwareRequisition:
    """发料实扣：库存唯一减点。

    - normal/excess：approved → issued；urgent：pending 也可直接发（先发后补）
    - 每行 issued_qty（缺省=need_qty）按 FIFO 扣批次 remaining，逐批写流水
    - 领用人点收 received_by=系统签收；urgent 设补单截止 +24h
    """
    req = await _load_requisition(db, requisition_id)
    if req.status not in ("approved", "pending"):
        raise HardwareError(f"申请状态 {req.status} 不可发料")
    if req.status == "pending" and req.req_type != "urgent":
        raise HardwareError("非紧急申请须审批通过后才能发料")

    issued_map: dict[UUID, Decimal] = {}
    if items:
        for it in items:
            issued_map[UUID(str(it.get("item_id")))] = Decimal(str(it.get("issued_qty")))

    rows = await list_requisition_items(db, requisition_id)
    if not rows:
        raise HardwareError("申请无明细行")
    operator = user.display_name if user and hasattr(user, "display_name") else issued_by
    now = _now()

    for row in rows:
        material = await db.get(HardwareMaterial, row.material_id)
        if material is None:
            raise HardwareError("领料行物料不存在", status_code=404)
        qty = issued_map.get(row.id, row.need_qty)
        if qty <= ZERO:
            raise HardwareError("实发量必须大于 0")
        lots = await get_fifo_lots(db, row.material_id)
        allocs = _consume_fifo(lots, qty)
        row.issued_qty = qty
        row.fifo_lot_allocations = [
            {
                "lot_id": str(lot.id),
                "lot_no": lot.lot_no,
                "location_id": str(lot.location_id) if lot.location_id else None,
                "qty": float(take),
            }
            for lot, take in allocs
        ]
        for lot, take in allocs:
            await _write_movement(
                db,
                direction="outbound",
                business_type="urgent_issue" if req.req_type == "urgent" else "req_issue",
                material=material,
                name=material.name,
                spec=material.spec,
                unit=material.unit,
                quantity=take,
                lot=lot,
                operator=operator,
                dept_name=req.dept_name,
                ref_table="hardware_requisitions",
                ref_id=req.id,
            )

    req.status = "issued"
    req.issued_by = issued_by
    req.issued_at = now
    req.received_by = received_by
    if req.req_type == "urgent":
        from datetime import timedelta

        req.urgent_patch_deadline = now + timedelta(hours=24)
    if user:
        req.updated_by = user.id
    await db.flush()
    return req


# ── movements 查询与 ERP 标记 ──


async def list_movements(
    db: AsyncSession,
    *,
    direction: str | None = None,
    business_type: str | None = None,
    keyword: str | None = None,
    dept_name: str | None = None,
    erp_status: str | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[HardwareMovement], int]:
    stmt = select(HardwareMovement).where(HardwareMovement.is_deleted.is_(False))
    if direction:
        stmt = stmt.where(HardwareMovement.direction == direction)
    if business_type:
        stmt = stmt.where(HardwareMovement.business_type == business_type)
    if dept_name:
        stmt = stmt.where(HardwareMovement.dept_name == dept_name)
    if erp_status:
        stmt = stmt.where(HardwareMovement.erp_status == erp_status)
    if occurred_from:
        stmt = stmt.where(HardwareMovement.occurred_at >= occurred_from)
    if occurred_to:
        stmt = stmt.where(HardwareMovement.occurred_at <= occurred_to)
    if keyword:
        kw = f"%{keyword.strip()}%"
        stmt = stmt.where(
            HardwareMovement.movement_no.ilike(kw)
            | HardwareMovement.material_name.ilike(kw)
            | func.coalesce(HardwareMovement.lot_no, "").ilike(kw)
        )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = (
        await db.execute(
            stmt.order_by(HardwareMovement.occurred_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return list(items), int(total or 0)


async def mark_movements_entered(
    db: AsyncSession,
    movement_ids: list[UUID],
    *,
    erp_operator: str | None = None,
    user: User | None = None,
) -> int:
    """ERP 已录标记（一期人工通道，月度对账列出未录清单）。"""
    count = 0
    now = _now()
    for mid in movement_ids:
        mv = await db.get(HardwareMovement, mid)
        if mv is None:
            continue
        if mv.erp_status != "entered":
            mv.erp_status = "entered"
            mv.erp_entered_at = now
            mv.erp_operator = erp_operator or (
                user.display_name if user and hasattr(user, "display_name") else None
            )
            count += 1
    await db.flush()
    return count


# ── 物料主数据维护 ──


async def create_material_manual(
    db: AsyncSession, payload: Any, *, user: User | None = None
) -> HardwareMaterial:
    """主数据手工新增（管理端）。code 唯一性校验（非空时）。"""
    if payload.code:
        dup = await db.scalar(
            select(func.count()).select_from(HardwareMaterial).where(
                HardwareMaterial.code == payload.code,
                HardwareMaterial.is_deleted.is_(False),
            )
        )
        if dup:
            raise HardwareError(f"物料编码已存在: {payload.code}")
    material = HardwareMaterial(
        code=payload.code or None,
        name=payload.name,
        spec=payload.spec,
        unit=payload.unit,
        category=payload.category,
        managed_class=payload.managed_class,
        direct_dept=payload.direct_dept,
        inspect_class=payload.inspect_class,
        safety_stock=payload.safety_stock,
        max_stock=payload.max_stock,
        monthly_demands=payload.monthly_demands,
        lead_time_days=payload.lead_time_days,
        secondary_holder=payload.secondary_holder,
        no_expiry=payload.no_expiry,
        remark=payload.remark,
        created_by=user.id if user else None,
    )
    db.add(material)
    await db.flush()
    return material


async def update_material(
    db: AsyncSession, material_id: UUID, payload: Any, *, user: User | None = None
) -> HardwareMaterial:
    """主数据编辑（None 字段不动）。"""
    material = await db.get(HardwareMaterial, material_id)
    if material is None or material.is_deleted:
        raise HardwareError("物料不存在", status_code=404)
    for field in (
        "name", "spec", "unit", "category", "code", "direct_dept", "inspect_class",
        "safety_stock", "max_stock", "monthly_demands", "lead_time_days",
        "secondary_holder", "no_expiry", "active", "remark",
    ):
        value = getattr(payload, field, None)
        if value is not None:
            setattr(material, field, value)
    if user:
        material.updated_by = user.id
    await db.flush()
    return material


# ── 库位 ──


async def list_locations(db: AsyncSession, *, keyword: str | None = None) -> list[HardwareLocation]:
    stmt = select(HardwareLocation).where(
        HardwareLocation.is_deleted.is_(False), HardwareLocation.active.is_(True)
    )
    if keyword:
        kw = f"%{keyword.strip()}%"
        stmt = stmt.where(HardwareLocation.code.ilike(kw) | HardwareLocation.zone.ilike(kw))
    return list((await db.execute(stmt.order_by(HardwareLocation.code))).scalars().all())


async def create_location(
    db: AsyncSession, *, code: str, zone: str, description: str | None, user: User | None = None
) -> HardwareLocation:
    exists = await db.scalar(
        select(func.count()).select_from(HardwareLocation).where(HardwareLocation.code == code)
    )
    if exists:
        raise HardwareError(f"库位编码已存在: {code}")
    loc = HardwareLocation(
        code=code, zone=zone, description=description, created_by=user.id if user else None
    )
    db.add(loc)
    await db.flush()
    return loc
