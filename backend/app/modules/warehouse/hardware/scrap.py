"""五金库报废 service（三期 M7，制度 5.6 四条件；2026-11-25 并入申领出库全路径）。

报废出库与领料单走同一条出库路径（状态名对齐；审批不动库存，出库才实扣）：

    draft（发起：四条件单选+留证照片+明细行+指定审批人）
      → submit → pending（待审批；预扣生效。飞书分支已配置=代发起「福兴电子
        领/退料单审批」报废分支给所选审批人；未配置=审批人在平台点通过。
        实例创建失败→上抛，停在 draft 不降级，同申领）
      → approve → approved（待出库；审批人通过：飞书 APPROVED 回流（WS 事件/
        轮询/对账）或平台「通过」，两条路都可走，预扣保持）
      → execute → issued【唯一动账点】：仓管点「出库」——逐行 preferred_lot
        优先扣（校验有效+余额足），未指定按 FIFO（_consume_fifo 复用）；
        逐批写 movements scrap（outbound 恒正，ref=hardware_scraps）；
        批次 remaining 扣减。
    驳回（pending）/ 取消（draft/pending）：释放预扣，零动账。

红线：无单据不动账（收口原则不变）；报废只对 stocked 物料（direct 不占
库存无报废概念）；AI 不参与审批决策。
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.hardware import service as hw
from app.modules.warehouse.hardware.models import (
    HardwareMaterial,
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

SCRAP_MANAGE_PERM = "warehouse:hardware:scrap:manage"


def _now() -> datetime:
    return datetime.now(CN_TZ)


def _qty(value: Any) -> Decimal:
    return Decimal(str(value))


def can_user_approve_scrap(scrap: HardwareScrap, *, user: Any, perms: set[str]) -> bool:
    """平台「通过 / 驳回」资格：持「报废管理」权限，或被选为该单审批人。

    审批人是发起人自选的（飞书 user_id），登录用户的 identity.feishu_user_id
    与之一致即可在平台审批——与飞书审批单两条路任选其一。
    """
    if SCRAP_MANAGE_PERM in perms:
        return True
    if user is None or not scrap.approver_user_id:
        return False
    return str(getattr(user, "feishu_user_id", "") or "") == str(scrap.approver_user_id)


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
    approver_user_id: str | None = None,
    approver_name: str | None = None,
    user: Any = None,
) -> HardwareScrap:
    """报废草稿：行快照校验（仅 stocked；数量>0；批次可选）+ 指定审批人。"""
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
        requested_by_user_id=getattr(user, "id", None) if user is not None else None,
        approver_user_id=approver_user_id,
        approver_name=approver_name,
        scrap_reason=scrap_reason,
        reason_note=reason_note,
        attachments=attachments,
        status="draft",
        remark=remark,
        created_by=getattr(user, "id", None) if user is not None else None,
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


async def _mark_scrap_stock_dirty(db: AsyncSession, scrap_id: UUID) -> None:
    """报废预扣口径变化（提交/驳回/撤回/出库）→ 登记镜像三值刷新。"""
    from app.modules.warehouse.hardware.mirror_sync import mark_stock_dirty

    items = await list_scrap_items(db, scrap_id)
    mark_stock_dirty(*(i.material_id for i in items))


async def _approval_payload(db: AsyncSession, scrap_id: UUID) -> list[dict[str, Any]]:
    items = await list_scrap_items(db, scrap_id)
    return [
        {
            "material_id": str(i.material_id),
            "material_name": i.name,
            "spec": i.spec,
            "unit": i.unit,
            "quantity": float(i.quantity),
        }
        for i in items
    ]


async def submit_scrap(
    db: AsyncSession, scrap_id: UUID, *, user: Any = None
) -> HardwareScrap:
    """draft → pending：提交即预扣（可领量校验，防审批期间被领走）。

    飞书分支已配置：代发起「福兴电子领/退料单审批」报废分支给所选审批人，
    失败上抛（调用方转 502），单据留在 draft 不降级（同申领 2026-11-19 口径）；
    未配置：approval_channel=manual，审批人在平台点通过。
    """
    from app.modules.warehouse.hardware.approval_channel import (
        ApprovalChannelError,
        get_scrap_approval_channel,
    )

    scrap = await get_scrap(db, scrap_id)
    if scrap.status != "draft":
        raise hw.HardwareError(f"报废单状态 {scrap.status} 不可提交（仅草稿可提交）")
    items = await list_scrap_items(db, scrap_id)
    if not items:
        raise hw.HardwareError("报废单无明细行")
    # 预扣校验：同物料聚合后逐项对可领量（本单尚为 draft，未计入预扣）
    need_by_material: dict[UUID, Decimal] = {}
    for i in items:
        need_by_material[i.material_id] = need_by_material.get(i.material_id, ZERO) + i.quantity
    for material_id, need in need_by_material.items():
        available = await hw.available_of_material(db, material_id)
        if available < need:
            material = await db.get(HardwareMaterial, material_id)
            raise hw.HardwareError(
                f"可报废量不足：{material.name if material else material_id} "
                f"可领 {available.normalize()}，报废 {need.normalize()}"
            )

    channel = get_scrap_approval_channel()
    if channel is not None:
        if not str(scrap.approver_user_id or "").strip():
            raise hw.HardwareError(
                "未选择审批人（主管及以上），请重新发起并选择审批人", status_code=422
            )
        try:
            ref = await channel.submit_scrap(db, scrap, await _approval_payload(db, scrap_id))
        except ApprovalChannelError as exc:
            logger.exception("五金报废审批发起失败: scrap=%s", scrap.scrap_no)
            raise hw.HardwareError(
                f"飞书审批发起失败，单据已留在草稿可重试：{exc}", status_code=502
            ) from exc
        logger.info("五金报废审批已提交: scrap=%s channel=feishu ref=%s", scrap.scrap_no, ref)
    else:
        scrap.approval_channel = "manual"
        scrap.approval_status = "pending"
        logger.info("五金报废审批走平台通过: scrap=%s", scrap.scrap_no)

    scrap.status = "pending"
    if user is not None and hasattr(user, "id"):
        scrap.updated_by = user.id
    await db.flush()
    await _mark_scrap_stock_dirty(db, scrap_id)
    return scrap


async def approve_scrap(
    db: AsyncSession,
    scrap_id: UUID,
    *,
    approved_by: str,
    user: Any = None,
    withdraw_instance: bool = False,
) -> HardwareScrap:
    """pending → approved（待出库）：审批人通过，预扣保持不动账。

    飞书回流与平台「通过」共用。平台先通过时（withdraw_instance=True）尽力
    撤回还没处理的飞书审批单，审批人之后在飞书再点也不会重复处理。
    """
    from app.modules.warehouse.hardware.approval_channel import cancel_scrap_approval

    scrap = await get_scrap(db, scrap_id)
    if scrap.status != "pending":
        raise hw.HardwareError(f"报废单状态 {scrap.status} 不可审批通过（仅待审批可通过）")
    if withdraw_instance and scrap.approval_status == "pending":
        await cancel_scrap_approval(db, scrap)
    scrap.status = "approved"
    scrap.approval_status = "approved"
    scrap.approved_by = approved_by
    scrap.approved_at = _now()
    if user is not None and hasattr(user, "id"):
        scrap.updated_by = user.id
    await db.flush()
    return scrap


async def reject_scrap(
    db: AsyncSession,
    scrap_id: UUID,
    *,
    rejected_by: str,
    reason: str,
    withdraw_instance: bool = False,
) -> HardwareScrap:
    """pending → rejected：驳回释放预扣，零动账。

    平台驳回（withdraw_instance=True）尽力撤回未决飞书审批单；飞书回流
    驳回时实例已有结论，不再撤回。
    """
    from app.modules.warehouse.hardware.approval_channel import cancel_scrap_approval

    scrap = await get_scrap(db, scrap_id)
    if scrap.status != "pending":
        raise hw.HardwareError(f"报废单状态 {scrap.status} 不可驳回（仅待审批可驳回）")
    if withdraw_instance and scrap.approval_status == "pending":
        await cancel_scrap_approval(db, scrap)
    scrap.status = "rejected"
    scrap.approval_status = "rejected"
    scrap.rejected_by = rejected_by
    scrap.rejected_reason = reason
    scrap.rejected_at = _now()
    await db.flush()
    await _mark_scrap_stock_dirty(db, scrap_id)
    return scrap


async def cancel_scrap(db: AsyncSession, scrap_id: UUID) -> HardwareScrap:
    """draft/pending → cancelled：撤回释放预扣，零动账。"""
    from app.modules.warehouse.hardware.approval_channel import cancel_scrap_approval

    scrap = await get_scrap(db, scrap_id)
    if scrap.status not in ("draft", "pending"):
        raise hw.HardwareError(f"报废单状态 {scrap.status} 不可撤回（仅草稿/待审批可撤回）")
    if scrap.approval_status == "pending":
        await cancel_scrap_approval(db, scrap)
    scrap.status = "cancelled"
    await db.flush()
    await _mark_scrap_stock_dirty(db, scrap_id)
    return scrap


# ── 出库（唯一动账点）──


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


async def execute_scrap(
    db: AsyncSession, scrap_id: UUID, *, executed_by: str, user: Any = None
) -> HardwareScrap:
    """approved → issued：仓管出库实扣（唯一动账点，同事务）。

    - 逐行扣批次（preferred 优先/FIFO 兜底）+ 逐批 scrap 流水（outbound 恒正）；
    - 单头 issued + executed_by + scrapped_at + lot_allocations 结果留档。
    """
    scrap = await get_scrap(db, scrap_id)
    if scrap.status != "approved":
        raise hw.HardwareError(f"报废单状态 {scrap.status} 不可出库（审批通过后才可出库）")
    items = await list_scrap_items(db, scrap_id)
    if not items:
        raise hw.HardwareError("报废单无明细行")
    operator = (getattr(user, "display_name", None) or executed_by) if user is not None else executed_by
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
                operator=operator,
                dept_name=scrap.dept_name,
                ref_table="hardware_scraps",
                ref_id=scrap.id,
                remark=f"报废出库（{scrap.scrap_no}）：{SCRAP_REASON_LABELS.get(scrap.scrap_reason, scrap.scrap_reason)}",
            )
            allocations.append({
                "material": row.name,
                "material_id": str(row.material_id),
                "lot_id": str(lot.id),
                "lot_no": lot.lot_no,
                "mode": mode,
                "qty": float(take),
            })

    scrap.status = "issued"
    scrap.executed_by = operator
    scrap.scrapped_at = now
    scrap.lot_allocations = allocations
    if user is not None and hasattr(user, "id"):
        scrap.updated_by = user.id
    await db.flush()
    await _mark_scrap_stock_dirty(db, scrap_id)
    logger.info(
        "五金报废已出库: scrap=%s rows=%d 批次扣减=%d", scrap.scrap_no, len(items), len(allocations)
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
