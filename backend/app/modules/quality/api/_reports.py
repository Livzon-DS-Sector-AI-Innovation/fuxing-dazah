"""reports API 路由（api.py 拆分）。"""

import asyncio
import uuid
from datetime import datetime, time
from io import BytesIO
from pathlib import Path

from fastapi import (
    Body,
    Depends,
    HTTPException,
    Query,
)
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.core.time import APP_TZ, today
from app.modules.quality import storage as quality_storage
from app.modules.quality.api._common import (
    REPORT_TEMPLATE_DIR,
    _coa_response,
    _render_cao_file,
    router,
)
from app.modules.quality.repository import (
    count_report_records_since,
    create_report_record,
    get_report_record,
    is_serial_unique_violation,
    list_report_records,
)
from app.modules.quality.schemas import (
    GenerateReportRequest,
    TaskReportGenerateRequest,
)
from app.modules.quality.service import (
    lc_report_service,
    test_task_service,
)
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission


@router.post("/report/generate", summary="生成报告单")
async def generate_report(
    payload: GenerateReportRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:report:generate")),
):
    tp = REPORT_TEMPLATE_DIR / payload.template
    if not quality_storage.ensure_template_local(payload.template).is_file():
        raise HTTPException(status_code=404, detail=f"模板不存在：{payload.template}")

    # 获取填充数据
    fill_data: dict = {}
    product_name = ""
    batch_number = ""
    record_id: uuid.UUID | None = None

    if payload.inspection_record_id:
        # 从数据库加载检验记录自动填充
        detail = await lc_report_service.get_record_detail(db, payload.inspection_record_id)
        if not detail:
            raise HTTPException(status_code=404, detail="检验记录不存在")
        fill_data = lc_report_service.build_report_data(detail.report)
        product_name = detail.product_name
        batch_number = detail.batch_number
        record_id = detail.id
    elif payload.data:
        fill_data = payload.data
        product_name = fill_data.get("产品名称", "")
        batch_number = fill_data.get("批号", "")
    else:
        raise HTTPException(status_code=400, detail="请提供 inspection_record_id 或 data")

    # 流水号按北京时间计日：当天已生成的报告数作为序号起点。
    # 并发撞号时（唯一索引冲突）重算流水号重试，最多 3 次。
    for attempt in range(3):
        today_start = datetime.combine(today(), time.min, tzinfo=APP_TZ)
        serial_no = f"{today():%y%m%d}{await count_report_records_since(db, today_start) + 1:02d}"
        # 直接覆盖：保证 docx 内流水号与入库流水号一致（重试时也能换新号）
        fill_data["流水号"] = serial_no
        output_path, output_filename, content = _render_cao_file(
            tp, fill_data, product_name, batch_number
        )
        try:
            # 两条路径（inspection_record_id / payload.data）都落库，
            # 否则流水号不入库不计数，下一次出报拿到同一个号
            await create_report_record(
                db=db,
                inspection_record_id=record_id,
                template_path=payload.template,
                product_name=product_name,
                batch_number=batch_number,
                file_path=str(output_path),
                file_size=output_path.stat().st_size,
                serial_no=serial_no,
            )
            break
        except IntegrityError as exc:
            if not is_serial_unique_violation(exc) or attempt == 2:
                raise
            await db.rollback()  # flush 失败后 session 已不可用，回滚后才能重查计数
            await asyncio.sleep(0.1 * (attempt + 1))  # 等并发对手提交后再重算

    return _coa_response(output_filename, content)


@router.post("/tasks/{task_id}/report", summary="从已完成任务按标准文件逐份生成 COA 报告单")
async def generate_task_report(
    task_id: uuid.UUID,
    payload: TaskReportGenerateRequest | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:report:generate")),
):
    # 逐份生成：每个标准文件各出一份 COA（行归属其标准文件；模板按该文件 COA 绑定取）。
    # 并发撞号时（唯一索引冲突）整体重算流水号重试，最多 3 次。
    for attempt in range(3):
        try:
            splits = await test_task_service.build_task_report_splits(db, task_id)
            generated = []
            for split in splits:
                template = split["template"]
                tp = REPORT_TEMPLATE_DIR / template
                if not quality_storage.ensure_template_local(template).is_file():
                    raise HTTPException(status_code=404, detail=f"模板不存在：{template}")
                output_path, output_filename, _content = _render_cao_file(
                    tp, split["fill_data"], split["product_name"], split["batch_number"],
                    suffix=split["doc"].file_no,
                )
                record = await create_report_record(
                    db=db,
                    test_task_id=task_id,
                    template_path=template,
                    product_name=split["product_name"],
                    batch_number=split["batch_number"],
                    file_path=str(output_path),
                    file_size=output_path.stat().st_size,
                    serial_no=split["fill_data"].get("流水号", ""),
                )
                generated.append({
                    "report_id": str(record.id),
                    "filename": output_filename,
                    "file_no": split["doc"].file_no,
                    "template_path": template,
                })
            msg = f"已按标准文件逐份生成 {len(generated)} 份 COA"
            skipped = next((s["skipped_file_nos"] for s in splits if s.get("skipped_file_nos")), [])
            if skipped:
                msg += f"；跳过无结果行的标准文件：{'、'.join(skipped)}"
            return success_response(data=generated, message=msg)
        except IntegrityError as exc:
            if not is_serial_unique_violation(exc) or attempt == 2:
                raise
            await db.rollback()  # flush 失败后 session 已不可用，回滚后才能重查计数
            await asyncio.sleep(0.1 * (attempt + 1))  # 等并发对手提交后再重算
    raise HTTPException(status_code=500, detail="流水号重试次数用尽，请重新生成")


# ─── 报告单记录 ───


@router.get("/report/records", summary="报告单历史列表")
async def list_reports(
    product_name: str | None = Query(default=None),
    batch_number: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items, total = await list_report_records(
        db, product_name=product_name, batch_number=batch_number,
        page=page, page_size=page_size,
    )
    return paginated_response(
        data=[
            {
                "id": str(it.id),
                "inspection_record_id": str(it.inspection_record_id) if it.inspection_record_id else None,
                "test_task_id": str(it.test_task_id) if it.test_task_id else None,
                "template_path": it.template_path,
                "product_name": it.product_name,
                "batch_number": it.batch_number,
                "serial_no": it.serial_no,
                "file_path": it.file_path,
                "file_size": it.file_size,
                "created_at": it.created_at.isoformat() if it.created_at else None,
            }
            for it in items
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/report/records/{report_id}/download", summary="下载已生成的报告单")
async def download_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:report:read")),
):
    report = await get_report_record(db, report_id)
    if not report or not report.file_path:
        raise HTTPException(status_code=404, detail="报告文件不存在")
    fp = Path(report.file_path)
    # MinIO 优先（容器重建后本地文件丢失时仍可下载），本地副本兜底
    minio_data = quality_storage.read_report_from_minio(fp.name)
    if minio_data:
        return StreamingResponse(
            BytesIO(minio_data),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{fp.name}"'},
        )
    if not fp.exists():
        raise HTTPException(status_code=404, detail="报告文件已被清理")
    return FileResponse(
        str(fp),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=fp.name,
    )
