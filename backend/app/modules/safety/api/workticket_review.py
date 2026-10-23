"""Safety API — workticket_review endpoints.

手动触发作业票审核 + 查询指定日期审核摘要与违规明细（含该日问题的整改复查结论）。
"""

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.safety.models import (
    WorkTicketRectifyCheck,
    WorkTicketReviewViolation,
)
from app.modules.safety.schemas import WorkTicketReviewRunRequest
from app.modules.safety.workticket_review.repository import WorkTicketReviewRepository
from app.modules.safety.workticket_review.service import WorkTicketReviewService
from app.shared.schemas import ApiResponse

workticket_review_router = APIRouter()

logger = logging.getLogger(__name__)


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
    调度口径为「每日 10 点审昨日票」，手动触发按传入 date 审核（未传时默认今天），
    同时会复查 date-1 那次审核的问题整改情况。
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
    """查询 safety.work_ticket_reviews 摘要 + 逐票违规明细 + 该日问题整改复查。"""
    repo = WorkTicketReviewRepository(db)
    review = await repo.get_by_date(review_date)
    if review is None:
        return ApiResponse(code=404, message="未找到该日期的作业票审核记录")

    violations = await repo.list_violations(review.id)
    rectify_stmt = (
        select(WorkTicketRectifyCheck)
        .where(
            WorkTicketRectifyCheck.source_review_date == review_date,
            WorkTicketRectifyCheck.is_deleted.is_(False),
        )
        .order_by(WorkTicketRectifyCheck.ticket_no)
    )
    rectify_rows = list((await db.execute(rectify_stmt)).scalars().all())
    rectify_summary: dict[str, Any] | None = None
    if rectify_rows:
        by_status: dict[str, int] = {"rectified": 0, "unrectified": 0, "uncheckable": 0}
        for row in rectify_rows:
            by_status[row.status] = by_status.get(row.status, 0) + 1
        rectify_summary = {
            "source_date": review_date.isoformat(),
            "checked_date": rectify_rows[0].checked_date.isoformat(),
            "problem_total": len(rectify_rows),
            "rectified": by_status.get("rectified", 0),
            "unrectified": by_status.get("unrectified", 0),
            "uncheckable": by_status.get("uncheckable", 0),
            "tickets": [_serialize_rectify(row) for row in rectify_rows],
        }
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
            "rectify_check": rectify_summary,
        }
    )


def _serialize_rectify(row: WorkTicketRectifyCheck) -> dict[str, Any]:
    from app.modules.safety.workticket_review.report_builder import TICKET_TYPE_NAMES

    return {
        "ticket_no": row.ticket_no,
        "ticket_type": row.ticket_type,
        "ticket_type_name": TICKET_TYPE_NAMES.get(row.ticket_type, row.ticket_type),
        "status": row.status,
        "rule_results": row.rule_results or [],
        "note": row.note,
        "checked_date": row.checked_date.isoformat(),
    }


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
