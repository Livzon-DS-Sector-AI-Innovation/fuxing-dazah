"""生产-设备选项 HTTP 路由。

供生产模块前端选择设备使用。结果为调用用户在设备台账中的自有设备与
production 模块已共享设备的并集，全部经 equipment.public_api 解耦层，
不直接触碰 equipment 模块的 service/repository。
"""

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.equipment import public_api as equipment_public_api
from app.modules.production.schemas import EquipmentOptionOut
from app.platform.permission.deps import RequireUser

router = APIRouter(tags=["生产-设备选项"])


@router.get("/equipment-options", summary="当前用户可引用设备下拉选项")
async def get_equipment_options(
    current_user: RequireUser,
    db: AsyncSession = Depends(get_db),
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> JSONResponse:
    if status is None:
        # 不传 status 保持旧测试适配器及调用方的关键字签名兼容。
        equipments, total = await equipment_public_api.list_equipment_references(
            db,
            current_user,
            "production",
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
    else:
        equipments, total = await equipment_public_api.list_equipment_references(
            db,
            current_user,
            "production",
            keyword=keyword,
            status=status,
            page=page,
            page_size=page_size,
        )
    return paginated_response(
        [
            EquipmentOptionOut(
                id=e.id,
                equipment_no=e.equipment_no,
                name=e.name,
                status=getattr(e, "status", None),
                is_active=getattr(e, "is_active", True),
                source=getattr(e, "source", None),
            ).model_dump(mode="json")
            for e in equipments
        ],
        page,
        page_size,
        total,
    )


@router.get("/equipment-briefs", summary="按 ID 批量取设备摘要（表单回显用）")
async def get_equipment_briefs_by_ids(
    current_user: RequireUser,
    ids: list[uuid.UUID] = Query(...),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    # 与 equipment-options 同口径：自有范围 + production 已共享设备；越权 ID
    # 缺失于结果，避免通过回显接口探测设备是否存在。
    briefs = await equipment_public_api.get_equipment_references_by_ids(
        db, current_user, "production", ids,
    )
    return success_response(
        [
            EquipmentOptionOut(
                id=e.id,
                equipment_no=e.equipment_no,
                name=e.name,
                status=getattr(e, "status", None),
                is_active=getattr(e, "is_active", True),
                source=getattr(e, "source", None),
            ).model_dump(mode="json")
            for e in briefs
        ]
    )
