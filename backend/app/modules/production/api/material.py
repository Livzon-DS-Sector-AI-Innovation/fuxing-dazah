"""产出物管理 API — 只做 HTTP 层。"""

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.production.service import intermediate_service
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission

router = APIRouter()


@router.get("/materials", summary="产出物列表")
async def list_materials(
    keyword: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("production:batch:read")),
) -> JSONResponse:
    items, total = await intermediate_service.list_intermediate_types_paged(
        db, keyword, page, page_size
    )
    return paginated_response(
        [it.model_dump(mode="json") for it in items],
        page,
        page_size,
        total,
    )


@router.get("/materials/{material_id}", summary="产出物详情")
async def get_material(
    material_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("production:batch:read")),
) -> JSONResponse:
    out = await intermediate_service.get_intermediate_type_detail(db, material_id)
    return success_response(data=out.model_dump(mode="json"))


@router.get("/materials/{material_id}/movements", summary="产出物出入库流水")
async def get_material_movements(
    material_id: uuid.UUID,
    batch_no: str | None = Query(default=None, description="按产出批号筛选"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("production:batch:read")),
) -> JSONResponse:
    result = await intermediate_service.get_material_movements(db, material_id, batch_no=batch_no)
    return success_response(data=result.model_dump(mode="json"))
