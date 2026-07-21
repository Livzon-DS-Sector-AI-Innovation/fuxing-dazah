"""备件管理 API 路由."""

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AppException, NotFoundException
from app.core.response import paginated_response, success_response
from app.modules.equipment import repository as repo
from app.modules.equipment import service
from app.modules.equipment.deps import (
    EquipmentAccessContext,
    require_equipment_access,
)
from app.modules.equipment.schemas import (
    EquipmentSparePartCreate,
    EquipmentSparePartResponse,
    OutboundTransactionResponse,
    SparePartCreate,
    SparePartResponse,
    SparePartUpdate,
    StockAdjustRequest,
    StockInboundRequest,
    StockResponse,
    StockWarningResponse,
)

router = APIRouter()


@router.post("/", summary="创建备件")
async def create_spare_part(
    data: SparePartCreate,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:spare_part:create"),
    ),
) -> JSONResponse:
    spare_part = await service.create_spare_part(db, data, ctx)
    return success_response(data=SparePartResponse.model_validate(spare_part))


@router.get("/", summary="备件列表")
async def list_spare_parts(
    category: str | None = Query(None, description="备件分类"),
    keyword: str | None = Query(None, description="关键词搜索"),
    is_active: bool | None = Query(None, description="是否启用"),
    department_id: uuid.UUID | None = Query(None, description="归属部门ID"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=200, description="每页数量"),
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:spare_part:read"),
    ),
) -> JSONResponse:
    spare_parts, total = await service.get_spare_parts(
        db, ctx, category=category, keyword=keyword,
        is_active=is_active, department_id=department_id,
        page=page, page_size=page_size,
    )
    return paginated_response(
        data=[SparePartResponse.model_validate(sp) for sp in spare_parts],
        page=page, page_size=page_size, total=total,
    )


@router.get("/stock/warnings", summary="库存预警列表")
async def get_stock_warnings(
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:spare_part:read"),
    ),
) -> JSONResponse:
    warnings = await service.get_stock_warnings(db)
    return success_response(
        data=[
            StockWarningResponse(
                spare_part=SparePartResponse.model_validate(w["spare_part"]),
                stock=StockResponse.model_validate(w["stock"]),
                shortage=w["shortage"],
            )
            for w in warnings
        ]
    )


@router.get("/transactions", summary="消耗流水")
async def list_outbound_transactions(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=200, description="每页数量"),
    transaction_type: str | None = Query(None, description="类型筛选：入库/出库"),
    keyword: str | None = Query(None, description="备件名称搜索"),
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:spare_part:read"),
    ),
) -> JSONResponse:
    rows, total = await repo.get_outbound_transactions(
        db, ctx, page=page, page_size=page_size,
        transaction_type=transaction_type, keyword=keyword,
    )
    return paginated_response(
        data=[OutboundTransactionResponse(**row) for row in rows],
        page=page, page_size=page_size, total=total,
    )


@router.get("/{spare_part_id}/equipments", summary="查看备件关联的设备")
async def get_spare_part_equipments(
    spare_part_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:spare_part:read"),
    ),
) -> JSONResponse:
    links = await repo.get_spare_part_equipments(db, spare_part_id)
    results = []
    for link in links:
        eq = link.equipment
        results.append({
            "id": str(link.id),
            "equipment_id": str(link.equipment_id),
            "spare_part_id": str(link.spare_part_id),
            "quantity": link.quantity,
            "equipment_no": eq.equipment_no if eq else None,
            "equipment_name": eq.name if eq else None,
        })
    return success_response(data=results)


@router.post("/{spare_part_id}/equipments", summary="绑定备件到设备")
async def link_spare_part_equipment(
    spare_part_id: uuid.UUID,
    data: EquipmentSparePartCreate,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:spare_part:update"),
    ),
) -> JSONResponse:
    from sqlalchemy.exc import IntegrityError

    try:
        link = await repo.create_equipment_spare_part(db, {
            "equipment_id": data.equipment_id,
            "spare_part_id": spare_part_id,
            "quantity": data.quantity,
        })
        return success_response(data=EquipmentSparePartResponse.model_validate(link))
    except IntegrityError:
        await db.rollback()
        raise AppException(message="该设备已关联此备件，请勿重复添加")


@router.delete("/{spare_part_id}/equipments/{link_id}", summary="解绑设备关联")
async def unlink_spare_part_equipment(
    spare_part_id: uuid.UUID,
    link_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:spare_part:update"),
    ),
) -> JSONResponse:
    ok = await repo.delete_equipment_spare_part(db, link_id)
    if not ok:
        raise NotFoundException("关联记录", str(link_id))
    return success_response(message="解绑成功")


@router.get("/{spare_part_id}", summary="备件详情")
async def get_spare_part(
    spare_part_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:spare_part:read"),
    ),
) -> JSONResponse:
    spare_part = await service.get_spare_part_by_id(db, spare_part_id)
    return success_response(data=SparePartResponse.model_validate(spare_part))


@router.put("/{spare_part_id}", summary="更新备件")
async def update_spare_part(
    spare_part_id: uuid.UUID,
    data: SparePartUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:spare_part:update"),
    ),
) -> JSONResponse:
    spare_part = await service.update_spare_part(
        db, spare_part_id, data, ctx,
    )
    return success_response(data=SparePartResponse.model_validate(spare_part))


@router.delete("/{spare_part_id}", summary="删除备件")
async def delete_spare_part(
    spare_part_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:spare_part:delete"),
    ),
) -> JSONResponse:
    await service.delete_spare_part(db, spare_part_id, ctx)
    return success_response(message="删除成功")


@router.get("/{spare_part_id}/stock", summary="查看库存")
async def get_stock(
    spare_part_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:spare_part:read"),
    ),
) -> JSONResponse:
    stock = await service.get_stock_by_spare_part_id(db, spare_part_id)
    return success_response(data=StockResponse.model_validate(stock))


@router.post("/{spare_part_id}/stock/inbound", summary="入库")
async def inbound_stock(
    spare_part_id: uuid.UUID,
    data: StockInboundRequest,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:spare_part:update"),
    ),
) -> JSONResponse:
    stock = await service.inbound_stock(db, spare_part_id, data, ctx)
    return success_response(data=StockResponse.model_validate(stock))


@router.post("/{spare_part_id}/stock/adjust", summary="盘点调整")
async def adjust_stock(
    spare_part_id: uuid.UUID,
    data: StockAdjustRequest,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:spare_part:update"),
    ),
) -> JSONResponse:
    stock = await service.adjust_stock(db, spare_part_id, data, ctx)
    return success_response(data=StockResponse.model_validate(stock))
