"""对账中心路由（分期C 阶段二 Ticket 05-06 后端）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.warehouse import reconciliation as reconciliation_service
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission

router = APIRouter()


@router.post("/reconciliation/run", status_code=201, summary="手动触发库存台账对账")
async def run_stock_reconciliation(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:intelligence:update")),
) -> JSONResponse:
    run = await reconciliation_service.run_stock_reconciliation(db)
    await db.commit()
    return success_response(
        {
            "run_id": str(run.id),
            "status": run.status,
            "total_local": run.total_local,
            "total_feishu": run.total_feishu,
            "cnt_match": run.cnt_match,
            "cnt_missing_in_feishu": run.cnt_missing_in_feishu,
            "cnt_mismatch": run.cnt_mismatch,
            "cnt_missing_local": run.cnt_missing_local,
            "duration_ms": run.duration_ms,
            "error_message": run.error_message,
        },
        status_code=201,
    )


@router.get("/reconciliation/runs", summary="对账运行历史分页")
async def list_reconciliation_runs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:intelligence:read")),
) -> JSONResponse:
    items, total = await reconciliation_service.list_runs(db, page=page, page_size=page_size)
    return paginated_response(
        [
            {
                "id": str(r.id),
                "status": r.status,
                "total_local": r.total_local,
                "total_feishu": r.total_feishu,
                "cnt_match": r.cnt_match,
                "cnt_missing_in_feishu": r.cnt_missing_in_feishu,
                "cnt_mismatch": r.cnt_mismatch,
                "cnt_missing_local": r.cnt_missing_local,
                "error_message": r.error_message,
                "duration_ms": r.duration_ms,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in items
        ],
        page, page_size, total,
    )


@router.get("/reconciliation/runs/{run_id}/results", summary="对账差异明细分页")
async def list_reconciliation_results(
    run_id: str,
    status: str | None = Query(default=None, description="missing_in_feishu/mismatch/missing_local"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:intelligence:read")),
) -> JSONResponse:
    items, total = await reconciliation_service.list_results(
        db, run_id=run_id, status=status, page=page, page_size=page_size
    )
    return paginated_response(
        [
            {
                "id": str(r.id),
                "status": r.status,
                "material_code": r.material_code,
                "material_name": r.material_name,
                "batch_no": r.batch_no,
                "local_qty": float(r.local_qty) if r.local_qty is not None else None,
                "feishu_qty": float(r.feishu_qty) if r.feishu_qty is not None else None,
                "repair_status": r.repair_status,
                "repaired_at": r.repaired_at.isoformat() if r.repaired_at else None,
                "detail": r.detail,
            }
            for r in items
        ],
        page, page_size, total,
    )


@router.post("/reconciliation/results/{result_id}/repair", summary="按 Base 修复本地（人工一键）")
async def repair_reconciliation_result(
    result_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:intelligence:update")),
) -> JSONResponse:
    """裁决反转（2B：Base 胜出）的人工一键修复：

    - mismatch → 本地聚合数量调整为 Base 值；
    - missing_local → 按 Base 记录补建本地库存行；
    - missing_in_feishu → 仅置「待人工处置」（不删数据，删除属红区）。
    """
    try:
        result = await reconciliation_service.apply_base_repair(
            db, result_id, operator_id=str(user.id) if user else None
        )
    except reconciliation_service.ReconciliationRepairError as exc:
        message = str(exc)
        # 仅「行不存在/ID 无效」为 404；其余（已处理/前置缺失/负数调整）为 409
        status_code = 404 if message.startswith(("差异行不存在", "差异行 ID 无效")) else 409
        raise HTTPException(status_code=status_code, detail=message) from exc
    await db.commit()
    return success_response(
        {
            "id": str(result.id),
            "status": result.status,
            "material_code": result.material_code,
            "batch_no": result.batch_no,
            "repair_status": result.repair_status,
            "repaired_at": result.repaired_at.isoformat() if result.repaired_at else None,
        },
        message="已按 Base 修复本地"
        if result.repair_status == reconciliation_service.REPAIR_STATUS_REPAIRED
        else "已标记待人工处置",
    )
