"""Safety API — 安全设备设施管理（facilities-p1）。

- 票 01：GET /facilities/ledgers/{ledger}（三台账三态信封）；
- 票 03：GET /facility-tasks（列表/summary/详情含事件流）；
- 票 04：POST /facility-tasks/{id}/reopen · /cancel（管理员干预）。
无 submit/close 端点是拍板口径：闭环唯一入口=多维表格更新检测。
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.modules.safety.facilities.closure import cancel_task, reopen_task
from app.modules.safety.facilities.page import build_ledger_page
from app.modules.safety.facilities.query import list_tasks, task_detail, task_summary
from app.modules.safety.models import TRIGGER_MANUAL
from app.modules.safety.schemas.facilities import (
    FacilitiesLedgerPageOut,
    FacilityTaskActionIn,
)
from app.shared.schemas import ApiResponse

facilities_router = APIRouter()


@facilities_router.get(
    "/facilities/ledgers/{ledger}",
    response_model=ApiResponse,
    summary="三台账页面数据（三态信封：安全附件/消防器材/特种设备）",
)
async def get_facilities_ledger(
    ledger: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> ApiResponse:
    data = await build_ledger_page(ledger, page=page, page_size=page_size)
    return ApiResponse(data=FacilitiesLedgerPageOut(**data).model_dump(mode="json"))


@facilities_router.get(
    "/facility-tasks",
    response_model=ApiResponse,
    summary="校验任务列表（筛选：状态/部门/类型/分组/仅逾期）",
)
async def list_facility_tasks(
    status: str | None = Query(None),
    department: str | None = Query(None),
    biz_type: str | None = Query(None),
    group_key: str | None = Query(None),
    overdue: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db=Depends(get_db),
) -> ApiResponse:
    items, total = await list_tasks(
        db,
        status=status, department=department, biz_type=biz_type,
        group_key=group_key, overdue=overdue,
        page=page, page_size=page_size,
    )
    return ApiResponse(data={"items": items, "total": total, "page": page, "page_size": page_size})


@facilities_router.get(
    "/facility-tasks/summary",
    response_model=ApiResponse,
    summary="校验任务分桶统计（按部门/分组聚合进度）",
)
async def facility_task_summary(
    biz_type: str | None = Query(None),
    department: str | None = Query(None),
    db=Depends(get_db),
) -> ApiResponse:
    return ApiResponse(data=await task_summary(db, biz_type=biz_type, department=department))


@facilities_router.get(
    "/facility-tasks/{task_id}",
    response_model=ApiResponse,
    summary="校验任务详情（含事件流时间线）",
)
async def get_facility_task(task_id: uuid.UUID, db=Depends(get_db)) -> ApiResponse:
    detail = await task_detail(db, task_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return ApiResponse(data=detail)


@facilities_router.post(
    "/facility-tasks/{task_id}/reopen",
    response_model=ApiResponse,
    summary="误关恢复（closed/cancelled → issued，事件留痕）",
)
async def reopen_facility_task(
    task_id: uuid.UUID,
    payload: FacilityTaskActionIn | None = None,
    db=Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
) -> ApiResponse:
    from app.modules.safety.models import FacilityCheckTask

    task = await db.get(FacilityCheckTask, task_id)
    if task is None or task.is_deleted:
        raise HTTPException(status_code=404, detail="任务不存在")
    operator = getattr(current_user, "open_id", None) or "admin"
    ok = await reopen_task(db, task, operator=operator, reason=payload.reason if payload else None)
    if not ok:
        raise HTTPException(status_code=409, detail="任务已是待闭环状态")
    await db.commit()
    detail = await task_detail(db, task_id)
    return ApiResponse(data=detail)


@facilities_router.post(
    "/facility-tasks/{task_id}/cancel",
    response_model=ApiResponse,
    summary="管理员取消（必填原因，事件留痕；行失效兜底）",
)
async def cancel_facility_task(
    task_id: uuid.UUID,
    payload: FacilityTaskActionIn,
    db=Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
) -> ApiResponse:
    from app.modules.safety.models import FacilityCheckTask

    reason = (payload.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=422, detail="取消原因必填")
    task = await db.get(FacilityCheckTask, task_id)
    if task is None or task.is_deleted:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != "issued":
        raise HTTPException(status_code=409, detail="仅待闭环任务可取消")
    operator = getattr(current_user, "open_id", None) or "admin"
    await cancel_task(
        db, task, trigger=TRIGGER_MANUAL, reason=reason, operator=operator
    )
    await db.commit()
    detail = await task_detail(db, task_id)
    return ApiResponse(data=detail)
