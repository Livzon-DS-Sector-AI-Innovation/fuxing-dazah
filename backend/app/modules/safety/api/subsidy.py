"""监护补贴只读 API（Web 查询面；生成动作留 Agent，见 DESIGN 20261026）。

编排既有服务，不写业务规则：
- ``GET /subsidy/sources``——可查询部门元数据（台账三部门，零 IO）；
- ``GET /subsidy/guardian-summary``——``fetch_ledger_rows → build_ledger_plan →
  SubsidyService.calculate → b_cert_adjusted_total``，与 Agent 生成工具、
  月报私发完全同口径（级别只认台账/未登按 A 证暂计/同日去重/B 证 0.5 折算）。

一期只接台账三部门（拍板点 A）：平台源部门查询引导 AI 助手。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.modules.safety.service.subsidy import (
    SubsidyService,
    b_cert_adjusted_total,
)
from app.modules.safety.service.subsidy_dept_ledgers import (
    LEDGER_SOURCES,
    build_ledger_plan,
    fetch_ledger_rows,
    match_ledger_source,
)
from app.shared.schemas import ApiResponse

logger = logging.getLogger(__name__)

subsidy_router = APIRouter()

# 与月报私发/Agent 工具同口径
_B_CERT_RATE = 0.5
_UNCERTIFIED_LEVEL = "A证"


def _validate_year_month(year: int, month: int) -> str | None:
    """年月校验（与 subsidy_tools._validate_params 同口径）；非法返回错误文案。"""
    if month < 1 or month > 12:
        return f"月份参数不合法：{month}（应为 1-12）。"
    if year < 2000 or year > 2100:
        return f"年份参数不合法：{year}。"
    return None


@subsidy_router.get(
    "/subsidy/sources",
    response_model=ApiResponse,
    summary="监护补贴可查询部门（台账三部门）",
)
async def list_subsidy_sources(
    current_user: CurrentUser | None = Depends(get_current_user),
) -> ApiResponse:
    return ApiResponse(data=[
        {"department": s.department, "source": "dept_ledger"}
        for s in LEDGER_SOURCES
    ])


@subsidy_router.get(
    "/subsidy/guardian-summary",
    response_model=ApiResponse,
    summary="监护补贴统计（台账部门只读查询）",
)
async def get_guardian_subsidy_summary(
    department: str = Query(..., description="部门全名（提炼工程四/五/六部）"),
    year: int = Query(..., description="统计年份，如 2026"),
    month: int = Query(..., description="统计月份 1-12（按台账开始时间归集）"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
) -> ApiResponse:
    department = (department or "").strip()
    err = _validate_year_month(year, month)
    if err:
        return ApiResponse(code=400, message=err)

    source = match_ledger_source(department)
    if source is None or source.department != department:
        return ApiResponse(
            code=404,
            message=(
                f"「{department}」不在监护补贴台账部门（提炼工程四/五/六部）内，"
                "该部门补贴统计请使用 AI 助手。"
            ),
        )

    try:
        rows = await fetch_ledger_rows(source)
    except Exception:
        logger.exception("监护台账拉取失败: dept=%s %d-%02d", department, year, month)
        return ApiResponse(code=502, message=f"{department}监护台账拉取失败，请稍后重试。")

    plan = build_ledger_plan(source, rows, year, month, uncertified_level=_UNCERTIFIED_LEVEL)
    result = SubsidyService.calculate(plan.records, year=year, month=month)
    return ApiResponse(data={
        "department": department,
        "year": year,
        "month": month,
        "source": "dept_ledger",
        "stats": {
            "matched": plan.matched_tickets,
            "guardians": result.stats.guardian_count,
            "total_amount": result.stats.total_amount,
            "adjusted_total": b_cert_adjusted_total(result.details, _B_CERT_RATE),
            "unmatched": plan.unmatched_tickets,
            "unmatched_people": len(plan.unmatched),
            "skipped": plan.skipped_tickets,
        },
        "summaries": [s.model_dump() for s in result.summaries],
        "details": [d.model_dump() for d in result.details],
        "unmatched": [
            {"name": u.name, "ticket_count": u.ticket_count,
             "operation_types": u.operation_types}
            for u in plan.unmatched
        ],
        "skipped": [
            {"ticket_no": s.ticket_no, "ticket_type": s.ticket_type, "reason": s.reason}
            for s in plan.skipped
        ],
    })
