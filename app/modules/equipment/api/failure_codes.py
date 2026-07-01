"""故障代码 API 路由."""

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.equipment import service
from app.modules.equipment.deps import EquipmentAccessContext, require_equipment_access
from app.modules.equipment.models import FailureAction, FailureCause, FailureSymptom
from app.modules.equipment.schemas import (
    FailureCodeCreate,
    FailureCodeResponse,
    FailureCodeUpdate,
)

router = APIRouter()


def _register_failure_code_routes(
    path: str,
    model_class: type,
    summary_prefix: str,
) -> None:
    """注册故障代码 CRUD 路由"""

    @router.post(f"/{path}", summary=f"新增{summary_prefix}")
    async def create(
        data: FailureCodeCreate,
        db: AsyncSession = Depends(get_db),
        ctx: EquipmentAccessContext = Depends(
            require_equipment_access("equipment:maintenance:update"),
        ),
    ) -> JSONResponse:
        result = await service.create_failure_code(db, model_class, data)
        return success_response(data=FailureCodeResponse.model_validate(result))

    @router.get(f"/{path}", summary=f"查询{summary_prefix}列表")
    async def list_codes(
        db: AsyncSession = Depends(get_db),
        ctx: EquipmentAccessContext = Depends(
            require_equipment_access("equipment:maintenance:read"),
        ),
    ) -> JSONResponse:
        codes = await service.get_failure_codes(db, model_class)
        return success_response(
            data=[FailureCodeResponse.model_validate(c) for c in codes]
        )

    @router.get(
        f"/{path}/{{code_id}}", summary=f"查询单个{summary_prefix}"
    )
    async def get_one(
        code_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        ctx: EquipmentAccessContext = Depends(
            require_equipment_access("equipment:maintenance:read"),
        ),
    ) -> JSONResponse:
        result = await service.get_failure_code_by_id(db, model_class, code_id)
        return success_response(data=FailureCodeResponse.model_validate(result))

    @router.put(
        f"/{path}/{{code_id}}", summary=f"修改{summary_prefix}"
    )
    async def update(
        code_id: uuid.UUID,
        data: FailureCodeUpdate,
        db: AsyncSession = Depends(get_db),
        ctx: EquipmentAccessContext = Depends(
            require_equipment_access("equipment:maintenance:update"),
        ),
    ) -> JSONResponse:
        result = await service.update_failure_code(db, model_class, code_id, data)
        return success_response(data=FailureCodeResponse.model_validate(result))

    @router.delete(
        f"/{path}/{{code_id}}", summary=f"删除{summary_prefix}"
    )
    async def delete(
        code_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        ctx: EquipmentAccessContext = Depends(
            require_equipment_access("equipment:maintenance:update"),
        ),
    ) -> JSONResponse:
        await service.delete_failure_code(db, model_class, code_id)
        return success_response(message="删除成功")


_register_failure_code_routes("symptoms", FailureSymptom, "故障现象")
_register_failure_code_routes("causes", FailureCause, "故障原因")
_register_failure_code_routes("actions", FailureAction, "维修措施")
