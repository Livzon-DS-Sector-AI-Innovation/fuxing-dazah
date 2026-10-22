"""Safety API — 体系标准核查（S1 目标责任与绩效）。

GET /safety/goals/standards：标准清单×运行数据四态判定（达标/进行中/未达标/
无数据）。核查表是普通 Bitable 表（安环科维护标准行），平台只读判定不回写。
GET /safety/goals/standards/evidence：单条标准凭据明细（点开重算一次，取数
无状态不共享请求间缓存——低频点按低耗重算，口径注释见 page.py）。
GET /safety/goals/standards/history：历史定格（二期）——读 snapshot 表，
迎检/自评直接取定格结果，不实时重算。
DESIGN：docs/DESIGN-安全目标责任与绩效模块-体系标准符合性核查引擎-20261021.md
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.safety.schemas.standard_check import (
    StandardCheckPageOut,
    StandardEvidenceOut,
    StandardHistoryOut,
)
from app.modules.safety.service.standard_check import (
    build_standard_check_page,
    build_standard_evidence,
    build_standard_history,
)
from app.shared.schemas import ApiResponse

standard_check_router = APIRouter()


@standard_check_router.get(
    "/goals/standards",
    response_model=ApiResponse,
    summary="体系标准核查清单（四态判定，三态信封）",
)
async def get_standard_check_page(
    db: AsyncSession = Depends(get_db),
    year: int | None = Query(None, description="年度（默认当年，北京时间）"),
    element: str | None = Query(None, description="要素归属筛选（八要素之一）"),
    status: str | None = Query(
        None, description="四态筛选：ok/in_progress/missed/no_data"
    ),
    department: str | None = Query(None, description="责任部门筛选（multi 包含）"),
) -> ApiResponse:
    data = await build_standard_check_page(
        db=db, year=year, element=element, status=status, department=department
    )
    return ApiResponse(data=StandardCheckPageOut(**data).model_dump(mode="json"))


@standard_check_router.get(
    "/goals/standards/evidence",
    response_model=ApiResponse,
    summary="单条标准凭据明细（达标可点验，无数据附原因）",
)
async def get_standard_evidence(
    record_id: str = Query(..., description="核查表行 record_id"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    data = await build_standard_evidence(record_id, db=db)
    return ApiResponse(data=StandardEvidenceOut(**data).model_dump(mode="json"))


@standard_check_router.get(
    "/goals/standards/history",
    response_model=ApiResponse,
    summary="历史定格（读 snapshot 表非实时重算；迎检/自评直接取定格结果）",
)
async def get_standard_history(
    year: int | None = Query(None, description="年度（默认当年，北京时间）"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    data = await build_standard_history(year, db=db)
    return ApiResponse(data=StandardHistoryOut(**data).model_dump(mode="json"))
