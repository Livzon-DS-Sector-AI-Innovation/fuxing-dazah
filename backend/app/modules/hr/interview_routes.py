"""面试管理 + AI 评估接口"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.hr.schemas import (
    AiEvaluationResponse,
    InterviewCreate,
    InterviewResponse,
    InterviewUpdate,
)
from app.modules.hr.service import AiEvaluationService, InterviewService

router = APIRouter(tags=["HR-面试管理"])


def get_interview_service(session: AsyncSession = Depends(get_db)) -> InterviewService:
    return InterviewService(session)


def get_ai_service(session: AsyncSession = Depends(get_db)) -> AiEvaluationService:
    return AiEvaluationService(session)


# ─── 面试 CRUD ───


@router.get("/candidates/{cid}/interviews", summary="候选人面试列表")
async def list_interviews(cid: UUID, service: InterviewService = Depends(get_interview_service)):
    rows = await service.list_by_candidate(cid)
    return success_response(data=[InterviewResponse.model_validate(r).model_dump(mode="json") for r in rows])


@router.post("/interviews", summary="安排面试")
async def create_interview(payload: InterviewCreate, service: InterviewService = Depends(get_interview_service)):
    r = await service.create(payload)
    return success_response(data=InterviewResponse.model_validate(r).model_dump(mode="json"), message="面试已安排", status_code=201)


@router.get("/interviews/{interview_id}", summary="面试详情")
async def get_interview(interview_id: UUID, service: InterviewService = Depends(get_interview_service)):
    r = await service.get(interview_id)
    return success_response(data=InterviewResponse.model_validate(r).model_dump(mode="json"))


@router.put("/interviews/{interview_id}", summary="更新面试")
async def update_interview(interview_id: UUID, payload: InterviewUpdate, service: InterviewService = Depends(get_interview_service)):
    r = await service.update(interview_id, payload)
    return success_response(data=InterviewResponse.model_validate(r).model_dump(mode="json"), message="已更新")


@router.delete("/interviews/{interview_id}", summary="取消面试")
async def delete_interview(interview_id: UUID, service: InterviewService = Depends(get_interview_service)):
    await service.delete(interview_id)
    return success_response(message="已取消")


# ─── AI 评估 ───


@router.post("/interviews/{interview_id}/evaluate", summary="AI评估面试")
async def evaluate_interview(interview_id: UUID, service: AiEvaluationService = Depends(get_ai_service)):
    try:
        r = await service.evaluate(interview_id)
        return success_response(data=AiEvaluationResponse.model_validate(r).model_dump(mode="json"), message="AI评估完成")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/interviews/{interview_id}/evaluation", summary="获取AI评估结果")
async def get_evaluation(interview_id: UUID, service: AiEvaluationService = Depends(get_ai_service)):
    r = await service.get_by_interview(interview_id)
    if not r:
        return success_response(data=None, message="尚未评估")
    return success_response(data=AiEvaluationResponse.model_validate(r).model_dump(mode="json"))
