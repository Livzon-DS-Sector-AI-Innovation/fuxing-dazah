"""新员工信息收集接口：发起收集 / 待审列表 / 采纳 / 驳回。"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.hr.deps import HrAccessContext, get_hr_scope
from app.modules.hr.employee_info_collection_service import (
    approve_collection,
    create_collections,
    list_collections,
    reject_collection,
)

router = APIRouter(tags=["HR-新员工信息收集"])


class CreatePayload(BaseModel):
    employee_ids: list[UUID] = Field(min_length=1)


class RejectPayload(BaseModel):
    reason: str = Field(min_length=1, max_length=200)


@router.post("/employee-info-collections", summary="批量发起信息收集（机器人私发表单卡片）")
async def create_employee_info_collections(
    payload: CreatePayload,
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    result = await create_collections(session, payload.employee_ids, operator=hr_scope.user.name)
    return success_response(data=result, message=f"已发送 {result['created']} 份")


@router.get("/employee-info-collections", summary="信息收集任务列表（含字段差异对比）")
async def list_employee_info_collections(
    status: str | None = Query(None, description="sent/submitted/approved/rejected"),
    session: AsyncSession = Depends(get_db),
):
    rows = await list_collections(session, status=status)
    return success_response(data=rows)


@router.post("/employee-info-collections/{collection_id}/approve", summary="采纳：写入飞书源表并预更新档案")
async def approve_employee_info_collection(
    collection_id: UUID,
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    try:
        result = await approve_collection(session, collection_id, reviewer=hr_scope.user.name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    message = f"已采纳并写入源表 {result['written_fields']} 项字段"
    if result.get("skipped_fields"):
        message += f"（源表缺列跳过：{'、'.join(result['skipped_fields'])}）"
    return success_response(data=result, message=message)


@router.post("/employee-info-collections/{collection_id}/reject", summary="驳回：记录原因并重发填写卡片")
async def reject_employee_info_collection(
    collection_id: UUID,
    payload: RejectPayload,
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    try:
        await reject_collection(session, collection_id, payload.reason, reviewer=hr_scope.user.name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return success_response(message="已驳回，填写卡片已重新发送给员工")
