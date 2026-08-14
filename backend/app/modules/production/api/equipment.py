"""生产-设备选项 HTTP 路由。

供生产模块前端选择设备使用。设备数据范围按调用用户在设备台账的
可见范围过滤，全部经 equipment.public_api 解耦层，不直接触碰
equipment 模块的 service/repository。
"""

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.equipment.public_api import (
    get_equipment_briefs,
    list_equipments_for_user,
)
from app.modules.production.schemas import EquipmentOptionOut
from app.platform.permission.deps import RequireUser

router = APIRouter(tags=["生产-设备选项"])


@router.get("/equipment-options", summary="当前用户可见设备下拉选项")
async def get_equipment_options(
    current_user: RequireUser,
    db: AsyncSession = Depends(get_db),
    keyword: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> JSONResponse:
    equipments, total = await list_equipments_for_user(
        db, current_user, keyword=keyword, page=page, page_size=page_size,
    )
    return paginated_response(
        [
            EquipmentOptionOut(
                id=e.id, equipment_no=e.equipment_no, name=e.name,
            ).model_dump(mode="json")
            for e in equipments
        ],
        page,
        page_size,
        total,
    )


@router.get("/equipment-briefs", summary="按 ID 批量取设备摘要（表单回显用）")
async def get_equipment_briefs_by_ids(
    _current_user: RequireUser,  # 仅鉴权，无数据范围过滤
    ids: list[uuid.UUID] = Query(...),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    briefs = await get_equipment_briefs(db, ids)
    return success_response(
        [
            EquipmentOptionOut(
                id=e.id, equipment_no=e.equipment_no, name=e.name,
            ).model_dump(mode="json")
            for e in briefs
        ]
    )
