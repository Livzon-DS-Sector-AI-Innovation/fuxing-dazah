"""设备台账 API 路由."""

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser
from app.core.response import paginated_response, success_response
from app.modules.equipment import repository as repo
from app.modules.equipment import service
from app.modules.equipment.schemas import (
    EquipmentCategoryCreate,
    EquipmentCategoryResponse,
    EquipmentCategoryTree,
    EquipmentCategoryUpdate,
    EquipmentCreate,
    EquipmentResponse,
    EquipmentStatistics,
    EquipmentUpdate,
    LocationCreate,
    LocationResponse,
    LocationTree,
    LocationUpdate,
)

router = APIRouter()


async def _equipment_to_response(equipment, db=None) -> EquipmentResponse:
    """将 ORM Equipment 转为响应对象，填充多分类信息及部门信息"""
    resp = EquipmentResponse.model_validate(equipment)
    links = getattr(equipment, "category_links", []) or []
    resp.category_ids = [link.category_id for link in links if not link.is_deleted]
    names = [link.category.name for link in links if not link.is_deleted and link.category]
    resp.category_names = "、".join(names) if names else None
    # 填充部门信息
    if equipment.department_id and db:
        dept_info = await repo.get_department_info(db, equipment.department_id)
        if dept_info:
            resp.department_name = dept_info["name"]
            # 负责人：优先用设备独立设置的 responsible_person_id；否则由部门负责人推导
            if not equipment.responsible_person_id:
                resp.responsible_person_name = dept_info["leader_name"]
                resp.responsible_person_id = dept_info.get("leader_id")
    # 负责人名称：如果独立设置了 responsible_person_id，从用户表查找
    if equipment.responsible_person_id and db:
        resp.responsible_person_name = await repo.get_user_name_by_id(
            db, equipment.responsible_person_id
        )
    return resp


# ==================== 设备分类 ====================
@router.post("/categories", summary="创建设备分类")
async def create_equipment_category(
    data: EquipmentCategoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    """创建设备分类"""
    category = await service.create_equipment_category(db, data)
    return success_response(data=EquipmentCategoryResponse.model_validate(category))


@router.get("/categories", summary="获取设备分类列表")
async def get_equipment_categories(
    parent_id: uuid.UUID | None = Query(None, description="父分类ID"),
    tree: bool = Query(False, description="是否返回树形结构"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """获取设备分类列表"""
    if tree:
        categories = await service.get_equipment_category_tree(db)
        return success_response(
            data=[EquipmentCategoryTree.model_validate(c) for c in categories]
        )
    categories = await service.get_equipment_categories(db, parent_id)
    return success_response(
        data=[EquipmentCategoryResponse.model_validate(c) for c in categories]
    )


@router.get("/categories/{category_id}", summary="获取设备分类详情")
async def get_equipment_category(
    category_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """获取设备分类详情"""
    category = await service.get_equipment_category_by_id(db, category_id)
    return success_response(data=EquipmentCategoryResponse.model_validate(category))


@router.put("/categories/{category_id}", summary="更新设备分类")
async def update_equipment_category(
    category_id: uuid.UUID,
    data: EquipmentCategoryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    """更新设备分类"""
    category = await service.update_equipment_category(db, category_id, data)
    return success_response(data=EquipmentCategoryResponse.model_validate(category))


@router.delete("/categories/{category_id}", summary="删除设备分类")
async def delete_equipment_category(
    category_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    """删除设备分类"""
    await service.delete_equipment_category(db, category_id)
    return success_response(message="删除成功")


# ==================== 位置管理 ====================
@router.post("/locations", summary="创建位置")
async def create_location(
    data: LocationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    """创建位置"""
    location = await service.create_location(db, data)
    return success_response(data=LocationResponse.model_validate(location))


@router.get("/locations", summary="获取位置列表")
async def get_locations(
    parent_id: uuid.UUID | None = Query(None, description="父位置ID"),
    tree: bool = Query(False, description="是否返回树形结构"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """获取位置列表"""
    if tree:
        locations = await service.get_location_tree(db)
        return success_response(
            data=[LocationTree.model_validate(loc) for loc in locations]
        )
    locations = await service.get_locations(db, parent_id)
    return success_response(
        data=[LocationResponse.model_validate(loc) for loc in locations]
    )


@router.get("/locations/{location_id}", summary="获取位置详情")
async def get_location(
    location_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """获取位置详情"""
    location = await service.get_location_by_id(db, location_id)
    return success_response(data=LocationResponse.model_validate(location))


@router.put("/locations/{location_id}", summary="更新位置")
async def update_location(
    location_id: uuid.UUID,
    data: LocationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    """更新位置"""
    location = await service.update_location(db, location_id, data)
    return success_response(data=LocationResponse.model_validate(location))


@router.delete("/locations/{location_id}", summary="删除位置")
async def delete_location(
    location_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    """删除位置"""
    await service.delete_location(db, location_id)
    return success_response(message="删除成功")


# ==================== 部门列表（供设备表单下拉使用） ====================
@router.get("/departments", summary="获取部门列表（供设备表单下拉使用）")
async def get_departments_list(
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """获取可选部门列表，含部门名称和负责人姓名"""
    departments = await service.get_departments_for_select(db)
    return success_response(data=departments)


# ==================== 设备管理 ====================
@router.post("/equipments", summary="创建设备")
async def create_equipment(
    data: EquipmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    """创建设备"""
    equipment = await service.create_equipment(db, data)
    return success_response(data=await _equipment_to_response(equipment, db))


@router.get("/equipments", summary="获取设备列表")
async def get_equipments(
    category_id: uuid.UUID | None = Query(None, description="设备分类ID"),
    location_id: uuid.UUID | None = Query(None, description="设备位置ID"),
    department_id: uuid.UUID | None = Query(None, description="归属部门ID"),
    status: str | None = Query(None, description="设备状态"),
    keyword: str | None = Query(None, description="关键词搜索"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=200, description="每页数量"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """获取设备列表"""
    equipments, total = await service.get_equipments(
        db, category_id, location_id, department_id, status, keyword, page, page_size
    )
    equipment_responses = []
    for e in equipments:
        equipment_responses.append(await _equipment_to_response(e, db))
    return paginated_response(
        data=equipment_responses,
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/equipments/statistics", summary="获取设备统计")
async def get_equipment_statistics(
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """获取设备统计"""
    stats = await service.get_equipment_statistics(db)
    return success_response(data=EquipmentStatistics(**stats))


@router.get("/equipments/{equipment_id}", summary="获取设备详情")
async def get_equipment(
    equipment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """获取设备详情"""
    equipment = await service.get_equipment_by_id(db, equipment_id)
    return success_response(data=await _equipment_to_response(equipment, db))


@router.put("/equipments/{equipment_id}", summary="更新设备")
async def update_equipment(
    equipment_id: uuid.UUID,
    data: EquipmentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    """更新设备"""
    equipment = await service.update_equipment(db, equipment_id, data)
    return success_response(data=await _equipment_to_response(equipment, db))


@router.delete("/equipments/{equipment_id}", summary="删除设备")
async def delete_equipment(
    equipment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    """删除设备"""
    await service.delete_equipment(db, equipment_id)
    return success_response(message="删除成功")
