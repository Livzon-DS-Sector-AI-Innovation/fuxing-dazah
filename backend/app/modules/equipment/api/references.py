"""设备跨模块引用授权 API。"""

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.equipment.deps import (
    EquipmentAccessContext,
    require_equipment_reference_access,
)
from app.modules.equipment.schemas.reference import (
    EquipmentReferenceGrantRequest,
    EquipmentReferenceGrantResponse,
    EquipmentReferenceResponse,
    EquipmentReferenceRevokeRequest,
    EquipmentReferenceTargetModuleResponse,
)
from app.modules.equipment.service import reference as reference_service
from app.modules.equipment.service.reference import EquipmentReference

router = APIRouter(tags=["设备-跨模块引用"])


def _reference_response(reference: EquipmentReference) -> EquipmentReferenceResponse:
    """将公共 DTO 转为 HTTP 响应，避免把内部对象字段整体透出。"""
    return EquipmentReferenceResponse(
        id=reference.id,
        equipment_no=reference.equipment_no,
        name=reference.name,
        status=reference.status,
        is_active=reference.is_active,
        source=reference.source,
    )


@router.get(
    "/references/targets",
    summary="获取设备引用目标模块",
)
async def list_reference_targets(
    ctx: EquipmentAccessContext = Depends(require_equipment_reference_access()),
) -> JSONResponse:
    del ctx  # 权限依赖用于保护设备授权管理页面
    modules = reference_service.list_reference_target_modules()
    return success_response(
        data=[EquipmentReferenceTargetModuleResponse(**module) for module in modules]
    )


@router.get(
    "/references/equipment",
    summary="查询可授权设备摘要",
)
async def list_reference_equipment_options(
    target_module: str = Query(..., min_length=1),
    keyword: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(require_equipment_reference_access()),
) -> JSONResponse:
    references, total = await reference_service.list_equipment_references(
        db,
        ctx,
        target_module,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return paginated_response(
        data=[_reference_response(reference) for reference in references],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get(
    "/references/grants",
    summary="查询设备引用授权",
)
async def list_reference_grants(
    target_module: str = Query(..., min_length=1),
    equipment_ids: list[uuid.UUID] | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(require_equipment_reference_access()),
) -> JSONResponse:
    grants = await reference_service.get_reference_grants(
        db, ctx, target_module, equipment_ids
    )
    return success_response(
        data=[EquipmentReferenceGrantResponse.model_validate(grant) for grant in grants]
    )


@router.post(
    "/references/grants",
    summary="批量授权设备给业务模块",
)
async def grant_references(
    data: EquipmentReferenceGrantRequest,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(require_equipment_reference_access()),
) -> JSONResponse:
    grants = await reference_service.grant_equipment_references(
        db,
        ctx,
        data.target_module,
        data.equipment_ids,
        remark=data.remark,
    )
    return success_response(
        data=[EquipmentReferenceGrantResponse.model_validate(grant) for grant in grants]
    )


@router.post(
    "/references/grants/revoke",
    summary="批量撤销设备引用授权",
)
async def revoke_references(
    data: EquipmentReferenceRevokeRequest,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(require_equipment_reference_access()),
) -> JSONResponse:
    grants = await reference_service.revoke_equipment_references(
        db,
        ctx,
        data.target_module,
        data.equipment_ids,
    )
    return success_response(
        data=[EquipmentReferenceGrantResponse.model_validate(grant) for grant in grants]
    )


@router.delete(
    "/references/grants",
    summary="撤销设备引用授权",
)
async def delete_references(
    data: EquipmentReferenceRevokeRequest,
    db: AsyncSession = Depends(get_db),
    ctx: EquipmentAccessContext = Depends(require_equipment_reference_access()),
) -> JSONResponse:
    """DELETE 别名，兼容偏好 REST 删除语义的客户端。"""
    return await revoke_references(data, db, ctx)


__all__ = ["router"]
