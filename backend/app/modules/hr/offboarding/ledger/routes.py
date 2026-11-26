"""离职台账增强 HTTP 路由：筛选查询 / 字段勾选导出 / 保存视图 / 导出留痕（方案 §3.8）。

挂在 hr 模块路由下，权限复用 hr:departure:read（导出记录入口要 hr:departure:manage），
映射登记在 deps._HR_PATH_PERMISSIONS 的 /departure-ledger* 条目。
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.hr.deps import (
    HrAccessContext,
    check_sensitive_permission,
    require_hr_access,
)
from app.modules.hr.offboarding import repository as repo
from app.modules.hr.offboarding.ledger import export as ledger_export
from app.modules.hr.offboarding.ledger import query as ledger_query
from app.modules.hr.offboarding.ledger import views as ledger_views
from app.modules.hr.offboarding.ledger.schemas import (
    DepartureExportRequest,
    DepartureLedgerQuery,
    DepartureSavedViewIn,
)
from app.modules.hr.xlsx_utils import xlsx_response
from app.platform.audit.service import record_audit_log

logger = logging.getLogger(__name__)

router = APIRouter(tags=["HR-离职台账"])


# ─── 查询 / 筛选选项 / 字段清单 ───

@router.post("/departure-ledger/query", summary="离职台账查询（十类筛选 + 办理流程信息）")
async def query_ledger(
    payload: DepartureLedgerQuery,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:read")),
    has_sensitive: bool = Depends(check_sensitive_permission),
) -> JSONResponse:
    scoped = ledger_query.scoped_departments(ctx, payload.department)
    rows, total = await ledger_query.query(
        db, payload.model_dump(exclude={"sort_by", "sort_order", "page", "page_size"}),
        scoped=scoped, sort_by=payload.sort_by, sort_order=payload.sort_order,
        page=payload.page, page_size=payload.page_size,
    )
    return paginated_response(
        data=ledger_query.mask_rows(rows, has_sensitive),
        total=total, page=payload.page, page_size=payload.page_size,
    )


@router.get("/departure-ledger/filter-options", summary="筛选选项（各部门/岗位/类型/学历等现有取值聚合）")
async def filter_options(
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:read")),
) -> JSONResponse:
    return success_response(data=await ledger_query.filter_options(
        db, ledger_query.scoped_departments(ctx, None),
    ))


@router.get("/departure-ledger/export-columns", summary="可导出字段清单（分组）")
async def export_columns(
    _ctx: HrAccessContext = Depends(require_hr_access("hr:departure:read")),
) -> JSONResponse:
    return success_response(data={
        "columns": ledger_export.column_catalog(),
        "default_keys": list(ledger_export.DEFAULT_EXPORT_KEYS),
    })


# ─── 导出 / 导出留痕 ───

@router.post("/departure-ledger/export", summary="按筛选 + 勾选字段导出 Excel（写导出留痕）")
async def export_ledger(
    payload: DepartureExportRequest,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:read")),
) -> StreamingResponse:
    filters = payload.model_dump(exclude={"columns"})
    workbook, row_count, headers = await ledger_export.export_ledger(
        db, filters, payload.columns,
        scoped=ledger_query.scoped_departments(ctx, payload.department),
        operator_id=ctx.user.id, operator_name=ctx.user.name,
    )
    await record_audit_log(
        db, action="hr.departure.export", user=ctx.user,
        resource_type="hr_departure_ledger",
        new_value={"row_count": row_count, "columns": len(headers)},
    )
    return xlsx_response(workbook, "离职台账导出.xlsx")


@router.get("/departure-ledger/export-logs", summary="导出记录（操作人 / 时间 / 条件 / 条数）")
async def list_export_logs(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _ctx: HrAccessContext = Depends(require_hr_access("hr:departure:manage")),
) -> JSONResponse:
    logs = await repo.list_export_logs(db, module=ledger_export.EXPORT_MODULE, limit=limit)
    return success_response(data=[ledger_export.export_log_dict(log) for log in logs])


# ─── 保存视图 ───

@router.get("/departure-ledger/saved-views", summary="我的离职台账视图")
async def list_saved_views(
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:read")),
) -> JSONResponse:
    views = await ledger_views.list_views(db, ctx.user.id)
    return success_response(data=[ledger_views.view_dict(view) for view in views])


@router.post("/departure-ledger/saved-views", summary="存为视图")
async def create_saved_view(
    payload: DepartureSavedViewIn,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:read")),
) -> JSONResponse:
    view = await ledger_views.create_view(
        db, ctx.user.id, name=payload.name, filters=payload.filters.active(),
        columns=payload.columns, is_default=payload.is_default,
    )
    return success_response(data=ledger_views.view_dict(view), message="视图已保存")


@router.put("/departure-ledger/saved-views/{view_id}", summary="更新视图")
async def update_saved_view(
    view_id: UUID,
    payload: DepartureSavedViewIn,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:read")),
) -> JSONResponse:
    view = await ledger_views.update_view(
        db, ctx.user.id, view_id, name=payload.name, filters=payload.filters.active(),
        columns=payload.columns, is_default=payload.is_default,
    )
    return success_response(data=ledger_views.view_dict(view), message="视图已更新")


@router.delete("/departure-ledger/saved-views/{view_id}", summary="删除视图")
async def delete_saved_view(
    view_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:departure:read")),
) -> JSONResponse:
    await ledger_views.delete_view(db, ctx.user.id, view_id)
    return success_response(message="视图已删除")

