"""岗位需求接口"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.hr.schemas import (
    JobRequirementCreate,
    JobRequirementResponse,
    JobRequirementUpdate,
)
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


@router.get("/job-requirements/{req_id}/candidates/comparison", summary="候选人横向对比")
async def compare_candidates(req_id: UUID, session: AsyncSession = Depends(get_db)):
    from app.modules.hr.repository import (
        CandidateAiEvaluationRepository,
        CandidateRepository,
        InterviewRepository,
    )
    from app.modules.hr.schemas import (
        AiEvaluationResponse,
        CandidateResponse,
        InterviewResponse,
    )

    candidate_repo = CandidateRepository(session)
    eval_repo = CandidateAiEvaluationRepository(session)
    interview_repo = InterviewRepository(session)

    candidates, _ = await candidate_repo.list_all(job_requirement_id=req_id, page_size=200)
    # 批量预取评价和面试记录，避免 N+1
    candidate_ids = [c.id for c in candidates]
    eval_map = await eval_repo.get_by_candidate_ids(candidate_ids) if candidate_ids else {}
    interview_map = await interview_repo.list_by_candidate_ids(candidate_ids) if candidate_ids else {}
    result = []
    for c in candidates:
        ev = eval_map.get(c.id)
        interviews = interview_map.get(c.id, [])
        result.append({
            "candidate": CandidateResponse.model_validate(c).model_dump(mode="json"),
            "evaluation": AiEvaluationResponse.model_validate(ev).model_dump(mode="json") if ev else None,
            "interviews": [InterviewResponse.model_validate(iv).model_dump(mode="json") for iv in interviews],
        })

    # 按AI综合评分降序，无评分排最后
    def _score(item: dict) -> float:
        ev = item.get("evaluation")
        if not ev:
            return -1.0
        try:
            return float(ev.get("overall_score", 0) or 0)
        except (ValueError, TypeError):
            return -1.0
    result.sort(key=_score, reverse=True)
    return success_response(data=result)
