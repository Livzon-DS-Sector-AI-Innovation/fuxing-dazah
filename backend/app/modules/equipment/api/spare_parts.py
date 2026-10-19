"""备件管理 API 路由."""

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
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
    StockOutboundRequest,
    StockResponse,
    StockSettingsRequest,
)
from app.modules.equipment.service import IMPORT_MODE_ACCUMULATE

logger = logging.getLogger(__name__)

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
    low_stock: bool | None = Query(None, description="库存状态：true=低于安全线"),
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
        is_active=is_active, low_stock=low_stock, department_id=department_id,
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
    warnings = await service.get_stock_warnings(db, ctx)
    return success_response(data=warnings)


@router.get("/transactions", summary="消耗流水")
async def list_outbound_transactions(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=200, description="每页数量"),
    transaction_type: str | None = Query(
        None, description="类型筛选：入库/出库/盘点调整；不传返回全部"
    ),
    keyword: str | None = Query(None, description="备件编码/名称搜索"),
    spare_part_id: uuid.UUID | None = Query(None, description="按备件过滤"),
    date_from: datetime | None = Query(None, description="起始时间"),
    date_to: datetime | None = Query(None, description="截止时间"),
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:spare_part:read"),
    ),
) -> JSONResponse:
    rows, total = await repo.get_outbound_transactions(
        db, ctx, page=page, page_size=page_size,
        transaction_type=transaction_type, keyword=keyword,
        spare_part_id=spare_part_id, date_from=date_from, date_to=date_to,
    )
    return paginated_response(
        data=[OutboundTransactionResponse(**row) for row in rows],
        page=page, page_size=page_size, total=total,
    )


# ==================== Excel 导入 ====================
@router.get("/import/template", summary="下载备件导入模板")
async def download_spare_part_import_template(
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:spare_part:create"),
    ),
) -> StreamingResponse:
    """下载备件 Excel 导入模板"""
    buf = service.generate_spare_part_template_bytes()
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''%E5%A4%87%E4%BB%B6%E5%AF%BC%E5%85%A5%E6%A8%A1%E6%9D%BF.xlsx"
        },
    )


@router.post("/import", summary="批量导入备件")
async def import_spare_parts(
    file: UploadFile = File(..., description="Excel 文件（.xlsx）"),
    mode: str = Form(
        IMPORT_MODE_ACCUMULATE,
        description="已有编码的处理方式：accumulate=累加入库（默认），overwrite=以表格为准覆盖",
    ),
    db: AsyncSession = Depends(get_db),
    ctx_update: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:spare_part:update"),
    ),
    ctx_create: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:spare_part:create"),
    ),
) -> JSONResponse:
    """从 Excel 文件批量导入备件。

    导入既会新建备件（create）也会写已有备件的库存与主数据（update），
    因此要求 create + update 双权限。
    """
    ctx = ctx_update
    if not file.filename or not file.filename.endswith(".xlsx"):
        return JSONResponse(
            status_code=400,
            content={"message": "仅支持 .xlsx 格式的 Excel 文件"},
        )
    try:
        file_bytes = await file.read()
        result = await service.import_spare_parts_from_excel(
            db, file_bytes, ctx=ctx, mode=mode,
        )
        await db.commit()
        return success_response(data=result.model_dump())
    except ValueError as e:
        logger.warning("备件 Excel 导入失败: %s", e)
        return JSONResponse(status_code=400, content={"message": str(e)})


@router.get("/{spare_part_id}/equipments", summary="查看备件关联的设备")
async def get_spare_part_equipments(
    spare_part_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:spare_part:read"),
    ),
) -> JSONResponse:
    await service.ensure_spare_part_readable(db, spare_part_id, ctx)
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
        logger.warning(
            "备件关联设备失败: spare_part_id=%s equipment_id=%s",
            spare_part_id, data.equipment_id,
        )
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
    spare_part = await service.get_spare_part_detail(db, spare_part_id, ctx)
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
    stock = await service.get_stock_with_access(db, spare_part_id, ctx)
    return success_response(data=StockResponse.model_validate(stock))


@router.put("/{spare_part_id}/stock/settings", summary="库存设置（安全库存/最小采购批量/库位）")
async def update_stock_settings(
    spare_part_id: uuid.UUID,
    data: StockSettingsRequest,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:spare_part:update"),
    ),
) -> JSONResponse:
    stock = await service.update_stock_settings(db, spare_part_id, data, ctx)
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


@router.post("/{spare_part_id}/stock/outbound", summary="出库（手动领用/报废）")
async def outbound_stock(
    spare_part_id: uuid.UUID,
    data: StockOutboundRequest,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:spare_part:update"),
    ),
) -> JSONResponse:
    stock = await service.outbound_stock(db, spare_part_id, data, ctx)
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
