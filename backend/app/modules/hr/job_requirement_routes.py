"""岗位需求接口"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.hr.schemas import JobRequirementCreate, JobRequirementResponse, JobRequirementUpdate
from app.modules.hr.service import JobRequirementService

router = APIRouter(tags=["HR-岗位需求"])


def get_service(session: AsyncSession = Depends(get_db)) -> JobRequirementService:
    return JobRequirementService(session)


@router.get("/job-requirements", summary="岗位需求列表")
async def list_job_reqs(service: JobRequirementService = Depends(get_service)):
    rows = await service.list_all()
    return success_response(data=[JobRequirementResponse.model_validate(r).model_dump(mode="json") for r in rows])


@router.post("/job-requirements", summary="创建岗位需求")
async def create_job_req(payload: JobRequirementCreate, service: JobRequirementService = Depends(get_service)):
    r = await service.create(payload)
    return success_response(data=JobRequirementResponse.model_validate(r).model_dump(mode="json"), message="创建成功", status_code=201)


@router.put("/job-requirements/{req_id}", summary="更新岗位需求")
async def update_job_req(req_id: UUID, payload: JobRequirementUpdate, service: JobRequirementService = Depends(get_service)):
    r = await service.update(req_id, payload)
    return success_response(data=JobRequirementResponse.model_validate(r).model_dump(mode="json"), message="已更新")


@router.delete("/job-requirements/{req_id}", summary="删除岗位需求")
async def delete_job_req(req_id: UUID, service: JobRequirementService = Depends(get_service)):
    await service.delete(req_id)
    return success_response(message="已删除")
