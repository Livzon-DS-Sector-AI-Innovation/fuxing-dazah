"""五金库 OCR↔ERP 并存对账（三期 M8，设计 §六）。

erp_import 单到达 → 自动匹配既有 OCR/manual 单：
- 候选=同供应商（归一化相等/包含）∧ 到货日期 ±3 天 ∧ status=accepted；
- 行级判定：同 material_id 或 品名+规格归一化相等（matcher 归一化复用）
  ∧ 数量容差（默认 0=精确相等，可配）；
- 全行命中（每个 ERP 行找到互不重复的 OCR 行）→ **双向 verified**
  （erp.reconcile_status=ocr.reconcile_status="verified" + matched_receipt_id
  互指）；否则 erp 单 reconcile_status="unmatched"。

账务语义（spec 质询定案 #3）：OCR 单是库存权威（实物账），ERP 单=对账载体；
**verified 的 ERP 单禁止再入账**（accept_receipt 入口拦截，防双计）；
无 OCR 对应的 ERP 单走人工确认=补录入账（生成批次，正常路径）。

差异清单两栏：
- 「erp 有 ocr 无」= source=erp_import ∧ reconcile_status=unmatched；
- 「ocr 有 erp 无」= source∈(ocr,manual) ∧ status=accepted ∧
  reconcile_status="none"（未被任何 verified ERP 单指到）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.hardware import matcher as hw_matcher
from app.modules.warehouse.hardware import service as hw_service
from app.modules.warehouse.hardware.models import (
    HardwareReceipt,
    HardwareReceiptItem,
)

logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")
ZERO = Decimal("0")

#: 日期匹配窗（±3 天，任务书口径）
DATE_WINDOW_DAYS = 3


def _norm(value: str | None) -> str:
    return hw_matcher.normalize_text(value)


def _norm_spec(value: str | None) -> str:
    return hw_matcher.normalize_spec(value)


def _row_key(material_id: Any, name: str | None, spec: str | None) -> tuple[str, str, str]:
    """行对齐键：(material_id, 归一化品名, 归一化规格)。"""
    return (str(material_id) if material_id else "", _norm(name), _norm_spec(spec))


def _rows_match(
    erp_row: HardwareReceiptItem,
    ocr_row: HardwareReceiptItem,
    qty_tolerance: Decimal,
) -> bool:
    """行级判定：物料/品名规格对上 ∧ 数量在容差内。"""
    if erp_row.material_id and ocr_row.material_id:
        if erp_row.material_id != ocr_row.material_id:
            return False
    else:
        # 任一侧未挂主数据：品名+规格归一化相等兜底
        if _norm(erp_row.name) != _norm(ocr_row.name):
            return False
        if _norm_spec(erp_row.spec) != _norm_spec(ocr_row.spec):
            return False
    diff = abs((erp_row.quantity or ZERO) - (ocr_row.quantity or ZERO))
    return diff <= qty_tolerance


async def match_erp_receipt(
    db: AsyncSession,
    erp_receipt: HardwareReceipt,
    *,
    qty_tolerance: Decimal = ZERO,
) -> str:
    """erp_import 单自动匹配既有 OCR/manual 单，落双向 verified/unmatched。

    返回最终 reconcile_status（"verified" / "unmatched"）；非 erp_import
    单或非 draft 单原样返回现状态（幂等：已 verified 不重算）。
    """
    if erp_receipt.source != "erp_import" or erp_receipt.is_deleted:
        return erp_receipt.reconcile_status
    if erp_receipt.status != "draft":
        return erp_receipt.reconcile_status
    if erp_receipt.reconcile_status == "verified":
        return erp_receipt.reconcile_status  # 幂等

    erp_rows = await hw_service.list_receipt_items(db, erp_receipt.id)
    if not erp_rows:
        erp_receipt.reconcile_status = "unmatched"
        return erp_receipt.reconcile_status

    # 候选：同供应商 ∧ 日期 ±3 天 ∧ accepted 的 ocr/manual 单
    arrived = erp_receipt.arrived_at
    supplier_n = _norm(erp_receipt.supplier_name)
    stmt = (
        select(HardwareReceipt)
        .where(
            HardwareReceipt.source.in_(("ocr", "manual")),
            HardwareReceipt.status == "accepted",
            HardwareReceipt.is_deleted.is_(False),
        )
        .order_by(HardwareReceipt.accepted_at.desc())
        .limit(50)
    )
    if arrived is not None:
        stmt = stmt.where(
            HardwareReceipt.arrived_at >= arrived - timedelta(days=DATE_WINDOW_DAYS),
            HardwareReceipt.arrived_at <= arrived + timedelta(days=DATE_WINDOW_DAYS),
        )
    if supplier_n:
        # 供应商过滤放 Python 侧（归一化相等/包含双口径，LIKE 无法表达）
        candidates = [
            r for r in (await db.execute(stmt)).scalars().all()
            if r.supplier_name
            and (supplier_n in _norm(r.supplier_name) or _norm(r.supplier_name) in supplier_n)
        ]
    else:
        candidates = list((await db.execute(stmt)).scalars().all())

    for candidate in candidates:
        ocr_rows = await hw_service.list_receipt_items(db, candidate.id)
        # 全行命中：每个 ERP 行找到互不重复的 OCR 行
        used: set[Any] = set()
        all_hit = True
        for erp_row in erp_rows:
            hit = next(
                (
                    o for o in ocr_rows
                    if o.id not in used and _rows_match(erp_row, o, qty_tolerance)
                ),
                None,
            )
            if hit is None:
                all_hit = False
                break
            used.add(hit.id)
        if not all_hit:
            continue

        # 双向 verified（对账载体标记，零动账零批次）
        erp_receipt.reconcile_status = "verified"
        erp_receipt.matched_receipt_id = candidate.id
        candidate.reconcile_status = "verified"
        candidate.matched_receipt_id = erp_receipt.id
        await db.flush()
        logger.info(
            "ERP 单对账匹配成功: erp=%s ↔ ocr=%s", erp_receipt.receipt_no, candidate.receipt_no
        )
        return "verified"

    erp_receipt.reconcile_status = "unmatched"
    await db.flush()
    return erp_receipt.reconcile_status


async def list_erp_receipts(
    db: AsyncSession,
    *,
    reconcile_status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[HardwareReceipt], int]:
    """erp_import 单列表（匹配状态筛选；对账 Tab 主列表）。"""
    stmt = select(HardwareReceipt).where(
        HardwareReceipt.source == "erp_import",
        HardwareReceipt.is_deleted.is_(False),
    )
    if reconcile_status:
        stmt = stmt.where(HardwareReceipt.reconcile_status == reconcile_status)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        await db.execute(
            stmt.order_by(HardwareReceipt.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return list(rows), int(total or 0)


async def list_reconcile_diffs(
    db: AsyncSession, *, days: int = 30
) -> dict[str, list[dict[str, Any]]]:
    """差异清单两栏（对账差异页）：
    - erp_only：erp_import ∧ unmatched（erp 有 ocr 无——可人工确认补录入账）；
    - ocr_only：ocr/manual ∧ accepted ∧ reconcile_status="none"
      （ocr 有 erp 无——提示 ERP 侧补录）。
    """
    cut = datetime.now(CN_TZ) - timedelta(days=days)

    erp_only_rows = (
        await db.execute(
            select(HardwareReceipt)
            .where(
                HardwareReceipt.source == "erp_import",
                HardwareReceipt.reconcile_status == "unmatched",
                HardwareReceipt.is_deleted.is_(False),
                HardwareReceipt.created_at >= cut,
            )
            .order_by(HardwareReceipt.created_at.desc())
        )
    ).scalars().all()

    ocr_only_rows = (
        await db.execute(
            select(HardwareReceipt)
            .where(
                HardwareReceipt.source.in_(("ocr", "manual")),
                HardwareReceipt.status == "accepted",
                HardwareReceipt.reconcile_status == "none",
                HardwareReceipt.is_deleted.is_(False),
                HardwareReceipt.accepted_at >= cut,
            )
            .order_by(HardwareReceipt.accepted_at.desc())
        )
    ).scalars().all()

    def _head(r: HardwareReceipt) -> dict[str, Any]:
        return {
            "receipt_id": str(r.id),
            "receipt_no": r.receipt_no,
            "erp_doc_no": r.erp_doc_no,
            "supplier_name": r.supplier_name,
            "arrived_at": r.arrived_at.isoformat() if r.arrived_at else None,
            "status": r.status,
            "mode": r.mode,
            "reconcile_status": r.reconcile_status,
        }

    return {
        "erp_only": [_head(r) for r in erp_only_rows],
        "ocr_only": [_head(r) for r in ocr_only_rows],
    }
