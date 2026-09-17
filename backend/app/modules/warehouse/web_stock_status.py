"""库存状态变更路由（分期D Ticket 03 → V3.0 分期A Ticket 06 先 Base 后镜像）。

合法流转校验保留；落库改走 base_mirror（先写 material_receipt.上一状态，
成功后本地状态+日志；Base 失败整单失败、本地零变更，返回 502 明确报错）。
本地库存状态机降级为「操作镜像+展示」（2B 定案）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.warehouse import base_mirror
from app.modules.warehouse.models import WarehouseStock
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission

router = APIRouter()

# 库存状态取值（路由查询参数与请求体共用同一白名单）
STOCK_STATUS_PATTERN = "^(normal|quarantine|frozen)$"

# 合法状态流转：normal↔quarantine、quarantine→frozen、frozen→normal；
# normal 与 frozen 之间禁止直接跳转。
_LEGAL_TRANSITIONS = {
    ("normal", "quarantine"),
    ("quarantine", "normal"),
    ("quarantine", "frozen"),
    ("frozen", "normal"),
}


class StockStatusRequest(BaseModel):
    new_status: str = Field(..., pattern=STOCK_STATUS_PATTERN, description="目标状态")
    reason: str = Field(default="", max_length=500, description="变更原因")


@router.post("/stocks/{stock_id}/status", summary="变更库存状态")
async def change_stock_status(
    stock_id: str,
    payload: StockStatusRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:intelligence:update")),
) -> JSONResponse:
    stock = (
        await db.execute(
            select(WarehouseStock).where(
                WarehouseStock.id == stock_id, WarehouseStock.is_deleted == False  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if stock is None:
        return JSONResponse(status_code=404, content={"code": 404, "message": "库存行不存在"})

    old = stock.status
    new = payload.new_status
    if (old, new) not in _LEGAL_TRANSITIONS:
        return JSONResponse(
            status_code=400,
            content={"code": 400, "message": f"不允许从 {old} 变更为 {new}"},
        )

    try:
        # 先写 Base（material_receipt.上一状态），成功后 helper 内落本地状态+日志
        await base_mirror.apply_stock_status_base_first(
            db, stock, new, reason=payload.reason, operator_id=user.id if user else None
        )
    except base_mirror.BaseMirrorError as exc:
        await db.rollback()
        return JSONResponse(
            status_code=502,
            content={"code": 502, "message": f"Base 台账写入失败，本地未变更：{exc}"},
        )
    await db.commit()
    return success_response({"id": str(stock.id), "old_status": old, "new_status": new})
