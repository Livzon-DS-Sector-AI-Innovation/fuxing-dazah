"""对账引擎（分期C 阶段二 → V3.0 分期A Ticket 09 裁决反转）：本地库存 ↔ 飞书
material_stock 台账逐条比对。

四态分类：match / missing_in_feishu / mismatch / missing_local。
**裁决方向（2B 定案）：差异默认 Base 胜出**——结果行带 verdict/suggested_action
标注；「本地修复」为人工一键动作（apply_base_repair）：
- mismatch → 本地聚合数量调整为 Base 值；
- missing_local → 按 Base 记录补建本地库存行；
- missing_in_feishu → 仅置「待人工处置」（本地多出，删除属红区，绝不自动删）。
仅手动触发；飞书拉取复用 WarehouseBitableAdapter.search_records_page。
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.bitable_cells import cell_number, cell_text
from app.modules.warehouse.models import (
    WarehouseLocation,
    WarehouseMaterial,
    WarehouseStock,
    WarehouseSyncCheckResult,
    WarehouseSyncCheckRun,
)

logger = logging.getLogger(__name__)

# 飞书 material_stock 匹配字段（bitable_schema 实测快照；Ticket 09 修正——
# 原「物料编码/批次/可用库存」为错误键名，从未命中真实字段）
_FEISHU_CODE_FIELD = "代码"
_FEISHU_BATCH_FIELD = "物料批号"
_FEISHU_QTY_FIELD = "剩余数量"

# 修复状态（sync_check_results.repair_status）
REPAIR_STATUS_REPAIRED = "repaired"
REPAIR_STATUS_MANUAL = "manual"

# missing_local 补录用的固定库位（按需自动创建）
REPAIR_LOCATION_CODE = "RECON-IMPORT"
REPAIR_LOCATION_NAME = "对账补录库位"


class ReconciliationRepairError(Exception):
    """修复动作不可执行（重复处理/前置缺失等，调用方转 4xx）。"""


def _feishu_cell_text(value: Any) -> str:
    """匹配键文本（规范解析：富文本分段/类型包裹/单选数组全兼容）。"""
    return cell_text(value)


def _feishu_cell_number(value: Any) -> float:
    """数值（规范解析；无法解析按 0 计）。"""
    return cell_number(value) or 0.0


async def _fetch_all_feishu_records(db: AsyncSession) -> list[dict[str, Any]]:
    """分页拉取飞书 material_stock 全量记录。"""
    from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter

    adapter = WarehouseBitableAdapter()
    all_rows: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        data = await adapter.search_records_page(
            "material_stock", limit=500, page_token=page_token,
        )
        all_rows.extend(data["records"])
        page_token = data.get("page_token")
        if not page_token:
            break
    return all_rows


async def run_stock_reconciliation(
    db: AsyncSession, *, operator_id: str | None = None
) -> WarehouseSyncCheckRun:
    """执行一次库存对账并落库（调用方负责 commit）。"""
    run = WarehouseSyncCheckRun(status="running")
    db.add(run)
    await db.flush()

    started = time.monotonic()
    try:
        # 1. 本地侧：按 (material_code, batch_no) 聚合
        stmt = (
            select(
                WarehouseStock.material_code,
                WarehouseStock.material_name,
                WarehouseStock.batch_no,
                func.sum(WarehouseStock.quantity).label("qty"),
            )
            .where(WarehouseStock.is_deleted == False)  # noqa: E712
            .group_by(
                WarehouseStock.material_code,
                WarehouseStock.material_name,
                WarehouseStock.batch_no,
            )
        )
        local_rows = (await db.execute(stmt)).all()
        local_map: dict[tuple[str, str], dict[str, Any]] = {
            (r[0], r[2]): {"material_name": r[1], "qty": float(r[3])}
            for r in local_rows
        }

        # 2. 飞书侧：分页拉全量
        feishu_raw = await _fetch_all_feishu_records(db)
        feishu_map: dict[tuple[str, str], dict[str, Any]] = {}
        for row in feishu_raw:
            fields = row.get("fields") or {}
            code = _feishu_cell_text(fields.get(_FEISHU_CODE_FIELD))
            batch = _feishu_cell_text(fields.get(_FEISHU_BATCH_FIELD))
            qty = _feishu_cell_number(fields.get(_FEISHU_QTY_FIELD))
            key = (code, batch)
            feishu_map[key] = {"qty": qty, "record_id": row.get("record_id", "")}

        # 3. 四态分类（差异行默认标注「Base 胜出」裁决，Ticket 09）
        cnt_match = 0
        cnt_mif = 0
        cnt_mismatch = 0
        cnt_ml = 0
        results: list[WarehouseSyncCheckResult] = []

        for key, local in local_map.items():
            code, batch = key
            feishu = feishu_map.get(key)
            if feishu is None:
                cnt_mif += 1
                results.append(WarehouseSyncCheckResult(
                    run_id=run.id, status="missing_in_feishu",
                    material_code=code, material_name=local["material_name"],
                    batch_no=batch, local_qty=local["qty"], feishu_qty=None,
                    detail={
                        "reason": "飞书台账无此记录",
                        "verdict": "base_wins",
                        "suggested_action": "manual_review",
                    },
                ))
            else:
                lq = local["qty"]
                fq = feishu["qty"]
                if abs(lq - fq) > 0.001:
                    cnt_mismatch += 1
                    results.append(WarehouseSyncCheckResult(
                        run_id=run.id, status="mismatch",
                        material_code=code, material_name=local["material_name"],
                        batch_no=batch, local_qty=lq, feishu_qty=fq,
                        feishu_record_id=feishu.get("record_id"),
                        detail={
                            "reason": "数量不一致",
                            "verdict": "base_wins",
                            "suggested_action": "repair_local",
                        },
                    ))
                else:
                    cnt_match += 1

        for key, feishu in feishu_map.items():
            if key not in local_map:
                cnt_ml += 1
                results.append(WarehouseSyncCheckResult(
                    run_id=run.id, status="missing_local",
                    material_code=key[0], material_name="", batch_no=key[1],
                    local_qty=None, feishu_qty=feishu["qty"],
                    feishu_record_id=feishu.get("record_id"),
                    detail={
                        "reason": "本地无此记录",
                        "verdict": "base_wins",
                        "suggested_action": "repair_local",
                    },
                ))

        for r in results:
            db.add(r)

        run.status = "completed"
        run.total_local = len(local_map)
        run.total_feishu = len(feishu_map)
        run.cnt_match = cnt_match
        run.cnt_missing_in_feishu = cnt_mif
        run.cnt_mismatch = cnt_mismatch
        run.cnt_missing_local = cnt_ml
        run.duration_ms = int((time.monotonic() - started) * 1000)
        await db.flush()
        return run

    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)[:500]
        run.duration_ms = int((time.monotonic() - started) * 1000)
        await db.flush()
        logger.exception("库存对账失败")
        return run


async def list_runs(db: AsyncSession, *, page: int, page_size: int) -> tuple[list[WarehouseSyncCheckRun], int]:
    stmt = select(WarehouseSyncCheckRun).where(
        WarehouseSyncCheckRun.is_deleted == False  # noqa: E712
    ).order_by(WarehouseSyncCheckRun.created_at.desc())
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    items = list((await db.execute(stmt)).scalars().all())
    return items, int(total or 0)


async def list_results(
    db: AsyncSession, *, run_id: str, status: str | None, page: int, page_size: int
) -> tuple[list[WarehouseSyncCheckResult], int]:
    stmt = select(WarehouseSyncCheckResult).where(
        WarehouseSyncCheckResult.run_id == UUID(run_id),
        WarehouseSyncCheckResult.is_deleted == False,  # noqa: E712
    )
    if status:
        stmt = stmt.where(WarehouseSyncCheckResult.status == status)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    items = list((await db.execute(stmt)).scalars().all())
    return items, int(total or 0)


async def _get_repair_location(db: AsyncSession) -> WarehouseLocation:
    """missing_local 补录固定库位（不存在则创建）。"""
    loc = (
        await db.execute(
            select(WarehouseLocation).where(
                WarehouseLocation.code == REPAIR_LOCATION_CODE,
                WarehouseLocation.is_deleted.is_(False),
            )
        )
    ).scalars().first()
    if loc is None:
        loc = WarehouseLocation(code=REPAIR_LOCATION_CODE, name=REPAIR_LOCATION_NAME)
        db.add(loc)
        await db.flush()
    return loc


async def apply_base_repair(
    db: AsyncSession, result_id: str | UUID, *, operator_id: str | None = None
) -> WarehouseSyncCheckResult:
    """按「Base 为准」人工一键修复本地（Ticket 09；不 commit，调用方负责）。

    - mismatch：本地该 (编码, 批次) 聚合数量调整为 Base 值（差额落在数量
      最大的行；调整后为负则拒绝）；
    - missing_local：按 Base 记录补建本地库存行（物料主数据须已存在，
      库位用「对账补录」）；
    - missing_in_feishu：仅置「待人工处置」（本地多出，删除属红区）。
    重复修复（repair_status 已终态）抛 ReconciliationRepairError。
    """
    from app.modules.warehouse.agent import repository as agent_repository

    try:
        rid = result_id if isinstance(result_id, UUID) else UUID(str(result_id))
    except ValueError as exc:
        raise ReconciliationRepairError("差异行 ID 无效") from exc

    result = (
        await db.execute(
            select(WarehouseSyncCheckResult).where(
                WarehouseSyncCheckResult.id == rid,
                WarehouseSyncCheckResult.is_deleted.is_(False),
            )
        )
    ).scalars().first()
    if result is None:
        raise ReconciliationRepairError("差异行不存在或已删除")

    if result.repair_status in (REPAIR_STATUS_REPAIRED, REPAIR_STATUS_MANUAL):
        raise ReconciliationRepairError(
            f"该差异行已处理（{result.repair_status}），请重新对账后再操作"
        )

    if result.status == "mismatch":
        await _repair_mismatch(db, result)
        result.repair_status = REPAIR_STATUS_REPAIRED
    elif result.status == "missing_local":
        await _repair_missing_local(db, result)
        result.repair_status = REPAIR_STATUS_REPAIRED
    elif result.status == "missing_in_feishu":
        # 本地多出：Base 胜出 = 本地行不应存在，但删除属红区 → 仅标记待人工处置
        result.repair_status = REPAIR_STATUS_MANUAL
    else:
        raise ReconciliationRepairError(f"该差异行状态（{result.status}）无需修复")

    result.repaired_at = datetime.now(UTC)
    await agent_repository.insert_agent_audit(
        db,
        tool_name="reconciliation_repair",
        args_summary={
            "result_id": str(result.id),
            "status": result.status,
            "material_code": result.material_code,
            "batch_no": result.batch_no,
            "repair_status": result.repair_status,
            "operator": (operator_id or "")[:30],
        },
        result_status="ok",
    )
    await db.flush()
    return result


async def _repair_mismatch(db: AsyncSession, result: WarehouseSyncCheckResult) -> None:
    """本地聚合数量调整为 Base 值：差额落在数量最大的一行。"""
    if result.feishu_qty is None:
        raise ReconciliationRepairError("该行无飞书数量，无法按 Base 修复")
    rows = list(
        (
            await db.execute(
                select(WarehouseStock).where(
                    WarehouseStock.material_code == result.material_code,
                    WarehouseStock.batch_no == result.batch_no,
                    WarehouseStock.is_deleted.is_(False),
                )
            )
        ).scalars().all()
    )
    if not rows:
        raise ReconciliationRepairError("本地对应库存行已不存在，请重新对账")

    local_total = sum(float(r.quantity) for r in rows)
    delta = float(result.feishu_qty) - local_total
    if abs(delta) < 0.0001:
        return  # 聚合已一致（可能已被单独调整过）
    target = max(rows, key=lambda r: float(r.quantity))
    new_qty = Decimal(str(round(float(target.quantity) + delta, 4)))
    if new_qty < 0:
        raise ReconciliationRepairError(
            f"按 Base 调整后数量为负（{new_qty}），请人工核对后处理"
        )
    target.quantity = new_qty


async def _repair_missing_local(db: AsyncSession, result: WarehouseSyncCheckResult) -> None:
    """按 Base 记录补建本地库存行（物料主数据须已存在）。"""
    if result.feishu_qty is None:
        raise ReconciliationRepairError("该行无飞书数量，无法补建本地行")
    material = (
        await db.execute(
            select(WarehouseMaterial).where(
                WarehouseMaterial.code == result.material_code,
                WarehouseMaterial.is_deleted.is_(False),
            )
        )
    ).scalars().first()
    if material is None:
        raise ReconciliationRepairError(
            f"本地无物料主数据 {result.material_code}，请先在物料管理录入再修复"
        )
    loc = await _get_repair_location(db)
    db.add(
        WarehouseStock(
            material_id=material.id,
            material_code=material.code,
            material_name=result.material_name or material.name,
            batch_no=result.batch_no or "",
            location_id=loc.id,
            location_code=loc.code,
            location_name=loc.name,
            quantity=Decimal(str(round(float(result.feishu_qty), 4))),
        )
    )
