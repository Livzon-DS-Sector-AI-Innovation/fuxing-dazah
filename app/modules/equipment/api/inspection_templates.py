"""巡检模板管理 API 路由."""

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.equipment import service
from app.modules.equipment.deps import (
    EquipmentAccessContext,
    require_equipment_access,
)
from app.modules.equipment.schemas import (
    InspectionCompleteRequest,
    InspectionTemplateCreate,
    InspectionTemplateItemCreate,
    InspectionTemplateItemUpdate,
    InspectionTemplateResponse,
    InspectionTemplateUpdate,
    WorkOrderResponse,
)

router = APIRouter()


# ---------- 巡检模板 ----------
@router.post("/", summary="新增巡检模板")
async def create_inspection_template(
    data: InspectionTemplateCreate,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:create"),
    ),
) -> JSONResponse:
    template = await service.create_inspection_template(db, data)
    return success_response(
        data=InspectionTemplateResponse.model_validate(template)
    )


@router.get("/", summary="巡检模板列表")
async def list_inspection_templates(
    equipment_category_id: uuid.UUID | None = Query(
        None, description="设备分类ID"
    ),
    is_active: bool | None = Query(None, description="是否启用"),
    keyword: str | None = Query(None, description="关键词搜索"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=200, description="每页数量"),
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:read"),
    ),
) -> JSONResponse:
    templates, total = await service.get_inspection_templates(
        db,
        equipment_category_id=equipment_category_id,
        is_active=is_active,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return paginated_response(
        data=[
            InspectionTemplateResponse.model_validate(t) for t in templates
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/{template_id}", summary="巡检模板详情")
async def get_inspection_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:read"),
    ),
) -> JSONResponse:
    template = await service.get_inspection_template_by_id(db, template_id)
    return success_response(
        data=InspectionTemplateResponse.model_validate(template)
    )


@router.put("/{template_id}", summary="修改巡检模板")
async def update_inspection_template(
    template_id: uuid.UUID,
    data: InspectionTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:update"),
    ),
) -> JSONResponse:
    template = await service.update_inspection_template(db, template_id, data)
    return success_response(
        data=InspectionTemplateResponse.model_validate(template)
    )


@router.delete("/{template_id}", summary="删除巡检模板")
async def delete_inspection_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:delete"),
    ),
) -> JSONResponse:
    await service.delete_inspection_template(db, template_id)
    return success_response(message="删除成功")


# ---------- 检查项管理 ----------
@router.post("/{template_id}/items", summary="添加检查项")
async def add_template_item(
    template_id: uuid.UUID,
    data: InspectionTemplateItemCreate,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:create"),
    ),
) -> JSONResponse:
    await service.add_template_item(db, template_id, data)
    return success_response(message="添加成功")


@router.put("/items/{item_id}", summary="修改检查项")
async def update_template_item(
    item_id: uuid.UUID,
    data: InspectionTemplateItemUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:update"),
    ),
) -> JSONResponse:
    await service.update_template_item(db, item_id, data)
    return success_response(message="修改成功")


@router.delete("/items/{item_id}", summary="删除检查项")
async def delete_template_item(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:delete"),
    ),
) -> JSONResponse:
    await service.delete_template_item(db, item_id)
    return success_response(message="删除成功")


# ---------- 巡检执行 ----------
@router.post("/complete/{work_order_id}", summary="提交巡检结果")
async def complete_inspection(
    work_order_id: uuid.UUID,
    data: InspectionCompleteRequest,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(
        require_equipment_access("equipment:maintenance:update"),
    ),
) -> JSONResponse:
    wo = await service.complete_inspection(db, work_order_id, data)
    return success_response(data=WorkOrderResponse.model_validate(wo))
