"""维修人员 API 路由."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core.config import Settings, get_settings
from app.core.response import success_response
from app.platform.integrations.feishu.contact import get_department_members

router = APIRouter()


@router.get("/maintainers", summary="获取设备部维修人员列表")
async def list_maintainers(
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    dept_id = settings.FEISHU_EQUIPMENT_DEPT_ID
    if not dept_id:
        return success_response(data=[])

    members = await get_department_members(dept_id)
    return success_response(data=members)
