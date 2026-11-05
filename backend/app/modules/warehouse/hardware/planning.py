"""五金库月度采购计划 + 呆滞扫描 + 温湿度 service（二期 M5，设计 §2.6/§9.1 L4）。

P7 公式（制度方案二）：月采购量 = 安全库存量 + 月使用量 − 25 日实际库存量
- 月使用量 = 近 30 天 outbound(req_issue/urgent_issue) 按物料聚合
  （盘点盘亏调整不算使用）；
- 25 日库存量 = 生成时刻 on_hand（实物账口径）；
- 结果为负取 0 并在行备注标「库存高于安全线」；
- 同月重跑幂等：plan_month 唯一，未编辑行按新快照刷新、is_edited 行保留
  人工值（人编辑优先于公式）。

AI 用量注释（L4 决策辅助）：近 3 月用量序列 → LLM 一行建议文本落
ai_note 建议态字段（人审核采纳，不自动改数量）；场景
hardware_plan_annotation 关闭/失败 → ai_note 置空不阻塞草案。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.hardware import service as hw
from app.modules.warehouse.hardware.models import (
    HardwareEnvLog,
    HardwareMaterial,
    HardwareMovement,
    HardwarePurchasePlan,
    HardwarePurchasePlanItem,
    HardwareReceipt,
    HardwareReceiptItem,
)

logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")
ZERO = Decimal("0")

USAGE_WINDOW_DAYS = 30
USAGE_BIZ_TYPES = ("req_issue", "urgent_issue")

#: 呆滞判定：连续 STALE_DAYS 天无 outbound 且 on_hand>0（季度扫描口径）
STALE_DAYS = 91


def _now() -> datetime:
    return datetime.now(CN_TZ)


def next_month(plan_from: date | None = None) -> str:
    """计划月字符串：给定日的次月 'YYYY-MM'（25 日任务生成次月计划）。"""
    base = plan_from or _now().date()
    year, month = base.year, base.month + 1
    if month > 12:
        year, month = year + 1, 1
    return f"{year:04d}-{month:02d}"


# ── 月度采购计划 ──


async def generate_monthly_plan(
    db: AsyncSession,
    plan_month: str,
    *,
    snapshot_at: datetime | None = None,
    annotate: bool = True,
    user: Any = None,
) -> HardwarePurchasePlan:
    """生成/重跑次月计划草案（P7 公式；同月幂等：头复用、未编辑行刷新）。

    25 日定时任务与 superagent plan_draft 执行器共用本入口（幂等）。
    """
    snapshot = snapshot_at or _now()
    window_start = snapshot - timedelta(days=USAGE_WINDOW_DAYS)

    plan = await db.scalar(
        select(HardwarePurchasePlan).where(
            HardwarePurchasePlan.plan_month == plan_month,
            HardwarePurchasePlan.is_deleted.is_(False),
        )
    )
    if plan is None:
        plan = HardwarePurchasePlan(
            plan_month=plan_month,
            status="draft",
            snapshot_at=snapshot,
            usage_window_days=USAGE_WINDOW_DAYS,
            created_by=user.id if user is not None else None,
        )
        db.add(plan)
        await db.flush()
    else:
        plan.snapshot_at = snapshot

    # 聚合：on_hand（Σ accepted 批次余额）+ 近窗使用量
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
    usage = (
        select(
            HardwareMovement.material_id.label("material_id"),
            func.sum(HardwareMovement.quantity).label("qty"),
        )
        .where(
            HardwareMovement.direction == "outbound",
            HardwareMovement.business_type.in_(USAGE_BIZ_TYPES),
            HardwareMovement.occurred_at >= window_start,
            HardwareMovement.occurred_at <= snapshot,
            HardwareMovement.is_deleted.is_(False),
        )
        .group_by(HardwareMovement.material_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(HardwareMaterial, func.coalesce(on_hand.c.qty, ZERO), func.coalesce(usage.c.qty, ZERO))
            .outerjoin(on_hand, on_hand.c.material_id == HardwareMaterial.id)
            .outerjoin(usage, usage.c.material_id == HardwareMaterial.id)
            .where(
                HardwareMaterial.is_deleted.is_(False),
                HardwareMaterial.active.is_(True),
                HardwareMaterial.managed_class == "stocked",
            )
            .order_by(HardwareMaterial.category, HardwareMaterial.name)
        )
    ).all()

    # 幂等重跑：未编辑行删除重建（编辑行保留）
    existing = (
        await db.execute(
            select(HardwarePurchasePlanItem).where(
                HardwarePurchasePlanItem.purchase_plan_id == plan.id,
                HardwarePurchasePlanItem.is_deleted.is_(False),
            )
        )
    ).scalars().all()
    edited_by_material = {
        str(i.material_id): i
        for i in existing
        if i.is_edited
    }
    for i in existing:
        if not i.is_edited:
            await db.delete(i)
    await db.flush()

    for material, on_hand_qty, usage_qty in rows:
        mid = str(material.id)
        if mid in edited_by_material:
            continue  # 人工编辑行保留
        demand_total = ZERO
        if material.monthly_demands:
            for v in material.monthly_demands.values():
                try:
                    demand_total += Decimal(str(v))
                except (ArithmeticError, ValueError):
                    continue
        raw = material.safety_stock + (usage_qty or ZERO) - (on_hand_qty or ZERO)
        remark = None
        if raw < ZERO:
            purchase = ZERO
            remark = "库存高于安全线，本月不采购"
        else:
            purchase = raw
        db.add(
            HardwarePurchasePlanItem(
                purchase_plan_id=plan.id,
                material_id=material.id,
                code=material.code,
                name=material.name,
                spec=material.spec,
                unit=material.unit,
                monthly_demand_total=demand_total,
                safety_stock=material.safety_stock,
                stock_on_25th=on_hand_qty or ZERO,
                monthly_usage=usage_qty or ZERO,
                purchase_qty=purchase,
                remark=remark,
            )
        )
    await db.flush()

    if annotate:
        await annotate_plan_items(db, plan)
    return plan


async def annotate_plan_items(db: AsyncSession, plan: HardwarePurchasePlan) -> None:
    """AI 用量注释（建议态）：近 3 月月度用量 → LLM 一行 ai_note。

    场景 hardware_plan_annotation 关闭/调用失败 → ai_note 保持空、
    annotated=False，草案照常（不阻塞公式主流程）。
    """
    try:
        from app.modules.warehouse.hardware.plan_annotator import annotate_items

        await annotate_items(db, plan)
        plan.annotated = True
    except Exception:  # noqa: BLE001
        plan.annotated = False
        logger.exception("五金计划 AI 注释失败（不阻塞草案）")
    await db.flush()


async def get_plan_by_month(db: AsyncSession, plan_month: str) -> HardwarePurchasePlan:
    plan = await db.scalar(
        select(HardwarePurchasePlan).where(
            HardwarePurchasePlan.plan_month == plan_month,
            HardwarePurchasePlan.is_deleted.is_(False),
        )
    )
    if plan is None:
        raise hw.HardwareError(f"计划 {plan_month} 不存在", status_code=404)
    return plan


async def list_plans(
    db: AsyncSession, *, page: int = 1, page_size: int = 20
) -> tuple[list[HardwarePurchasePlan], int]:
    stmt = select(HardwarePurchasePlan).where(HardwarePurchasePlan.is_deleted.is_(False))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        await db.execute(
            stmt.order_by(HardwarePurchasePlan.plan_month.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return list(rows), int(total or 0)


async def list_plan_items(
    db: AsyncSession, plan_id: UUID
) -> list[HardwarePurchasePlanItem]:
    return list(
        (
            await db.execute(
                select(HardwarePurchasePlanItem)
                .where(
                    HardwarePurchasePlanItem.purchase_plan_id == plan_id,
                    HardwarePurchasePlanItem.is_deleted.is_(False),
                )
                .order_by(HardwarePurchasePlanItem.created_at.asc())
            )
        ).scalars().all()
    )


async def update_plan_item(
    db: AsyncSession,
    item_id: UUID,
    *,
    purchase_qty: Decimal | None = None,
    remark: str | None = None,
    ai_note: str | None = None,
) -> HardwarePurchasePlanItem:
    """人工编辑草案（数量/备注/采纳 AI 注释）→ is_edited=True（重跑保留）。"""
    item = await db.get(HardwarePurchasePlanItem, item_id)
    if item is None:
        raise hw.HardwareError("计划行不存在", status_code=404)
    if purchase_qty is not None:
        if purchase_qty < ZERO:
            raise hw.HardwareError("采购量不可为负", status_code=422)
        item.purchase_qty = purchase_qty
    if remark is not None:
        item.remark = remark
    if ai_note is not None:
        item.ai_note = ai_note
    item.is_edited = True
    await db.flush()
    return item


def export_plan_excel(
    items: list[HardwarePurchasePlanItem], *, plan_month: str
) -> bytes:
    """制度附件 4 表样导出（11 列，与任务书列清单一致）。"""
    from io import BytesIO

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = f"{plan_month}采购计划"
    ws.append([
        "序号", "物料编码", "物资名称", "规格型号", "单位", "数量",
        "月需求合计", "安全库存量", "当月25日库存量", "月度采购量", "备注",
    ])
    for idx, i in enumerate(items, start=1):
        ws.append([
            idx, i.code or "", i.name, i.spec or "", i.unit or "",
            float(i.purchase_qty),
            float(i.monthly_demand_total), float(i.safety_stock),
            float(i.stock_on_25th), float(i.purchase_qty),
            i.remark or "",
        ])
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


# ── 呆滞扫描（季度，M5-T3 使用）──


async def scan_stale_materials(
    db: AsyncSession, *, now: datetime | None = None, stale_days: int = STALE_DAYS
) -> list[dict[str, Any]]:
    """连续 stale_days 天无 outbound 且 on_hand>0 的 stocked 物料（movements 回算）。"""
    now = now or _now()
    cutoff = now - timedelta(days=stale_days)

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
    last_out = (
        select(
            HardwareMovement.material_id.label("material_id"),
            func.max(HardwareMovement.occurred_at).label("last_at"),
        )
        .where(
            HardwareMovement.direction == "outbound",
            HardwareMovement.is_deleted.is_(False),
        )
        .group_by(HardwareMovement.material_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(
                HardwareMaterial,
                on_hand.c.qty,
                last_out.c.last_at,
            )
            .join(on_hand, on_hand.c.material_id == HardwareMaterial.id)
            .outerjoin(last_out, last_out.c.material_id == HardwareMaterial.id)
            .where(
                HardwareMaterial.is_deleted.is_(False),
                HardwareMaterial.active.is_(True),
                HardwareMaterial.managed_class == "stocked",
                on_hand.c.qty > ZERO,
            )
        )
    ).all()
    stale: list[dict[str, Any]] = []
    for material, qty, last_at in rows:
        # 无出库记录=从未动用；或最后出库早于 cutoff → 呆滞
        if last_at is None or last_at < cutoff:
            stale.append({
                "material_id": str(material.id),
                "code": material.code,
                "name": material.name,
                "spec": material.spec,
                "unit": material.unit,
                "on_hand": float(qty or ZERO),
                "last_outbound_at": last_at.isoformat() if last_at else None,
                "silent_days": stale_days if last_at is None else (now - last_at).days,
            })
    stale.sort(key=lambda r: r["silent_days"], reverse=True)
    return stale


# ── 温湿度日检 ──


async def upsert_env_log(
    db: AsyncSession,
    *,
    log_date: date,
    temperature: Decimal | None = None,
    humidity: Decimal | None = None,
    checked_by: str | None = None,
    abnormal_note: str | None = None,
    user: Any = None,
) -> HardwareEnvLog:
    """当日温湿度录入（log_date 唯一，重复提交 upsert 不双行）。"""
    log = await db.scalar(
        select(HardwareEnvLog).where(
            HardwareEnvLog.log_date == log_date,
            HardwareEnvLog.is_deleted.is_(False),
        )
    )
    if log is None:
        log = HardwareEnvLog(
            log_date=log_date,
            created_by=user.id if user is not None else None,
        )
        db.add(log)
    if temperature is not None:
        log.temperature = temperature
    if humidity is not None:
        log.humidity = humidity
    if checked_by is not None:
        log.checked_by = checked_by
    if abnormal_note is not None:
        log.abnormal_note = abnormal_note
    await db.flush()
    return log


async def list_env_logs(
    db: AsyncSession, *, days: int = 30
) -> list[HardwareEnvLog]:
    since = (_now() - timedelta(days=days)).date()
    return list(
        (
            await db.execute(
                select(HardwareEnvLog)
                .where(
                    HardwareEnvLog.log_date >= since,
                    HardwareEnvLog.is_deleted.is_(False),
                )
                .order_by(HardwareEnvLog.log_date.desc())
            )
        ).scalars().all()
    )
