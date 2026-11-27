"""招聘岗位信息接口：岗位库每个岗位保存一份岗位职责 / 任职要求，新建岗位需求时带出复用。

权限走招聘域（查看 hr:recruitment:read、保存 hr:recruitment:manage，见 deps._HR_PATH_PERMISSIONS）；
数据范围与岗位需求一致：受部门范围限制的用户只看得到授权部门的岗位。
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.hr.deps import HrAccessContext, get_hr_scope
from app.modules.hr.schemas import RecruitmentPositionInfoUpdate
from app.modules.hr.service import RecruitmentPositionInfoService
from app.platform.audit.service import record_audit_log

router = APIRouter(tags=["HR-招聘岗位信息"])

RESOURCE_TYPE = "hr_position"


def get_service(session: AsyncSession = Depends(get_db)) -> RecruitmentPositionInfoService:
    return RecruitmentPositionInfoService(session)


@router.get("/recruitment/position-infos", summary="招聘岗位信息列表（全部岗位 + 是否已配置）")
async def list_recruitment_position_infos(
    department: str | None = Query(None, description="部门名称筛选"),
    keyword: str | None = Query(None, description="岗位名称 / 部门关键字"),
    only_missing: bool = Query(False, description="只看尚未配置招聘岗位信息的岗位"),
    service: RecruitmentPositionInfoService = Depends(get_service),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
) -> JSONResponse:
    # 数据范围收敛：受部门范围限制的只看授权部门；self_only 等无部门范围的看不到任何岗位
    departments: list[str] | None = None
    if not hr_scope.is_unrestricted:
        departments = sorted(hr_scope.scoped_departments)
    if department:
        # 指定部门仍受数据范围约束：授权范围内没有这个部门就查不到
        departments = [department] if departments is None or department in departments else []
    rows = await service.list(departments=departments, keyword=keyword, only_missing=only_missing)
    return success_response(
        data=[row.model_dump(mode="json") for row in rows],
    )


@router.get("/recruitment/position-infos/{position_id}", summary="招聘岗位信息详情")
async def get_recruitment_position_info(
    position_id: UUID,
    service: RecruitmentPositionInfoService = Depends(get_service),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
) -> JSONResponse:
    info = await service.get(position_id)
    hr_scope.ensure_can_access_department(info.department)
    return success_response(data=info.model_dump(mode="json"))


@router.put("/recruitment/position-infos/{position_id}", summary="保存招聘岗位信息")
async def save_recruitment_position_info(
    position_id: UUID,
    payload: RecruitmentPositionInfoUpdate,
    service: RecruitmentPositionInfoService = Depends(get_service),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
) -> JSONResponse:
    info = await service.get(position_id)
    hr_scope.ensure_dept_writable([info.department])
    saved = await service.save(position_id, payload, user_id=hr_scope.user.id)
    # 审计只记字数，不把整段描述再写一份
    await record_audit_log(
        service.repo.session,
        action="hr.recruitment_position_info.save",
        user=hr_scope.user,
        resource_type=RESOURCE_TYPE,
        resource_id=position_id,
        new_value={
            "department": saved.department,
            "position_name": saved.position_name,
            "duties_length": len(saved.duties or ""),
            "requirements_length": len(saved.requirements or ""),
        },
    )
    return success_response(data=saved.model_dump(mode="json"), message="招聘岗位信息已保存")
