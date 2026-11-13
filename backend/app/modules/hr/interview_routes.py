"""面试管理 + AI 评估接口

AI 评估已统一到胜任度报告（CandidateAnalysisReport）：
- POST /interviews/{id}/evaluate 生成该面试的胜任度报告
- GET  /interviews/{id}/evaluation 返回该面试的最新报告
原六维打分卡（CandidateAiEvaluation）代码路径已下线，历史数据保留只读
（候选人对比端点仍读旧表）。
"""

import logging
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.hr.deps import HrAccessContext, require_hr_access
from app.modules.hr.schemas import (
    CandidateAnalysisReportOut,
    InterviewCreate,
    InterviewFeedbackIn,
    InterviewFeedbackOut,
    InterviewResponse,
    InterviewUpdate,
)
from app.modules.hr.service import (
    CandidateAnalysisService,
    InterviewFeedbackService,
    InterviewService,
)

router = APIRouter(tags=["HR-面试管理"])

logger = logging.getLogger(__name__)


def get_interview_service(session: AsyncSession = Depends(get_db)) -> InterviewService:
    return InterviewService(session)


def get_analysis_service(session: AsyncSession = Depends(get_db)) -> CandidateAnalysisService:
    return CandidateAnalysisService(session)


# ─── 面试 CRUD ───


@router.get("/candidates/{cid}/interviews", summary="候选人面试列表")
async def list_interviews(cid: UUID, service: InterviewService = Depends(get_interview_service), ctx: HrAccessContext = Depends(require_hr_access("hr:recruitment:read"))):
    rows = await service.list_by_candidate(cid)
    return success_response(data=[InterviewResponse.model_validate(r).model_dump(mode="json") for r in rows])


@router.post("/interviews", summary="安排面试")
async def create_interview(payload: InterviewCreate, background_tasks: BackgroundTasks, service: InterviewService = Depends(get_interview_service), ctx: HrAccessContext = Depends(require_hr_access("hr:recruitment:manage"))):
    r = await service.create(payload, operator=ctx.user.id, operator_name=ctx.user.name)
    _schedule_analysis(background_tasks, r)
    return success_response(data=InterviewResponse.model_validate(r).model_dump(mode="json"), message="面试已安排", status_code=201)


@router.get("/interviews/{interview_id}", summary="面试详情")
async def get_interview(interview_id: UUID, service: InterviewService = Depends(get_interview_service), ctx: HrAccessContext = Depends(require_hr_access("hr:recruitment:read"))):
    r = await service.get(interview_id)
    return success_response(data=InterviewResponse.model_validate(r).model_dump(mode="json"))


@router.put("/interviews/{interview_id}", summary="更新面试")
async def update_interview(interview_id: UUID, payload: InterviewUpdate, background_tasks: BackgroundTasks, service: InterviewService = Depends(get_interview_service), ctx: HrAccessContext = Depends(require_hr_access("hr:recruitment:manage"))):
    old = await service.get(interview_id)
    # 先快照旧值：service.update 后 old 与 result 是同一 ORM 实例（身份映射），
    # 事后比较会变成「新值 vs 新值」恒相等
    old_transcript = (old.transcript_text or "").strip()
    old_notes = (old.notes or "").strip()
    r = await service.update(interview_id, payload, operator=ctx.user.id, operator_name=ctx.user.name)
    # 仅在逐字稿/备注实际变化时才触发 AI 报告重生成——
    # 否则改个面试状态也会烧一次 LLM 调用
    fields = payload.model_dump(exclude_unset=True)
    content_changed = any(
        (fields.get(f) or "").strip() != old_value
        for f, old_value in (("transcript_text", old_transcript), ("notes", old_notes))
        if f in fields
    )
    if content_changed:
        _schedule_analysis(background_tasks, r)
    return success_response(data=InterviewResponse.model_validate(r).model_dump(mode="json"), message="已更新")


@router.delete("/interviews/{interview_id}", summary="取消面试")
async def delete_interview(interview_id: UUID, service: InterviewService = Depends(get_interview_service), ctx: HrAccessContext = Depends(require_hr_access("hr:recruitment:manage"))):
    await service.delete(interview_id, operator=ctx.user.id, operator_name=ctx.user.name)
    return success_response(message="已取消")


# ─── 人工面试评价 ───


def get_feedback_service(session: AsyncSession = Depends(get_db)) -> InterviewFeedbackService:
    return InterviewFeedbackService(session)


@router.post("/interviews/{interview_id}/feedback", summary="提交/更新面试评价")
async def submit_feedback(
    interview_id: UUID,
    payload: InterviewFeedbackIn,
    service: InterviewFeedbackService = Depends(get_feedback_service),
    ctx: HrAccessContext = Depends(require_hr_access("hr:recruitment:manage")),
):
    fb = await service.upsert(interview_id, payload, operator=ctx.user.id)
    return success_response(
        data=InterviewFeedbackOut.model_validate(fb).model_dump(mode="json"),
        message="面试评价已保存",
    )


@router.get("/interviews/{interview_id}/feedback", summary="获取面试评价")
async def get_feedback(
    interview_id: UUID,
    service: InterviewFeedbackService = Depends(get_feedback_service),
    ctx: HrAccessContext = Depends(require_hr_access("hr:recruitment:read")),
):
    fb = await service.get_by_interview(interview_id)
    if not fb:
        return success_response(data=None, message="尚未评价")
    return success_response(data=InterviewFeedbackOut.model_validate(fb).model_dump(mode="json"))


# ─── AI 评估（统一走胜任度报告） ───


@router.post("/interviews/{interview_id}/evaluate", summary="AI评估面试（生成胜任度报告）")
async def evaluate_interview(
    interview_id: UUID,
    iv_service: InterviewService = Depends(get_interview_service),
    service: CandidateAnalysisService = Depends(get_analysis_service),
    ctx: HrAccessContext = Depends(require_hr_access("hr:recruitment:manage")),
):
    interview = await iv_service.get(interview_id)
    try:
        report = await service.generate(interview.candidate_id, interview_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return success_response(
        data=CandidateAnalysisReportOut.model_validate(report).model_dump(mode="json"),
        message="胜任度报告已生成",
    )


@router.get("/interviews/{interview_id}/evaluation", summary="获取AI评估结果（胜任度报告）")
async def get_evaluation(
    interview_id: UUID,
    service: CandidateAnalysisService = Depends(get_analysis_service),
    ctx: HrAccessContext = Depends(require_hr_access("hr:recruitment:read")),
):
    r = await service.get_by_interview(interview_id)
    if not r:
        return success_response(data=None, message="尚未生成报告")
    return success_response(data=CandidateAnalysisReportOut.model_validate(r).model_dump(mode="json"))


def _schedule_analysis(background_tasks: BackgroundTasks, interview) -> None:
    """面试记录含逐字稿/备注时，后台任务生成胜任度报告（响应不等待 LLM，最长 90s）。"""
    if not ((interview.transcript_text or "").strip() or (interview.notes or "").strip()):
        return
    background_tasks.add_task(_generate_analysis_background, interview.candidate_id, interview.id)


async def _generate_analysis_background(candidate_id: UUID, interview_id: UUID) -> None:
    """后台生成胜任度报告：独立会话（请求会话已随响应关闭），失败仅记日志。"""
    from app.core.database import async_session_factory

    try:
        async with async_session_factory() as session:
            analysis = CandidateAnalysisService(session)
            await analysis.generate(candidate_id, interview_id)
            await session.commit()
    except Exception:
        logger.warning("面试 %s 后台生成胜任度报告失败", interview_id, exc_info=True)
