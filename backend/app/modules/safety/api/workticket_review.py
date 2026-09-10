"""Safety API — workticket_review endpoints.

手动触发作业票审核 + 查询指定日期审核摘要与违规明细。
"""

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.core.database import get_db
from app.modules.safety.models import WorkTicketReviewViolation
from app.modules.safety.schemas import WorkTicketReviewRunRequest
from app.modules.safety.workticket_review.repository import WorkTicketReviewRepository
from app.modules.safety.workticket_review.service import WorkTicketReviewService
from app.shared.schemas import ApiResponse

workticket_review_router = APIRouter()


@workticket_review_router.post(
    "/workticket-review/run",
    response_model=ApiResponse,
    summary="手动触发作业票审核",
)
async def run_work_ticket_review(
    data: WorkTicketReviewRunRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """手动触发一次作业票审核。

    Body 可选：{date?: 'YYYY-MM-DD', push?: bool}，默认 date=今天、push=False。
    """
    review_date = data.date if data and data.date else date.today()
    push = data.push if data else False
    # 手动触发也使用调度器配置的发送对象（DB 播种/覆写），保持唯一来源
    chat_id = None
    try:
        from app.modules.safety.service.scheduler_config import (
            load_scheduled_jobs_with_overrides,
        )

        jobs = await load_scheduled_jobs_with_overrides(db)
        workticket = next((j for j in jobs if j["job_name"] == "作业票审核"), None)
        chat_id = workticket.get("target_chat_id") if workticket else None
    except Exception:
        logger.exception("作业票审核发送对象解析失败，使用 None")
    service = WorkTicketReviewService(db, chat_id=chat_id)
    try:
        result = await service.run_review(review_date, push=push)
        return ApiResponse(data=result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"作业票审核失败: {exc}") from exc


@workticket_review_router.get(
    "/workticket-review/{review_date}",
    response_model=ApiResponse,
    summary="查询指定日期的作业票审核摘要与违规明细",
)
async def get_work_ticket_review(
    review_date: date,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """查询 safety.work_ticket_reviews 摘要 + 逐票违规明细。"""
    repo = WorkTicketReviewRepository(db)
    review = await repo.get_by_date(review_date)
    if review is None:
        return ApiResponse(code=404, message="未找到该日期的作业票审核记录")

    violations = await repo.list_violations(review.id)
    return ApiResponse(
        data={
            "date": review.date.isoformat(),
            "total": review.total,
            "reviewed": review.reviewed,
            "violation_count": review.violation_count,
            "compliant_count": review.compliant_count,
            "data_insufficient": review.data_insufficient,
            "status": review.status,
            "report_markdown": review.report_markdown,
            "pushed": review.pushed,
            "push_message_id": review.push_message_id,
            "error": review.error,
            "finished_at": review.finished_at.isoformat() if review.finished_at else None,
            "violations": [_serialize_violation(v) for v in violations],
        }
    )


def _serialize_violation(v: WorkTicketReviewViolation) -> dict[str, Any]:
    return {
        "id": str(v.id),
        "review_id": str(v.review_id),
        "ticket_no": v.ticket_no,
        "ticket_type": v.ticket_type,
        "rule_no": v.rule_no,
        "rule_name": v.rule_name,
        "detail": v.detail,
        "key_times": v.key_times,
        "not_applicable": v.not_applicable,
    }
