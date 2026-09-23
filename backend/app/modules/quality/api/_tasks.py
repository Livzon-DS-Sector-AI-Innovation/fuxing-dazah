"""tasks API 路由（api.py 拆分）。"""

import uuid
from datetime import date, datetime
from io import BytesIO
from urllib.parse import quote

from fastapi import (
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.quality import storage as quality_storage
from app.modules.quality.api._common import (
    _safe_filename,
    router,
)
from app.modules.quality.repository import (
    create_task_attachment,
    delete_task_attachment,
    get_task_attachment,
    get_test_task,
    get_test_task_by_batch_number,
    list_task_attachments,
    list_task_reviews,
    update_test_task_report_date,
)
from app.modules.quality.schemas import (
    TestResultCreate,
    TestResultsUpdate,
    TestTaskCreate,
    TestTaskReportDateUpdate,
    TestTaskReviewRequest,
    TestTaskStatusUpdate,
)
from app.modules.quality.service import (
    _norm_date_str,
    test_task_service,
)
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission


@router.post("/tasks", summary="创建检验任务（从标准库快照项目行）")
async def create_test_task_endpoint(
    payload: TestTaskCreate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:task:create")),
) -> JSONResponse:
    detail = await test_task_service.create_task(db, payload)
    return success_response(data=detail.model_dump(mode="json"), message="任务创建成功", status_code=201)


@router.get("/tasks", summary="检验任务分页列表")
async def list_test_task_endpoint(
    product_name: str | None = Query(default=None, description="产品名称（模糊搜索）"),
    status: str | None = Query(default=None, description="状态筛选：in_progress/pending_review/completed/void"),
    report_date: str | None = Query(default=None, description="出报日期精确筛选（YYYY-MM-DD）"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items, total = await test_task_service.list_tasks(
        db, product_name, status, page, page_size, report_date=report_date,
    )
    return paginated_response(
        data=[it.model_dump(mode="json") for it in items],
        page=page, page_size=page_size, total=total,
    )


@router.get("/tasks/summary", summary="按 SOP 汇总各批次检验结果（以 SOP 为索引）")
async def task_summary_by_sop_endpoint(
    product_name: str | None = Query(default=None, description="产品名称（模糊搜索）"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    data = await test_task_service.summary_by_sop(db, product_name)
    return success_response(data=data)


@router.get("/tasks/{task_id}", summary="检验任务详情（含结果行）")
async def get_test_task_endpoint(
    task_id: uuid.UUID, db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    detail = await test_task_service.get_task_detail(db, task_id)
    if not detail:
        raise HTTPException(status_code=404, detail="检验任务不存在")
    return success_response(data=detail.model_dump(mode="json"))


@router.put("/tasks/{task_id}/results", summary="批量填报检验结果")
async def update_test_task_results_endpoint(
    task_id: uuid.UUID,
    payload: TestResultsUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:task:fill")),
) -> JSONResponse:
    detail = await test_task_service.update_results(db, task_id, payload, filled_by=user.id)
    return success_response(data=detail.model_dump(mode="json"), message="已保存")


@router.post("/tasks/{task_id}/results", summary="追加临时结果行")
async def add_test_task_result_endpoint(
    task_id: uuid.UUID,
    payload: TestResultCreate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:task:fill")),
) -> JSONResponse:
    row = await test_task_service.add_result(db, task_id, payload)
    return success_response(data=row.model_dump(mode="json"), message="已添加", status_code=201)


@router.post("/tasks/{task_id}/parse-lc", summary="上传液相计算表解析并填入任务（P1）")
async def parse_lc_into_task_endpoint(
    task_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:task:fill")),
) -> JSONResponse:
    """解析液相计算表：结果按项目名映射填入任务结果行（判定以标准库快照为准）。"""
    filename = file.filename or "unknown.xlsx"
    if not filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 或 .xls")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件超过 10MB")
    detail, filled, unmatched = await test_task_service.parse_lc_into_task(
        db, task_id, content, filename, filled_by=_user.id
    )
    # 原始计算表自动归档为任务附件（电子审核原始证据）
    object_key = f"{task_id}/{uuid.uuid4().hex[:12]}_{_safe_filename(filename)}"
    quality_storage.upload_attachment(
        object_key, content,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    await create_task_attachment(db, {
        "task_id": task_id,
        "filename": filename,
        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "object_key": object_key,
        "size": len(content),
        "source": "parse",
        "remark": "液相计算表（上传解析自动归档）",
    })
    msg = f"解析映射完成：已填入 {len(filled)} 项"
    if filled:
        msg += f"（{'、'.join(filled)}）"
    if unmatched:
        msg += f"；未匹配 {len(unmatched)} 项：{'、'.join(unmatched)}"
    return success_response(data=detail.model_dump(mode="json"), message=msg)


@router.post("/tasks/{task_id}/attachments", summary="上传任务原始证据附件（计算表/图谱等）")
async def upload_task_attachment_endpoint(
    task_id: uuid.UUID,
    file: UploadFile = File(...),
    remark: str = Form(""),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:task:fill")),
) -> JSONResponse:
    task = await get_test_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="检验任务不存在")
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名为空")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="超过20MB")
    object_key = f"{task_id}/{uuid.uuid4().hex[:12]}_{_safe_filename(file.filename)}"
    quality_storage.upload_attachment(object_key, content, file.content_type or "application/octet-stream")
    att = await create_task_attachment(db, {
        "task_id": task_id,
        "filename": file.filename,
        "content_type": file.content_type or "application/octet-stream",
        "object_key": object_key,
        "size": len(content),
        "uploaded_by": user.id,
        "source": "manual",
        "remark": remark or None,
    })
    return success_response(
        data={"id": str(att.id), "filename": att.filename}, message="附件已上传", status_code=201,
    )


@router.get("/tasks/{task_id}/attachments", summary="任务原始证据附件列表")
async def list_task_attachments_endpoint(
    task_id: uuid.UUID, db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items = await list_task_attachments(db, task_id)
    return success_response(data=[
        {
            "id": str(a.id),
            "filename": a.filename,
            "content_type": a.content_type,
            "size": a.size,
            "source": a.source,
            "remark": a.remark,
            "uploaded_by": str(a.uploaded_by) if a.uploaded_by else None,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in items
    ])


@router.get("/tasks/{task_id}/attachments/{attachment_id}/download", summary="下载任务附件")
async def download_task_attachment_endpoint(
    task_id: uuid.UUID, attachment_id: uuid.UUID, db: AsyncSession = Depends(get_db),
):
    att = await get_task_attachment(db, attachment_id)
    if not att or att.task_id != task_id:
        raise HTTPException(status_code=404, detail="附件不存在")
    data = quality_storage.read_attachment(att.object_key)
    if data is None:
        raise HTTPException(status_code=404, detail="附件文件已丢失")
    encoded = quote(att.filename)
    return StreamingResponse(
        BytesIO(data),
        media_type=att.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{att.filename}"; filename*=UTF-8\'\'{encoded}'},
    )


@router.delete("/tasks/{task_id}/attachments/{attachment_id}", summary="删除任务附件（软删除）")
async def delete_task_attachment_endpoint(
    task_id: uuid.UUID, attachment_id: uuid.UUID, db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:task:review")),
) -> JSONResponse:
    att = await delete_task_attachment(db, attachment_id)
    if not att or att.task_id != task_id:
        raise HTTPException(status_code=404, detail="附件不存在")
    quality_storage.delete_attachment(att.object_key)
    return success_response(message="已删除")


@router.post("/tasks/{task_id}/review", summary="复核通过（双人复核：两名不同复核人通过后任务完成）")
async def review_task_endpoint(
    task_id: uuid.UUID,
    payload: TestTaskReviewRequest = Body(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:task:review")),
) -> JSONResponse:
    detail, approved_count, advanced = await test_task_service.add_review(
        db, task_id, user.id, payload.comment if payload else None,
    )
    data = detail.model_dump(mode="json")
    data["approved_count"] = approved_count
    data["review_required"] = test_task_service.REVIEW_REQUIRED_COUNT
    if advanced:
        msg = f"复核通过（{approved_count}/{test_task_service.REVIEW_REQUIRED_COUNT}），任务已完成"
    else:
        msg = f"复核已记录（{approved_count}/{test_task_service.REVIEW_REQUIRED_COUNT}），等待另一位复核人"
    return success_response(data=data, message=msg)


@router.get("/tasks/{task_id}/reviews", summary="任务复核记录")
async def list_task_reviews_endpoint(
    task_id: uuid.UUID, db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    reviews = await list_task_reviews(db, task_id)
    return success_response(data=[
        {
            "reviewer_id": str(r.reviewer_id),
            "comment": r.comment,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in reviews
    ])


@router.put("/tasks/{task_id}/status", summary="任务状态流转（重开/作废）")
async def update_test_task_status_endpoint(
    task_id: uuid.UUID,
    payload: TestTaskStatusUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:task:review")),
) -> JSONResponse:
    detail = await test_task_service.update_status(db, task_id, payload)
    return success_response(data=detail.model_dump(mode="json"), message="状态已更新")


@router.put("/tasks/{task_id}/report-date", summary="补录/修改出报日期（关联当日机器人任务推送）")
async def update_test_task_report_date_endpoint(
    task_id: uuid.UUID,
    payload: TestTaskReportDateUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:task:fill")),
) -> JSONResponse:
    detail = await test_task_service.update_report_date(db, task_id, payload)
    return success_response(
        data=detail.model_dump(mode="json"),
        message="出报日期已更新" if payload.report_date else "出报日期已清空",
    )


@router.post("/tasks/report-date-batch", summary="批量补录出报日期（Excel：批号列+出报日期列）")
async def batch_report_date_endpoint(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:task:fill")),
) -> JSONResponse:
    import io as _io

    import openpyxl

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    try:
        wb = openpyxl.load_workbook(_io.BytesIO(content))
        ws = wb.active
        raw_rows = list(ws.iter_rows(min_row=2, values_only=True))
    except Exception:
        raise HTTPException(status_code=400, detail="Excel 解析失败") from None

    updated = 0
    skipped: list[str] = []
    for row in raw_rows:
        if not row or not row[0]:
            continue
        batch = str(row[0]).strip()
        date_cell = row[1] if len(row) > 1 else None
        if isinstance(date_cell, (datetime, date)):
            report_date = date_cell.strftime("%Y-%m-%d")
        elif date_cell:
            report_date = _norm_date_str(str(date_cell).strip())
        else:
            # 空单元格跳过：此前 report_date=None 会静默清空已有出报日期
            skipped.append(f"{batch}:日期为空，未修改")
            continue
        task = await get_test_task_by_batch_number(db, batch)
        if not task:
            skipped.append(f"{batch}:未找到任务")
            continue
        await update_test_task_report_date(db, task.id, report_date)
        updated += 1
    return success_response(
        data={"updated": updated, "skipped": skipped},
        message=f"已更新 {updated} 个任务的出报日期" + (f"，跳过 {len(skipped)} 条" if skipped else ""),
    )


@router.delete("/tasks/{task_id}/results/{result_id}", summary="删除单行结果（软删除）")
async def delete_test_task_result_endpoint(
    task_id: uuid.UUID, result_id: uuid.UUID, db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:task:review")),
) -> JSONResponse:
    row = await test_task_service.delete_result(db, task_id, result_id)
    if not row:
        raise HTTPException(status_code=404, detail="结果行不存在")
    return success_response(message="已删除")


@router.delete("/tasks/{task_id}", summary="删除检验任务（软删级联结果行）")
async def delete_test_task_endpoint(
    task_id: uuid.UUID, db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:task:review")),
) -> JSONResponse:
    task = await test_task_service.delete_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="检验任务不存在")
    return success_response(message="已删除")
