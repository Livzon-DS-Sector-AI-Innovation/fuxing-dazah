"""Safety API — contractor_admission endpoints.

直读模式（SAFETY_CONTRACTOR_ADMISSION_DIRECT_ENABLED）：列表/统计 meta 带
mode=direct + elapsed_ms；详情/审核路径参数接受 recXXX 或 UUID 双态。
非法串处置：详情 404（原 FastAPI 422，受控偏差照 key_risk_op 落档）；
审核 400（沿用本端点既有「仅支持飞书来源」契约）。
"""

import time

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.schemas import (
    ContractorAdmissionListItem,
    ContractorAdmissionResponse,
    ContractorAdmissionStats,
)
from app.modules.safety.service import ContractorAdmissionService

contractor_admission_router = APIRouter()


@contractor_admission_router.get(
    "/contractor-admissions", response_model=ApiResponse, summary="获取相关方准入列表"
)
async def get_contractor_admissions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    related_party_type: str | None = Query(
        None, description="相关方类型: 承包商/合作类相关方/劳务派遣/其他相关方"
    ),
    submit_status: str | None = Query(
        None, description="提交状态: 已完成/进行中/未开始"
    ),
    ai_review_status: str | None = Query(
        None, description="AI审核状态: none/processing/completed/failed"
    ),
    ai_conclusion: str | None = Query(
        None, description="AI审核总体结论: 审核通过/需补充完善/审核不通过"
    ),
    keyword: str | None = Query(
        None, description="关键词（模糊匹配作业单位名称/承包商负责人）"
    ),
    sort_by: str | None = Query(
        None, description="排序字段: entry_date/actual_complete_date/created_at/company_name"
    ),
    sort_order: str = Query("desc", description="排序方向: desc/asc"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取相关方准入列表，支持多条件筛选"""
    from app.modules.safety.service.contractor_admission_direct import (
        config as direct_config,
    )

    direct = direct_config.direct_enabled()
    t0 = time.perf_counter()
    service = ContractorAdmissionService(db)
    items, total = await service.get_list(
        filters={
            "related_party_type": related_party_type,
            "submit_status": submit_status,
            "ai_review_status": ai_review_status,
            "ai_conclusion": ai_conclusion,
            "keyword": keyword,
            "sort_by": sort_by,
            "sort_order": sort_order,
        },
        page=page,
        page_size=page_size,
    )
    meta: dict[str, object] = {"page": page, "page_size": page_size, "total": total}
    if direct:
        meta["mode"] = "direct"
        meta["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
    return ApiResponse(
        data=[ContractorAdmissionListItem.model_validate(i) for i in items],
        meta=meta,
    )


@contractor_admission_router.get(
    "/contractor-admissions/stats",
    response_model=ApiResponse,
    summary="获取相关方准入统计",
)
async def get_contractor_admission_stats(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """相关方准入统计（KPI 卡）：total + 按 AI 审核状态/相关方类型/提交状态分组计数"""
    from app.modules.safety.service.contractor_admission_direct import (
        config as direct_config,
    )

    direct = direct_config.direct_enabled()
    t0 = time.perf_counter()
    service = ContractorAdmissionService(db)
    data = await service.get_stats()
    meta: dict[str, object] | None = None
    if direct:
        meta = {"mode": "direct", "elapsed_ms": int((time.perf_counter() - t0) * 1000)}
    return ApiResponse(data=ContractorAdmissionStats.model_validate(data), meta=meta)


@contractor_admission_router.get(
    "/contractor-admissions/{admission_id}",
    response_model=ApiResponse,
    summary="获取相关方准入详情",
)
async def get_contractor_admission(
    admission_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取相关方准入详情（id 双态：recXXX 直读视图 / UUID 平台行，非法串 404）"""
    service = ContractorAdmissionService(db)
    item = await service.resolve_detail(admission_id)
    if not item:
        return ApiResponse(code=404, message="相关方准入记录不存在")
    return ApiResponse(data=ContractorAdmissionResponse.model_validate(item))


@contractor_admission_router.post(
    "/contractor-admissions/{admission_id}/ai/audit",
    response_model=ApiResponse,
    summary="触发相关方准入AI审核",
)
async def run_contractor_admission_ai_audit(
    admission_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """手动触发单条相关方准入 AI 审核，结果回填飞书多维表格并更新平台。

    id 双态：recXXX（直读新鲜数据审核）/ UUID（平台行定位）。
    仅支持飞书来源（source='bitable'）且有 feishu_record_id 的记录。
    """
    service = ContractorAdmissionService(db)
    item = await service.run_admission_audit_dual(admission_id, channel="web")
    if item is None:
        return ApiResponse(code=400, message="仅支持飞书来源的相关方准入记录触发AI审核")
    return ApiResponse(data=ContractorAdmissionResponse.model_validate(item))
