"""报告批量匹配/识别/上传与 AI 日期提取 API 端点。"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, cast
from uuid import UUID

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundException
from app.core.response import success_response
from app.modules.meter import repository as repo
from app.modules.meter import service
from app.modules.meter.ai_service import extract_and_update_date, get_meter_ai_config
from app.modules.meter.api._router import router
from app.modules.meter.schemas import (
    ExtractDateResponse,
    FileMatchItem,
    FileMatchRequest,
    ReportAnalyzeItem,
)

logger = logging.getLogger(__name__)

@router.post("/reports/match", summary="批量匹配文件名到仪表（单次最多 200 个文件）")
async def match_files(
    body: FileMatchRequest,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    results = await service.match_filenames(db, body.filenames)
    items = [FileMatchItem(**r).model_dump(mode="json") for r in results]
    return success_response(items)



@router.post("/reports/analyze", summary="批量识别报告内容并匹配台账（单次最多 200 份）")
async def analyze_report_files(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.core.config import get_settings

    settings_obj = get_settings()
    form = await request.form(max_part_size=settings_obj.MAX_UPLOAD_SIZE_MB * 1024 * 1024)

    files_raw = form.getlist("files")
    if not files_raw:
        return JSONResponse(status_code=400, content={"code": 400, "message": "缺少 files 参数"})
    if len(files_raw) > 200:
        return JSONResponse(status_code=400, content={"code": 400, "message": "单次最多 200 份文件"})

    source_raw = form.get("source")
    source: str | None = str(source_raw) if source_raw and str(source_raw) in ("instrument", "gas_detector") else None

    file_list: list[tuple[str, bytes, str]] = []
    for f in files_raw:
        f = cast(Any, f)
        if hasattr(f, "read"):
            data = await f.read()
            fn = f.filename if hasattr(f, "filename") else "unknown"
            ct = f.content_type if hasattr(f, "content_type") else "application/octet-stream"
            file_list.append((fn or "unknown", data, ct or "application/octet-stream"))

    # 同名文件防御：文件名是归档定位键，重名会互相覆盖
    names = [fn for fn, _, _ in file_list]
    if len(names) != len(set(names)):
        return JSONResponse(status_code=400, content={"code": 400, "message": "存在同名文件，请重命名后重新选择"})

    results = await service.analyze_report_files(db, file_list, source)
    return success_response(
        [ReportAnalyzeItem(**r).model_dump(mode="json") for r in results]
    )



@router.post("/reports/batch", summary="批量上传检测报告（单次最多 200 份）")
async def batch_upload_reports(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.core.config import get_settings

    settings_obj = get_settings()
    form = await request.form(max_part_size=settings_obj.MAX_UPLOAD_SIZE_MB * 1024 * 1024)

    import json

    items_json = form.get("items_json")
    if not items_json:
        return JSONResponse(status_code=400, content={"code": 400, "message": "缺少 items_json 参数"})
    try:
        items = json.loads(str(items_json))
    except json.JSONDecodeError:
        return JSONResponse(status_code=400, content={"code": 400, "message": "items_json JSON 格式错误"})
    if not isinstance(items, list) or len(items) > 200:
        return JSONResponse(status_code=400, content={"code": 400, "message": "items 必须为列表且单次最多 200 项"})

    report_date_raw = form.get("report_date")
    report_date_val: date | None = None
    if report_date_raw:
        try:
            report_date_val = date.fromisoformat(str(report_date_raw))
        except ValueError:
            pass

    remark_val: str | None = str(form.get("remark")) if form.get("remark") else None

    files_raw = form.getlist("files")
    if len(files_raw) > 200:
        return JSONResponse(status_code=400, content={"code": 400, "message": "单次最多 200 份文件"})
    file_list: list[tuple[str, bytes, str]] = []
    for f in files_raw:
        f = cast(Any, f)
        if hasattr(f, "read"):
            data = await f.read()
            fn = f.filename if hasattr(f, "filename") else "unknown"
            ct = f.content_type if hasattr(f, "content_type") else "application/octet-stream"
            file_list.append((fn or "unknown", data, ct or "application/octet-stream"))

    result = await service.batch_upload_reports(db, file_list, items, report_date=report_date_val, remark=remark_val)
    return success_response(result, status_code=201 if result["success"] > 0 else 200)



# ═══════════════════════════════════════════
# AI 日期提取（配置从环境变量 METER_AI_* 读取）
# ═══════════════════════════════════════════


@router.post("/reports/{report_id}/extract-date", summary="从报告中提取校准日期")
async def extract_date(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    import logging

    logger = logging.getLogger(__name__)

    try:
        config = get_meter_ai_config()
        if not config:
            return JSONResponse(
                status_code=400,
                content={"code": 400, "message": "请先配置环境变量 METER_AI_BASE_URL / METER_AI_API_KEY / METER_AI_MODEL"},
            )

        report = await service.get_report(db, report_id)
        result = await service.download_report_data(report)
        if result is None:
            raise NotFoundException("报告文件", str(report_id))
        pdf_data, _ = result

        # 获取关联仪表的检定周期
        calibration_cycle = None
        if report.instrument_id:
            inst = await service.get_instrument(db, report.instrument_id)
            calibration_cycle = inst.calibration_cycle_months
        # 探测器无 calibration_cycle_months 字段，保持 None

        ai_result = await extract_and_update_date(
            pdf_data, config["api_url"], config["api_key"], config["model"], calibration_cycle
        )

        if ai_result["success"]:
            # 回写数据库（asyncpg 需要 Python date 对象，不能传字符串）
            cal_date = date.fromisoformat(ai_result["calibration_date"])
            updates: dict[str, Any] = {"calibration_date": cal_date}
            if ai_result.get("next_calibration_date"):
                updates["next_calibration_date"] = date.fromisoformat(ai_result["next_calibration_date"])
            if report.instrument_id:
                await repo.update_instrument(db, report.instrument_id, updates)
            elif report.gas_detector_id:
                await repo.update_gas_detector(db, report.gas_detector_id, updates)
            # 同时将识别出的日期写入报告本身的 report_date
            await repo.update_report_date(db, report_id, cal_date)
            await db.commit()

        return success_response(
            ExtractDateResponse(**ai_result).model_dump(mode="json")
        )
    except Exception:
        logger.exception("extract_date 未捕获异常")
        return JSONResponse(
            status_code=500,
            content={"code": 500, "message": "服务器内部错误"},
        )
