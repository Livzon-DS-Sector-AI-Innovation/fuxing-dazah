"""QA AI 分析与主数据提案端点。"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundException
from app.core.response import paginated_response, success_response
from app.modules.qa import service
from app.modules.qa.api._deps import (
    proposal_publish,
    relation_manage,
)
from app.modules.qa.repository import (
    get_ai_run,
    get_latest_ai_run,
)
from app.modules.qa.schemas import (
    AIAnalysisRunOut,
    AIAnalysisTriggerRequest,
    AIRelationConfirmationRequest,
    MasterObjectProposalApproveRequest,
    MasterObjectProposalOut,
)
from app.modules.qa.service import ai_analysis
from app.platform.identity.models import User
from app.shared.schemas import ApiResponse

router = APIRouter()
router = APIRouter()


@router.post(
    "/document-versions/{version_id}/ai-analysis",
    response_model=ApiResponse,
    summary="异步触发文档 AI 分析",
)
async def post_ai_analysis(
    version_id: uuid.UUID,
    payload: AIAnalysisTriggerRequest | None = None,
    user: User = Depends(relation_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    run = await ai_analysis.create_analysis_run(
        db, version_id, user, force=bool(payload and payload.force)
    )
    return success_response({"run_id": run.id, "status": run.status})


@router.get(
    "/document-versions/{version_id}/ai-analysis/latest",
    response_model=ApiResponse,
    summary="获取版本最近一次 AI 分析",
)
async def get_latest_ai_analysis(
    version_id: uuid.UUID,
    user: User = Depends(relation_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    run = await get_latest_ai_run(db, version_id)
    if run is None:
        raise NotFoundException("AI 分析运行", str(version_id))
    data = await ai_analysis.analysis_to_dict(db, run, user=user)
    return success_response(
        AIAnalysisRunOut.model_validate(data).model_dump(mode="json")
    )


@router.get(
    "/ai-analysis/{run_id}",
    response_model=ApiResponse,
    summary="获取指定 AI 分析运行及证据",
)
async def get_ai_analysis(
    run_id: uuid.UUID,
    user: User = Depends(relation_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    run = await get_ai_run(db, run_id)
    if run is None:
        raise NotFoundException("AI 分析运行", str(run_id))
    data = await ai_analysis.analysis_to_dict(db, run, user=user)
    return success_response(
        AIAnalysisRunOut.model_validate(data).model_dump(mode="json")
    )


@router.post(
    "/ai-analysis/{run_id}/confirm-relations",
    response_model=ApiResponse,
    summary="确认 AI 候选文件关联",
)
async def post_confirm_ai_relations(
    run_id: uuid.UUID,
    payload: AIRelationConfirmationRequest,
    user: User = Depends(relation_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    rows = await ai_analysis.confirm_relations(
        db,
        run_id,
        accepted_suggestion_ids=payload.accepted_suggestion_ids,
        manual_master_object_ids=payload.manual_master_object_ids,
        remove_master_object_ids=payload.remove_master_object_ids,
        user=user,
    )
    return success_response([await service._relation_dict(db, row) for row in rows])


@router.get(
    "/master-object-proposals",
    response_model=ApiResponse,
    summary="QA 主数据 AI 提案箱",
)
async def get_master_object_proposals(
    user: User = Depends(proposal_publish),
    db: AsyncSession = Depends(get_db),
    status: str | None = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> Any:
    items, total = await ai_analysis.list_proposal_page(
        db, status=status, page=page, page_size=page_size
    )
    return paginated_response(items, page, page_size, total)


@router.post(
    "/master-object-proposals/{proposal_id}/approve",
    response_model=ApiResponse,
    summary="审批 QA 主数据 AI 提案",
)
async def approve_master_object_proposal(
    proposal_id: uuid.UUID,
    payload: MasterObjectProposalApproveRequest | None = None,
    user: User = Depends(proposal_publish),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row, auto_link_skipped = await ai_analysis.approve_proposal(
        db, proposal_id, payload.payload if payload else None, user
    )
    body = MasterObjectProposalOut.model_validate(row).model_dump(mode="json")
    body["auto_linked"] = auto_link_skipped is None
    body["auto_link_skipped_reason"] = auto_link_skipped
    return success_response(body)


@router.post(
    "/master-object-proposals/{proposal_id}/reject",
    response_model=ApiResponse,
    summary="拒绝 QA 主数据 AI 提案",
)
async def reject_master_object_proposal(
    proposal_id: uuid.UUID,
    user: User = Depends(proposal_publish),
    db: AsyncSession = Depends(get_db),
) -> Any:
    # 拒绝即软删除，不回传提案内容：调用方只需知道已处理。
    await ai_analysis.reject_proposal(db, proposal_id, user)
    return success_response({"id": str(proposal_id), "status": "rejected"})


@router.post(
    "/master-object-proposals/reject-all",
    response_model=ApiResponse,
    summary="一键拒绝全部待审核 QA 主数据 AI 提案",
)
async def reject_all_master_object_proposals(
    user: User = Depends(proposal_publish),
    db: AsyncSession = Depends(get_db),
) -> Any:
    rejected, skipped = await ai_analysis.reject_all_proposals(db, user)
    return success_response({"rejected": rejected, "skipped": skipped})
