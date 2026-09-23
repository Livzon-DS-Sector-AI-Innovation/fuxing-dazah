"""lc API 路由（api.py 拆分）。"""

import uuid

from fastapi import (
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.quality.api._common import (
    router,
)
from app.modules.quality.repository import (
    delete_inspection_record,
    get_test_task_by_batch,
    list_inspection_records,
)
from app.modules.quality.schemas import (
    InspectionRecordListItem,
    LcReportOut,
    UploadLcResponse,
)
from app.modules.quality.service import (
    lc_report_service,
    test_task_service,
)
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission

# ─── 液相解析上传 ───


@router.post("/lc/upload", response_model=UploadLcResponse, summary="上传液相计算表并解析")
async def upload_lc_excel(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:lc:upload")),
):
    filename = file.filename or "unknown.xlsx"
    if not filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 或 .xls")
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(file_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件超过 10MB")
    try:
        # 优先模板配置驱动的通用解析（表号识别）；无匹配配置回落到旧解析器
        generic = await test_task_service.parse_lc_generic(db, file_bytes, filename, filled_by=_user.id)
        if generic is not None:
            parsed = generic["parse"]
            result = UploadLcResponse(
                filename=filename,
                report=LcReportOut(
                    product_name=parsed.product_name,
                    batch_number=parsed.batch_number,
                    form_id=parsed.form_id,
                ),
                record_id=generic["record_id"],
                task_link=generic["task_link"],
                components=[
                    {"name": c.name, "first": c.first, "second": c.second, "report_value": c.report_value}
                    for c in parsed.components
                ],
            )
            return result
        result = await lc_report_service.parse_and_validate(file_bytes, filename, db=db)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"无法解析：{e}") from e
    # 自动关联已建检验任务：按产品+批号定位，按 SOP/项目名映射填入
    if result.record_id:
        task = await get_test_task_by_batch(db, result.report.product_name, result.report.batch_number)
        if task and task.status == "in_progress":
            filled, unmatched = await test_task_service.fill_task_from_report(
                db, task, result.report, result.record_id, filled_by=_user.id
            )
            result.task_link = {
                "task_id": str(task.id),
                "filled": filled,
                "unmatched": unmatched,
            }
    return result


# ─── 检验记录查询 ───


@router.get("/lc/records", summary="分页查询液相解析历史记录")
async def list_lc_records(
    product_name: str | None = Query(default=None, description="产品名称（模糊搜索）"),
    batch_number: str | None = Query(default=None, description="批号（模糊搜索）"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items, total = await list_inspection_records(
        db, product_name=product_name, batch_number=batch_number,
        page=page, page_size=page_size,
    )
    return paginated_response(
        data=[
            InspectionRecordListItem(
                id=it.id,
                product_name=it.product_name,
                batch_number=it.batch_number,
                form_id=it.form_id,
                standard_type=it.standard_type,
                all_pass=it.all_pass,
                excel_filename=it.excel_filename,
                created_at=it.created_at,
            ).model_dump(mode="json")
            for it in items
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/lc/records/{record_id}", summary="查询单条检验记录详情（含杂质明细）")
async def get_lc_record(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    detail = await lc_report_service.get_record_detail(db, record_id)
    if not detail:
        raise HTTPException(status_code=404, detail="检验记录不存在")
    return success_response(data=detail.model_dump(mode="json"))


@router.delete("/lc/records/{record_id}", summary="删除检验记录（软删除）")
async def delete_lc_record(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:lc:upload")),
) -> JSONResponse:
    result = await delete_inspection_record(db, record_id)
    if not result:
        raise HTTPException(status_code=404, detail="检验记录不存在")
    return success_response(message="已删除")
