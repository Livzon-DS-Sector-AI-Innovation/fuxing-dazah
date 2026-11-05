"""五金库报废 service（三期 M7，制度 5.6 四条件，设计 §十一 三期）。

报废闭环（两步审批，manual 通道默认；feishu 通道制度定稿后切配置）：

    draft（发起：四条件单选+留证照片+明细行）
      → submit → pending_dept（①待部门主管确认）
      → dept_confirm → pending_final（②待仓储负责人终审）
      → final_approve → approved【唯一动账点】：
          逐行 preferred_lot 优先扣（校验有效+余额足），未指定按 FIFO
          （_consume_fifo 复用）；逐批写 movements scrap（outbound 恒正，
          ref=hardware_scraps）；批次 remaining 扣减。
    驳回（任一步）/取消：零动账。

红线：无单据不动账（收口原则不变）；报废只对 stocked 物料（direct 不占
库存无报废概念）；AI 不参与审批决策。
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.hardware import service as hw
from app.modules.warehouse.hardware.models import (
    HardwareMaterial,
    HardwareMovement,
    HardwareReceipt,
    HardwareReceiptItem,
    HardwareScrap,
    HardwareScrapItem,
)

logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")
ZERO = Decimal("0")

_SCRAP_NO_COLUMN = HardwareScrap.__table__.c.scrap_no

SCRAP_REASON_LABELS = {
    "expired": "超有效期",
    "damaged": "破损污染变质",
    "obsolete": "工艺淘汰",
    "appraisal": "技术鉴定失效",
}


def _now() -> datetime:
    return datetime.now(CN_TZ)


def _qty(value: Any) -> Decimal:
    return Decimal(str(value))


# ── 发起与状态机 ──


async def create_scrap(
    db: AsyncSession,
    *,
    dept_name: str,
    requested_by: str,
    requested_by_open_id: str | None = None,
    scrap_reason: str,
    reason_note: str | None = None,
    items: list[dict[str, Any]],
    attachments: list[dict[str, Any]] | None = None,
    remark: str | None = None,
) -> HardwareScrap:
    """报废草稿：行快照校验（仅 stocked；数量>0；批次可选）。"""
    if scrap_reason not in SCRAP_REASON_LABELS:
        raise hw.HardwareError(
            f"未知报废条件: {scrap_reason}（须为 {'/'.join(SCRAP_REASON_LABELS)}）",
            status_code=422,
        )
    rows: list[dict[str, Any]] = []
    for raw in items or []:
        qty = _qty(raw.get("quantity"))
        if qty <= ZERO:
            raise hw.HardwareError("报废数量必须大于 0", status_code=422)
        material = await db.get(HardwareMaterial, UUID(str(raw.get("material_id"))))
        if material is None:
            raise hw.HardwareError(f"物料不存在: {raw.get('material_id')}", status_code=404)
        if material.managed_class != "stocked":
            raise hw.HardwareError(
                f"{material.name} 是车间单独需求类（不占库存），无报废概念"
            )
        rows.append({
            "material_id": str(material.id),
            "name": material.name,
            "spec": material.spec,
            "unit": material.unit,
            "unit_price": str(material.unit_price) if material.unit_price is not None else None,
            "quantity": str(qty),
            "preferred_lot_id": raw.get("preferred_lot_id"),
        })
    if not rows:
        raise hw.HardwareError("报废单无明细行", status_code=422)
    scrap = HardwareScrap(
        scrap_no=await hw.generate_doc_no(db, HardwareScrap, "WJK-BF", column=_SCRAP_NO_COLUMN),
        dept_name=dept_name,
        requested_by=requested_by,
        requested_by_open_id=requested_by_open_id,
        scrap_reason=scrap_reason,
        reason_note=reason_note,
        attachments=attachments,
        status="draft",
        remark=remark,
    )
    db.add(scrap)
    await db.flush()
    for row in rows:
        db.add(
            HardwareScrapItem(
                scrap_id=scrap.id,
                material_id=UUID(row["material_id"]),
                quantity=_qty(row["quantity"]),
                preferred_lot_id=(
                    UUID(str(row["preferred_lot_id"])) if row.get("preferred_lot_id") else None
                ),
                name=row["name"],
                spec=row["spec"],
                unit=row["unit"],
                unit_price=_qty(row["unit_price"]) if row.get("unit_price") else None,
            )
        )
    await db.flush()
    return scrap


async def get_scrap(db: AsyncSession, scrap_id: UUID) -> HardwareScrap:
    scrap = await db.get(HardwareScrap, scrap_id)
    if scrap is None:
        raise hw.HardwareError("报废单不存在", status_code=404)
    return scrap


async def list_scrap_items(db: AsyncSession, scrap_id: UUID) -> list[HardwareScrapItem]:
    return list(
        (
            await db.execute(
                select(HardwareScrapItem)
                .where(
                    HardwareScrapItem.scrap_id == scrap_id,
                    HardwareScrapItem.is_deleted.is_(False),
                )
                .order_by(HardwareScrapItem.created_at.asc())
            )
        ).scalars().all()
    )


async def list_scraps(
    db: AsyncSession,
    *,
    status: str | None = None,
    scrap_reason: str | None = None,
    dept_name: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[HardwareScrap], int]:
    stmt = select(HardwareScrap).where(HardwareScrap.is_deleted.is_(False))
    if status:
        stmt = stmt.where(HardwareScrap.status == status)
    if scrap_reason:
        stmt = stmt.where(HardwareScrap.scrap_reason == scrap_reason)
    if dept_name:
        stmt = stmt.where(HardwareScrap.dept_name == dept_name)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        await db.execute(
            stmt.order_by(HardwareScrap.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return list(rows), int(total or 0)


async def submit_scrap(
    db: AsyncSession, scrap_id: UUID, *, user: Any = None
) -> HardwareScrap:
    """draft → pending_dept：提交审批（复用 ApprovalChannel 工厂，未配置=manual 两步）。"""
    from app.modules.warehouse.hardware.approval_channel import (
        ApprovalChannelError,
        get_scrap_approval_channel,
    )

    scrap = await get_scrap(db, scrap_id)
    if scrap.status != "draft":
        raise hw.HardwareError(f"报废单状态 {scrap.status} 不可提交（仅 draft 可提交）")
    items = await list_scrap_items(db, scrap_id)
    if not items:
        raise hw.HardwareError("报废单无明细行")
    channel = get_scrap_approval_channel()
    payload = [
        {
            "material_id": str(i.material_id),
            "material_name": i.name,
            "spec": i.spec,
            "unit": i.unit,
            "quantity": float(i.quantity),
        }
        for i in items
    ]
    try:
        ref = await channel.submit_scrap(db, scrap, payload)
        scrap.approval_channel = channel.name
        scrap.approval_status = "pending"
        logger.info(
            "五金报废审批已提交: scrap=%s channel=%s ref=%s", scrap.scrap_no, channel.name, ref
        )
    except ApprovalChannelError:
        # feishu 通道故障 → manual 两步兜底（与领料同款降级口径）
        if channel.name == "feishu":
            logger.warning("feishu 报废审批提交失败，降级 manual 通道: %s", scrap.scrap_no)
            scrap.approval_channel = "manual"
            scrap.approval_status = "pending"
        else:
            raise
    scrap.status = "pending_dept"
    if user is not None and hasattr(user, "id"):
        scrap.updated_by = user.id
    await db.flush()
    return scrap


async def dept_confirm_scrap(
    db: AsyncSession, scrap_id: UUID, *, confirmed_by: str, note: str | None = None
) -> HardwareScrap:
    """pending_dept → pending_final：①部门主管确认（manual 通道第一步）。"""
    scrap = await get_scrap(db, scrap_id)
    if scrap.status != "pending_dept":
        raise hw.HardwareError(f"报废单状态 {scrap.status} 不可部门确认（仅 pending_dept 可确认）")
    scrap.status = "pending_final"
    scrap.dept_confirmed_by = confirmed_by
    scrap.dept_confirmed_at = _now()
    if note:
        scrap.remark = note
    await db.flush()
    return scrap


async def reject_scrap(
    db: AsyncSession, scrap_id: UUID, *, rejected_by: str, reason: str
) -> HardwareScrap:
    """pending_dept/pending_final → rejected：驳回零动账。"""
    scrap = await get_scrap(db, scrap_id)
    if scrap.status not in ("pending_dept", "pending_final"):
        raise hw.HardwareError(f"报废单状态 {scrap.status} 不可驳回（仅审批中两态可驳回）")
    scrap.status = "rejected"
    scrap.approval_status = "rejected"
    scrap.rejected_by = rejected_by
    scrap.rejected_reason = reason
    scrap.rejected_at = _now()
    await db.flush()
    return scrap


async def cancel_scrap(db: AsyncSession, scrap_id: UUID) -> HardwareScrap:
    """draft/pending_dept/pending_final → cancelled：发起人撤回（零动账）。"""
    scrap = await get_scrap(db, scrap_id)
    if scrap.status == "approved":
        raise hw.HardwareError("已销账的报废单不可撤回")
    if scrap.status == "cancelled":
        raise hw.HardwareError("报废单已是取消状态")
    scrap.status = "cancelled"
    await db.flush()
    return scrap


# ── 销账（唯一动账点）──


async def _consume_scrap_lots(
    db: AsyncSession, row: HardwareScrapItem
) -> list[tuple[HardwareReceiptItem, Decimal, str]]:
    """报废行扣批次：preferred_lot 优先（校验有效+余额足），空则 FIFO。"""
    material_id = row.material_id
    qty = row.quantity
    allocs: list[tuple[HardwareReceiptItem, Decimal, str]] = []
    if row.preferred_lot_id:
        lot = await db.get(HardwareReceiptItem, row.preferred_lot_id)
        parent = (
            await db.get(HardwareReceipt, lot.receipt_id)
            if lot is not None and not lot.is_deleted
            else None
        )
        if (
            lot is None
            or lot.is_deleted
            or parent is None
            or parent.status != "accepted"
            or lot.material_id != material_id
            or lot.remaining_quantity is None
        ):
            raise hw.HardwareError(f"指定批次无效，不可报废：{row.name}（批次不存在或非 accepted）")
        if lot.remaining_quantity < qty:
            raise hw.HardwareError(
                f"指定批次余额不足：{row.name} 余 {lot.remaining_quantity.normalize()}，"
                f"报废 {qty.normalize()}"
            )
        lot.remaining_quantity = lot.remaining_quantity - qty
        allocs.append((lot, qty, "preferred"))
        return allocs
    # FIFO（复用库存引擎扣减；批次不足上抛）
    lots = await hw.get_fifo_lots(db, material_id)
    for lot, take in hw._consume_fifo(lots, qty):
        allocs.append((lot, take, "fifo"))
    return allocs


async def final_approve_scrap(
    db: AsyncSession, scrap_id: UUID, *, approved_by: str, user: Any = None
) -> HardwareScrap:
    """pending_final → approved：终审通过即销账（唯一动账点，同事务）。

    - 逐行扣批次（preferred 优先/FIFO 兜底）+ 逐批 scrap 流水（outbound 恒正）；
    - 单头 approved + scrapped_at + lot_allocations 结果留档。
    """
    scrap = await get_scrap(db, scrap_id)
    if scrap.status != "pending_final":
        raise hw.HardwareError(
            f"报废单状态 {scrap.status} 不可终审（部门主管确认后才可终审）"
        )
    items = await list_scrap_items(db, scrap_id)
    if not items:
        raise hw.HardwareError("报废单无明细行")
    now = _now()
    allocations: list[dict[str, Any]] = []

    for row in items:
        material = await db.get(HardwareMaterial, row.material_id)
        if material is None:
            raise hw.HardwareError(f"报废行物料不存在: {row.material_id}", status_code=404)
        for lot, take, mode in await _consume_scrap_lots(db, row):
            await hw._write_movement(
                db,
                direction="outbound",
                business_type="scrap",
                material=material,
                name=row.name,
                spec=row.spec,
                unit=row.unit,
                quantity=take,
                lot=lot,
                operator=approved_by,
                dept_name=scrap.dept_name,
                ref_table="hardware_scraps",
                ref_id=scrap.id,
                remark=f"报废销账（{scrap.scrap_no}）：{SCRAP_REASON_LABELS.get(scrap.scrap_reason, scrap.scrap_reason)}",
            )
            allocations.append({
                "material": row.name,
                "material_id": str(row.material_id),
                "lot_id": str(lot.id),
                "lot_no": lot.lot_no,
                "mode": mode,
                "qty": float(take),
            })

    scrap.status = "approved"
    scrap.approval_status = "approved"
    scrap.approved_by = approved_by
    scrap.approved_at = now
    scrap.scrapped_at = now
    scrap.lot_allocations = allocations
    if user is not None and hasattr(user, "id"):
        scrap.updated_by = user.id
    await db.flush()
    logger.info(
        "五金报废已销账: scrap=%s rows=%d 批次扣减=%d", scrap.scrap_no, len(items), len(allocations)
    )
    return scrap


async def scrap_summary(db: AsyncSession, scrap_id: UUID) -> dict[str, Any]:
    """报废单详情聚合（头+行+批次结果；台账/审批页共用）。"""
    scrap = await get_scrap(db, scrap_id)
    items = await list_scrap_items(db, scrap_id)
    total_amount = sum(
        ((i.unit_price or ZERO) * i.quantity for i in items), Decimal("0")
    )
    return {
        "scrap": scrap,
        "items": items,
        "total_amount": total_amount.quantize(Decimal("0.01")),
    }
