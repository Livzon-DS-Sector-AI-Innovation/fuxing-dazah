"""检测报告 API 端点：上传、匹配、下载、预览、删除与元数据。"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundException
from app.core.response import success_response
from app.modules.meter import service
from app.modules.meter.api._helpers import _build_report_items
from app.modules.meter.api._router import router
from app.modules.meter.schemas import (
    ReportResponse,
    UpdateReportRequest,
)

# ═══════════════════════════════════════════
# 检测报告
# ═══════════════════════════════════════════


@router.post("/reports", summary="上传检测报告")
async def upload_report(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.core.config import get_settings

    settings_obj = get_settings()
    form = await request.form(max_part_size=settings_obj.MAX_UPLOAD_SIZE_MB * 1024 * 1024)

    file = form.get("file")
    if file is None or not hasattr(file, "read"):
        return JSONResponse(status_code=400, content={"code": 400, "message": "缺少 file 参数"})

    instrument_id_raw = form.get("instrument_id")
    instrument_id: UUID | None = None
    if instrument_id_raw:
        try:
            instrument_id = UUID(str(instrument_id_raw))
        except ValueError:
            pass

    gas_detector_id_raw = form.get("gas_detector_id")
    gas_detector_id: UUID | None = None
    if gas_detector_id_raw:
        try:
            gas_detector_id = UUID(str(gas_detector_id_raw))
        except ValueError:
            pass

    report_date_raw = form.get("report_date")
    report_date_val: date | None = None
    if report_date_raw:
        try:
            report_date_val = date.fromisoformat(str(report_date_raw))
        except ValueError:
            pass

    remark_val: str | None = str(form.get("remark")) if form.get("remark") else None

    report = await service.upload_report(
        db,
        file=file,  # type: ignore[arg-type]
        instrument_id=instrument_id,
        gas_detector_id=gas_detector_id,
        report_date=report_date_val,
        remark=remark_val,
    )
    return success_response(
        ReportResponse(
            id=str(report.id),
            instrument_id=str(report.instrument_id) if report.instrument_id else None,
            gas_detector_id=str(report.gas_detector_id) if report.gas_detector_id else None,
            file_name=report.file_name,
            file_size=report.file_size,
            content_type=report.content_type,
            certificate_no=report.certificate_no,
            report_date=report.report_date,
            remark=report.remark,
            uploaded_at=report.created_at,
        ).model_dump(mode="json"),
        status_code=201,
    )



@router.get("/reports/match-one", summary="按名称+编号匹配台账（供人工修正后重新关联）")
async def match_one(
    instrument_name: str | None = Query(default=None, description="器具名称"),
    serial_number: str | None = Query(default=None, description="出厂编号/产品编号"),
    source: str | None = Query(default=None, pattern="^(instrument|gas_detector)$", description="限定台账类型"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    # 注意：此静态路由必须注册在 /reports/{report_id} 之前，否则会被动态路由吞掉（UUID 解析 422）
    result = await service.match_one(db, instrument_name, serial_number, source)
    return success_response(result)



@router.get("/reports/{report_id}", summary="获取检测报告元数据")
async def get_report(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    report = await service.get_report(db, report_id)
    return success_response(
        ReportResponse(
            id=str(report.id),
            instrument_id=str(report.instrument_id) if report.instrument_id else None,
            gas_detector_id=str(report.gas_detector_id) if report.gas_detector_id else None,
            file_name=report.file_name,
            file_size=report.file_size,
            content_type=report.content_type,
            certificate_no=report.certificate_no,
            report_date=report.report_date,
            remark=report.remark,
            uploaded_at=report.created_at,
        ).model_dump(mode="json")
    )



@router.get("/reports/{report_id}/download", summary="下载检测报告文件")
async def download_report(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    report = await service.get_report(db, report_id)
    result = await service.download_report_data(report)
    if result is None:
        raise NotFoundException("检测报告文件", str(report_id))
    data, content_type = result
    # 去除引号/换行等控制字符，避免 Content-Disposition 头注入
    filename = (
        report.file_name.replace('"', "").replace("\r", "").replace("\n", "")
        .encode("ascii", "ignore").decode()
    ) or "report"
    return StreamingResponse(
        iter([data]),
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(data)),
        },
    )



@router.get("/reports/{report_id}/preview", summary="在线预览检测报告文件")
async def preview_report(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    report = await service.get_report(db, report_id)
    result = await service.download_report_data(report)
    if result is None:
        raise NotFoundException("检测报告文件", str(report_id))
    data, content_type = result
    # 去除引号/换行等控制字符，避免 Content-Disposition 头注入
    filename = (
        report.file_name.replace('"', "").replace("\r", "").replace("\n", "")
        .encode("ascii", "ignore").decode()
    ) or "report"
    return StreamingResponse(
        iter([data]),
        media_type=content_type,
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Content-Length": str(len(data)),
        },
    )



@router.delete("/reports/{report_id}", summary="删除检测报告（软删除）")
async def delete_report(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await service.delete_report(db, report_id)
    return success_response(message="删除成功")



@router.get("/instruments/{instrument_id}/reports", summary="获取标准计量器具的报告列表")
async def list_instrument_reports(
    instrument_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    reports = await service.list_instrument_reports(db, instrument_id)
    items = _build_report_items(reports)
    return success_response(items)



@router.get("/gas-detectors/{detector_id}/reports", summary="获取探测器的报告列表")
async def list_gas_detector_reports(
    detector_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    reports = await service.list_gas_detector_reports(db, detector_id)
    items = _build_report_items(reports)
    return success_response(items)



@router.put("/reports/{report_id}", summary="手动修改检测报告证书编号")
async def update_report(
    report_id: UUID,
    body: UpdateReportRequest,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    report = await service.update_report_certificate_no(db, report_id, body.certificate_no)
    return success_response(
        ReportResponse(
            id=str(report.id),
            instrument_id=str(report.instrument_id) if report.instrument_id else None,
            gas_detector_id=str(report.gas_detector_id) if report.gas_detector_id else None,
            file_name=report.file_name,
            file_size=report.file_size,
            content_type=report.content_type,
            certificate_no=report.certificate_no,
            report_date=report.report_date,
            remark=report.remark,
            uploaded_at=report.created_at,
        ).model_dump(mode="json")
    )
