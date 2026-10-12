"""Safety API — hazards endpoints（3.0 只读台账口径）.

仅保留台账查询类端点：列表 / 统计 / 详情 / Bitable 漏单诊断。
登记与整改操作（创建/更新/删除/图片上传/整改状态机/AI 手动触发/通知）
已随 Web 退役——业务操作在飞书多维表格与机器人，service 层保留供
Bitable 同步与 AI 自动链路（scheduler / feishu handler）使用。
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.schemas import (
    HazardReportResponse,
    HazardStatsResponse,
)
from app.modules.safety.service import (
    HazardService,
)

hazards_router = APIRouter()


@hazards_router.get("/hazards", response_model=ApiResponse, summary="获取隐患列表")
async def get_hazards(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    rectification_status: str | None = None,
    hazard_type: str | None = None,
    hazard_level: str | None = None,
    hazard_category: str | None = None,
    inspection_category: str | None = None,
    department: str | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取隐患列表"""
    service = HazardService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_hazards(
        skip, page_size, status, rectification_status, hazard_type, hazard_level,
        hazard_category, inspection_category, department, keyword,
    )
    return ApiResponse(
        data=[HazardReportResponse.model_validate(h) for h in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@hazards_router.get("/hazards/stats", response_model=ApiResponse, summary="获取隐患统计数据")
async def get_hazard_stats(
    db: AsyncSession = Depends(get_db),
):
    """获取隐患全局统计数据（不受分页/筛选影响，用于统计药丸展示）。"""
    service = HazardService(db)
    stats = await service.get_hazard_stats()
    return ApiResponse(data=HazardStatsResponse(**stats))


@hazards_router.get("/hazards/{hazard_id}", response_model=ApiResponse, summary="获取隐患详情")
async def get_hazard(
    hazard_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取隐患详情"""
    service = HazardService(db)
    item = await service.get_hazard(hazard_id)
    if not item:
        return ApiResponse(code=404, message="隐患不存在")
    return ApiResponse(data=HazardReportResponse.model_validate(item))


@hazards_router.get(
    "/hazards/catch-up/diagnose",
    response_model=ApiResponse,
    summary="Bitable 漏单诊断",
)
async def diagnose_bitable_catch_up(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """诊断 Bitable 多维表格中是否有在 WebSocket 断线期间被遗漏的记录。

    使用飞书 Bitable 系统字段「修改时间」做精准增量查询：
    - 获取本地最新记录的 updated_at 作为时间下界
    - 查询 Bitable 中 last_modified_time > 此值的记录
    - 按 feishu_record_id 比对，找出本地不存在的记录

    纯查询操作，不修改数据库或 Bitable 中的任何数据。

    返回字段：
    - cutoff_time: 时间下界（ISO 格式）
    - bitable_matched: 查询窗口内 Bitable 返回的记录总数
    - local_total: 本地已关联 feishu_record_id 的记录数
    - missed: 漏单数（Bitable 有但本地没有），-1 表示诊断失败
    - existing: 两边都存在的记录数
    - missed_records: 漏单详情（最多 50 条，含 record_id + 关键字段）
    """
    from app.modules.safety.feishu.catch_up import diagnose_missed_records

    result = await diagnose_missed_records(db)
    return ApiResponse(data=result)
