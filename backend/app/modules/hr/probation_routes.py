"""试用期转正评估接口：发起 / 列表 / 确认生效 / 取消。"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.hr.deps import HrAccessContext, get_hr_scope
from app.modules.hr.probation_service import (
    cancel_review,
    create_review,
    finalize_review,
    list_reviews,
)

router = APIRouter(tags=["HR-试用期转正"])


class CreatePayload(BaseModel):
    employee_id: UUID
    reviewer_name: str = Field(min_length=1, max_length=64, description="评估人（部门负责人姓名）")


class FinalizePayload(BaseModel):
    hr_note: str | None = Field(None, max_length=256)


@router.post("/probation-reviews", summary="发起转正评估（机器人私发评估卡片给部门负责人）")
async def create_probation_review(
    payload: CreatePayload,
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    try:
        review = await create_review(
            session, payload.employee_id, payload.reviewer_name, operator=hr_scope.user.name,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return success_response(data={"id": str(review.id)}, message=f"评估卡片已发送给 {payload.reviewer_name}")


@router.get("/probation-reviews", summary="转正评估列表")
async def list_probation_reviews(
    status: str | None = Query(None, description="pending_reviewer/pending_hr/effective/cancelled"),
    session: AsyncSession = Depends(get_db),
):
    rows = await list_reviews(session, status=status)
    return success_response(data=rows)


@router.post("/probation-reviews/{review_id}/finalize", summary="HR 确认生效（通过=写源表转正；延长=改到期日）")
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
