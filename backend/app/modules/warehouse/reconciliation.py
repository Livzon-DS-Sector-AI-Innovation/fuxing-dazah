"""对账引擎（分期C 阶段二）：本地库存 ↔ 飞书 material_stock 台账逐条比对。

四态分类：match / missing_in_feishu / mismatch / missing_local。
仅展示不覆盖（用户决策）；仅手动触发。
飞书拉取复用 WarehouseBitableAdapter.search_records_page（限流内建）+ 分页循环。
"""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.models import (
    WarehouseStock,
    WarehouseSyncCheckResult,
    WarehouseSyncCheckRun,
)

logger = logging.getLogger(__name__)

# 飞书 material_stock 表中用于匹配的字段名（bitable_schema material_stock 定义）
_FEISHU_CODE_FIELD = "物料编码"
_FEISHU_BATCH_FIELD = "批次"
_FEISHU_QTY_FIELD = "可用库存"


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
            code = str(fields.get(_FEISHU_CODE_FIELD, "")).strip()
            batch = str(fields.get(_FEISHU_BATCH_FIELD, "")).strip()
            qty_raw = fields.get(_FEISHU_QTY_FIELD)
            try:
                qty = float(qty_raw) if qty_raw is not None else 0.0
            except (ValueError, TypeError):
                qty = 0.0
            key = (code, batch)
            feishu_map[key] = {"qty": qty, "record_id": row.get("record_id", "")}

        # 3. 四态分类
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
                    detail={"reason": "飞书台账无此记录"},
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
                        detail={"reason": "数量不一致"},
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
                    detail={"reason": "本地无此记录"},
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
