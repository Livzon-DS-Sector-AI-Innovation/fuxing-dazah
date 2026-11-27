"""试用期转正评估接口：发起 / 列表 / 兜底生效 / 取消 / 安全考试结果。"""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.hr.deps import HrAccessContext, get_hr_scope
from app.modules.hr.probation_service import (
    add_safety_exam,
    cancel_review,
    create_review,
    delete_safety_exam,
    finalize_review,
    list_reviews,
    list_safety_exams,
)

router = APIRouter(tags=["HR-试用期转正"])


class CreatePayload(BaseModel):
    employee_id: UUID


class FinalizePayload(BaseModel):
    hr_note: str | None = Field(None, max_length=256)


@router.post("/probation-reviews", summary="发起转正评估（三级审批：直属上级→部门经理→分管领导）")
async def create_probation_review(
    payload: CreatePayload,
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    try:
        review = await create_review(
            session, payload.employee_id, operator=hr_scope.user.name,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return success_response(
        data={"id": str(review.id)},
        message=f"评估卡片已发送给直属上级 {review.direct_manager_name}，将依次经部门经理、分管领导审批",
    )


@router.get("/probation-reviews", summary="转正评估列表")
async def list_probation_reviews(
    status: str | None = Query(None, description="pending_step1/pending_step2/pending_step3/effective/rejected/cancelled"),
    session: AsyncSession = Depends(get_db),
):
    rows = await list_reviews(session, status=status)
    return success_response(data=rows)


@router.post("/probation-reviews/{review_id}/finalize", summary="HR 确认生效（兜底：源表回写失败重试 / 线下沟通完毕直接生效）")
async def finalize_probation_review(
    review_id: UUID,
    payload: FinalizePayload,
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    try:
        result = await finalize_review(session, review_id, payload.hr_note, reviewer=hr_scope.user.name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if result["conclusion"] == "通过":
        message = "已转正生效：源表员工性质已改为「正式」，本地状态已更新"
    elif result["conclusion"] == "延长":
        message = f"已确认延长试用期至 {result['extended_to']}，到期后请重新发起评估"
    else:
        message = "已确认不通过（未改动员工状态），请按需走离职流程"
    return success_response(data=result, message=message)


@router.post("/probation-reviews/{review_id}/cancel", summary="取消进行中的评估")
async def cancel_probation_review(
    review_id: UUID,
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    try:
        await cancel_review(session, review_id, operator=hr_scope.user.name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return success_response(message="已取消")


# ── 安全考试结果（安全办录入）──


class SafetyExamPayload(BaseModel):
    employee_id: UUID
    exam_date: date = Field(description="考试日期")
    passed: bool = Field(description="是否合格")
    score: float | None = Field(None, ge=0, le=200)
    remark: str | None = Field(None, max_length=256)


@router.get("/probation-safety-exams", summary="安全考试结果列表（重点岗位 60 天节点）")
async def list_probation_safety_exams(
    employee_id: UUID | None = Query(None),
    session: AsyncSession = Depends(get_db),
):
    return success_response(data=await list_safety_exams(session, employee_id=employee_id))


@router.post("/probation-safety-exams", summary="录入安全考试结果（安全办）")
async def create_probation_safety_exam(
    payload: SafetyExamPayload,
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    try:
        row = await add_safety_exam(
            session,
            employee_id=payload.employee_id, exam_date=payload.exam_date,
            passed=payload.passed, score=payload.score,
            entered_by=hr_scope.user.name, remark=payload.remark,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return success_response(data=row, message="已录入")


@router.delete("/probation-safety-exams/{exam_id}", summary="删除安全考试记录（软删）")
async def delete_probation_safety_exam(
    exam_id: UUID,
    session: AsyncSession = Depends(get_db),
):
    try:
        await delete_safety_exam(session, exam_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return success_response(message="已删除")
