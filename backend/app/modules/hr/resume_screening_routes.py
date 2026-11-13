"""AI 简历筛选接口：按岗位要求批量上传 PDF，逐份打分排名辅助初筛。"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.hr.deps import HrAccessContext, require_hr_access
from app.modules.hr.resume_screening_service import ResumeScreeningService
from app.modules.hr.schemas import CandidateResponse
from app.modules.hr.service import NotFoundException

router = APIRouter(tags=["HR-AI简历筛选"])


def _to_dict(r, jd=None) -> dict:
    return {
        "id": str(r.id),
        "job_requirement_id": str(r.job_requirement_id),
        "job_name": jd.position_name if jd else None,
        "job_department": jd.department if jd else None,
        "candidate_id": str(r.candidate_id) if r.candidate_id else None,
        "jd_snapshot": r.jd_snapshot,
        "file_name": r.file_name,
        "candidate_name": r.candidate_name,
        "core_evaluation": r.core_evaluation,
        "talent_category": r.talent_category,
        "candidate_profile": r.candidate_profile or {},
        "dimension_assessment": r.dimension_assessment or {},
        "match_report": r.match_report,
        "total_score": r.total_score,
        "recommendation": r.recommendation,
        "advantages": r.advantages or [],
        "flaws": r.flaws or [],
        "score_table": r.score_table or [],
        "final_verdict": r.final_verdict,
        "final_reasons": r.final_reasons or [],
        "model_version": r.model_version,
        "created_by_name": r.created_by_name,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.post("/resume-screening/{jd_id}", summary="AI 筛选一份简历（PDF 全文 + 岗位要求 → 打分/理由）")
async def screen_resume(
    jd_id: UUID,
    file: UploadFile,
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(require_hr_access("hr:recruitment:manage")),
) -> JSONResponse:
    """单份处理：前端逐份调用展示进度。文件需为文字版 PDF（扫描件无法提取文本）。"""
    service = ResumeScreeningService(session)
    try:
        result = await service.screen_resume(
            jd_id=jd_id,
            file_name=file.filename or "resume.pdf",
            file_bytes=bytes(await file.read()),
            operator=hr_scope.user.name,
        )
        await session.commit()
        return success_response(data=_to_dict(result), message="筛选完成", status_code=201)
    except NotFoundException as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/resume-screening/candidate/{candidate_id}", summary="对已建档候选人的存量简历直接 AI 初筛（免重复上传）")
async def screen_candidate_resume(
    candidate_id: UUID,
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(require_hr_access("hr:recruitment:manage")),
) -> JSONResponse:
    """读取候选人已上传的简历文件，按其关联岗位需求 AI 打分；结果回链候选人并回写推荐等级/匹配报告。"""
    service = ResumeScreeningService(session)
    try:
        result = await service.screen_candidate(candidate_id, operator=hr_scope.user.name)
        await session.commit()
        return success_response(data=_to_dict(result), message="初筛完成", status_code=201)
    except NotFoundException as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/resume-screening", summary="筛选结果排名总览（岗位可选，不传=全部岗位，总分降序）")
async def list_screening_results(
    job_requirement_id: UUID | None = None,
    session: AsyncSession = Depends(get_db),
    _ctx: HrAccessContext = Depends(require_hr_access("hr:recruitment:read")),
) -> JSONResponse:
    service = ResumeScreeningService(session)
    pairs = await service.list_ranking(job_requirement_id)
    return success_response(data=[_to_dict(r, jd) for r, jd in pairs])


@router.get("/resume-screening/{result_id}/resume-preview", summary="查看筛选结果的简历原文")
async def screening_resume_preview(
    result_id: UUID,
    session: AsyncSession = Depends(get_db),
    _ctx: HrAccessContext = Depends(require_hr_access("hr:recruitment:read")),
):
    """读取该筛选结果存档的简历 PDF（与候选人简历预览同一套存储读取规则）。"""
    from fastapi.responses import Response

    try:
        data, _name = await ResumeScreeningService(session).get_resume_bytes(result_id)
    except NotFoundException as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return Response(content=data, media_type="application/pdf")


@router.delete("/resume-screening/{result_id}", summary="删除筛选结果")
async def delete_screening_result(
    result_id: UUID,
    session: AsyncSession = Depends(get_db),
    _ctx: HrAccessContext = Depends(require_hr_access("hr:recruitment:manage")),
) -> JSONResponse:
    try:
        await ResumeScreeningService(session).delete(result_id)
        await session.commit()
    except NotFoundException as e:
        raise HTTPException(404, str(e)) from e
    return success_response(message="已删除")


@router.post("/resume-screening/{result_id}/convert", summary="筛选结果转为候选人（进入待筛选流程）")
async def convert_screening_result(
    result_id: UUID,
    session: AsyncSession = Depends(get_db),
    _ctx: HrAccessContext = Depends(require_hr_access("hr:recruitment:manage")),
) -> JSONResponse:
    try:
        candidate = await ResumeScreeningService(session).convert_to_candidate(result_id)
        await session.commit()
    except NotFoundException as e:
        raise HTTPException(404, str(e)) from e
    return success_response(
        data=CandidateResponse.model_validate(candidate).model_dump(mode="json"),
        message="已转为候选人（待筛选）",
        status_code=201,
    )
