"""Safety API — URS 智能审核 endpoints。

属于 EHS变更功能域（与 ehs_changes 并列）。全部端点挂 /api/v1/safety/。
"""

import logging
import uuid

from fastapi import APIRouter, Depends, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import ApiResponse
from app.modules.safety.schemas.urs import (
    EQUIPMENT_CATEGORY_OPTIONS,
    PROCUREMENT_PURPOSE_OPTIONS,
    RISK_DIMENSION_KEYS,
    RISK_LEVEL_OPTIONS,
    URS_STATUS_OPTIONS,
    URSAppeal,
    URSAssessmentConfirm,
    URSCreate,
    URSItemReview,
    URSItemReviewBatch,
    URSReportResponse,
    URSReviewDocumentResponse,
    URSStandardItemResponse,
    URSStatsResponse,
    URSUpdate,
)
from app.modules.safety.service.ehs_change.urs import URSService

logger = logging.getLogger(__name__)

urs_router = APIRouter()


@urs_router.get("/urs-reports/enums", response_model=ApiResponse, summary="URS 枚举选项")
async def get_enums():
    return ApiResponse(data={
        "equipment_categories": EQUIPMENT_CATEGORY_OPTIONS,
        "procurement_purposes": PROCUREMENT_PURPOSE_OPTIONS,
        "risk_levels": RISK_LEVEL_OPTIONS,
        "status_options": URS_STATUS_OPTIONS,
        "risk_dimension_keys": RISK_DIMENSION_KEYS,
    })


@urs_router.get("/urs-reports", response_model=ApiResponse, summary="URS 审核列表")
async def list_reports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    department: str | None = Query(None),
    equipment_category: str | None = Query(None),
    status: str | None = Query(None),
    keyword: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    service = URSService(db)
    skip = (page - 1) * page_size
    items, total = await service.list_reports(
        skip, page_size,
        department=department,
        equipment_category=equipment_category,
        status=status,
        keyword=keyword,
    )
    return ApiResponse(
        data=[URSReportResponse.model_validate(r) for r in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@urs_router.get("/urs-reports/stats", response_model=ApiResponse, summary="URS 统计")
async def get_stats(db: AsyncSession = Depends(get_db)):
    service = URSService(db)
    stats = await service.get_stats()
    return ApiResponse(data=URSStatsResponse.model_validate(stats))


@urs_router.post("/urs-reports", response_model=ApiResponse, summary="创建 URS 审核")
async def create_report(
    data: URSCreate,
    db: AsyncSession = Depends(get_db),
):
    service = URSService(db)
    report = await service.create_report(data.model_dump())
    await db.commit()
    # INSERT 有 RETURNING 回填，但 commit 后统一 re-fetch 更稳妥（避免懒加载 MissingGreenlet）
    report = await service.get_report(report.id)
    return ApiResponse(data=URSReportResponse.model_validate(report), message="创建成功")


@urs_router.post("/urs-reports/parse-document", response_model=ApiResponse, summary="解析 URS 文档提取字段")
async def parse_document(payload: dict):
    text = payload.get("document_text") or ""
    if not text.strip():
        return ApiResponse(code=400, message="文档内容为空", data=None)
    result = await URSService.parse_urs_document(text)
    return ApiResponse(data=result)


@urs_router.post("/urs-reports/parse-upload", response_model=ApiResponse, summary="上传并完整解析 URS 附件")
async def parse_urs_upload(file: UploadFile, db: AsyncSession = Depends(get_db)):
    """multipart 上传 URS 附件 → 提取完整原文 → AI 提取元数据+结构化要点。

    返回：equipment_name / equipment_category / department / procurement_purpose /
          urs_content（完整原文）/ structured_points / attachment_path。
    """
    service = URSService(db)
    try:
        result = await service.parse_urs_attachment(file)
    except ValueError as e:
        return ApiResponse(code=400, message=str(e), data=None)
    except Exception:
        logger.exception("URS 附件解析失败")
        return ApiResponse(code=500, message="附件解析失败", data=None)
    return ApiResponse(data=result, message="解析完成")


@urs_router.get("/urs-reports/{report_id}", response_model=ApiResponse, summary="URS 详情")
async def get_report(report_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = URSService(db)
    report = await service.get_report(report_id)
    if report is None:
        return ApiResponse(code=404, message="记录不存在", data=None)
    return ApiResponse(data=URSReportResponse.model_validate(report))


@urs_router.put("/urs-reports/{report_id}", response_model=ApiResponse, summary="更新 URS（draft 阶段）")
async def update_report(
    report_id: uuid.UUID,
    data: URSUpdate,
    db: AsyncSession = Depends(get_db),
):
    service = URSService(db)
    report = await service.get_report(report_id)
    if report is None:
        return ApiResponse(code=404, message="记录不存在", data=None)
    if report.review_status != "draft":
        return ApiResponse(code=400, message="仅草稿状态可修改", data=None)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(report, key, value)
    await db.commit()
    report = await service.get_report(report_id)
    return ApiResponse(data=URSReportResponse.model_validate(report), message="更新成功")


@urs_router.delete("/urs-reports/{report_id}", response_model=ApiResponse, summary="删除 URS（软删除）")
async def delete_report(report_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = URSService(db)
    ok = await service.delete_report(report_id)
    if not ok:
        return ApiResponse(code=404, message="记录不存在", data=None)
    await db.commit()
    return ApiResponse(message="删除成功")


# ══════════════════════════════════════════════════════════
# 状态机
# ══════════════════════════════════════════════════════════


@urs_router.post("/urs-reports/{report_id}/submit", response_model=ApiResponse, summary="提交 → 触发 AI 适用性评估")
async def submit_report(report_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = URSService(db)
    try:
        report = await service.submit_report(report_id)
        await db.commit()
        # 提交后 spawn 后台评估（请求 session 已 commit）
        service.trigger_assessment_background(report_id)
        # UPDATE 后 re-fetch，避免 updated_at 懒加载 MissingGreenlet
        report = await service.get_report(report_id)
        return ApiResponse(data=URSReportResponse.model_validate(report), message="已提交，AI 评估进行中")
    except ValueError as e:
        return ApiResponse(code=400, message=str(e), data=None)
    except Exception as e:
        return ApiResponse(code=500, message=f"提交失败: {e}", data=None)


@urs_router.get("/urs-reports/{report_id}/assessment", response_model=ApiResponse, summary="获取风险评估结果")
async def get_assessment(report_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = URSService(db)
    report = await service.get_report(report_id)
    if report is None:
        return ApiResponse(code=404, message="记录不存在", data=None)
    return ApiResponse(data=URSReportResponse.model_validate(report))


@urs_router.post("/urs-reports/{report_id}/assessment/confirm", response_model=ApiResponse, summary="人工确认/修正风险画像")
async def confirm_assessment(
    report_id: uuid.UUID,
    data: URSAssessmentConfirm,
    db: AsyncSession = Depends(get_db),
):
    service = URSService(db)
    try:
        report = await service.confirm_assessment(
            report_id,
            comment=data.comment,
            corrections=data.corrections,
        )
        await db.commit()
        if report is None:
            return ApiResponse(code=404, message="记录不存在", data=None)
        # UPDATE 后 re-fetch，避免 updated_at 懒加载 MissingGreenlet
        report = await service.get_report(report_id)
        return ApiResponse(data=URSReportResponse.model_validate(report), message="已确认")
    except ValueError as e:
        return ApiResponse(code=400, message=str(e), data=None)


@urs_router.get("/urs-reports/{report_id}/adaptation", response_model=ApiResponse, summary="获取适配清单")
async def get_adaptation(report_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = URSService(db)
    items = await service.get_items(report_id)
    return ApiResponse(data=[URSStandardItemResponse.model_validate(i) for i in items])


@urs_router.post("/urs-reports/{report_id}/adaptation/run", response_model=ApiResponse, summary="触发标准适配")
async def run_adaptation(report_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = URSService(db)
    try:
        report = await service.run_adaptation(report_id)
        await db.commit()
        if report is None:
            return ApiResponse(code=404, message="记录不存在", data=None)
        # UPDATE 后 re-fetch，避免 updated_at 懒加载 MissingGreenlet
        report = await service.get_report(report_id)
        return ApiResponse(data=URSReportResponse.model_validate(report), message="适配完成")
    except ValueError as e:
        return ApiResponse(code=400, message=str(e), data=None)


@urs_router.get("/urs-reports/{report_id}/items", response_model=ApiResponse, summary="审核条目列表")
async def get_items(report_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = URSService(db)
    items = await service.get_items(report_id)
    return ApiResponse(data=[URSStandardItemResponse.model_validate(i) for i in items])


# ⚠️ 注意：FastAPI 按定义顺序匹配路径，/items/batch 必须定义在 /items/{item_id} 之前，
# 否则 "batch" 会被 {item_id} 捕获导致 422（uuid 解析失败 + body 字段错配）。
@urs_router.put("/urs-reports/{report_id}/items/batch", response_model=ApiResponse, summary="批量审核确认")
async def review_items_batch(
    report_id: uuid.UUID,
    data: URSItemReviewBatch,
    db: AsyncSession = Depends(get_db),
):
    service = URSService(db)
    try:
        updated = await service.review_items_batch(
            report_id, [it.model_dump() for it in data.items],
        )
        await db.commit()
        # UPDATE 后 re-fetch 全部条目，避免字段懒加载 MissingGreenlet
        all_items = await service.get_items(report_id)
        updated_ids = {it.id for it in updated}
        fresh = [it for it in all_items if it.id in updated_ids]
        return ApiResponse(
            data=[URSStandardItemResponse.model_validate(i) for i in fresh],
            message=f"已更新 {len(fresh)} 条",
        )
    except ValueError as e:
        return ApiResponse(code=400, message=str(e), data=None)


@urs_router.put("/urs-reports/{report_id}/items/{item_id}", response_model=ApiResponse, summary="单条审核确认")
async def review_item(
    report_id: uuid.UUID,
    item_id: uuid.UUID,
    data: URSItemReview,
    db: AsyncSession = Depends(get_db),
):
    service = URSService(db)
    item = await service.review_item(
        report_id, item_id,
        verdict=data.verdict,
        comment=data.comment,
        rectification_required=data.rectification_required,
    )
    if item is None:
        return ApiResponse(code=404, message="审核条目不存在", data=None)
    await db.commit()
    # UPDATE 后 re-fetch，避免字段懒加载 MissingGreenlet
    item = await service.get_item(report_id, item_id)
    return ApiResponse(data=URSStandardItemResponse.model_validate(item), message="已更新")


@urs_router.get("/urs-reports/{report_id}/conclusion", response_model=ApiResponse, summary="获取审核结论")
async def get_conclusion(report_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = URSService(db)
    report = await service.get_report(report_id)
    if report is None:
        return ApiResponse(code=404, message="记录不存在", data=None)
    return ApiResponse(data=URSReportResponse.model_validate(report))


@urs_router.post("/urs-reports/{report_id}/conclusion/generate", response_model=ApiResponse, summary="触发结论生成")
async def generate_conclusion(report_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = URSService(db)
    try:
        report = await service.generate_conclusion(report_id)
        await db.commit()
        if report is None:
            return ApiResponse(code=404, message="记录不存在", data=None)
        # UPDATE 后 re-fetch，避免 updated_at 懒加载 MissingGreenlet
        report = await service.get_report(report_id)
        return ApiResponse(data=URSReportResponse.model_validate(report), message="结论已生成")
    except ValueError as e:
        return ApiResponse(code=400, message=str(e), data=None)


@urs_router.post("/urs-reports/{report_id}/appeal", response_model=ApiResponse, summary="提交申诉")
async def submit_appeal(
    report_id: uuid.UUID,
    data: URSAppeal,
    db: AsyncSession = Depends(get_db),
):
    service = URSService(db)
    try:
        report = await service.submit_appeal(report_id, data.reason)
        await db.commit()
        if report is None:
            return ApiResponse(code=404, message="记录不存在", data=None)
        # UPDATE 后 re-fetch，避免 updated_at 懒加载 MissingGreenlet
        report = await service.get_report(report_id)
        return ApiResponse(data=URSReportResponse.model_validate(report), message="申诉已受理，正在重新评估")
    except ValueError as e:
        return ApiResponse(code=400, message=str(e), data=None)


@urs_router.get("/urs-reports/{report_id}/documents", response_model=ApiResponse, summary="AI 审核文档列表")
async def get_documents(report_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    service = URSService(db)
    docs = await service.get_documents(report_id)
    return ApiResponse(data=[URSReviewDocumentResponse.model_validate(d) for d in docs])


@urs_router.post("/urs-reports/{report_id}/export-pdf", summary="导出 URS 审核报告 PDF")
async def export_urs_pdf(report_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """导出单条 URS 审核的完整报告 PDF（基本信息/风险画像/审核结论/标准条款审核过程）。

    返回 application/pdf 二进制流，前端以 base64 下载。
    """
    from datetime import datetime as dt_module
    from urllib.parse import quote

    from fastapi.responses import Response

    service = URSService(db)
    report = await service.get_report(report_id)
    if report is None:
        return ApiResponse(code=404, message="记录不存在", data=None)
    try:
        pdf_bytes = await service.export_pdf(report_id)
    except ValueError as e:
        # 并发软删除竞态：endpoint 预取后 export_pdf 内部再取已不存在 → 映射为 404
        logger.warning("URS PDF 导出记录已不存在: report_id=%s (%s)", report_id, e)
        return ApiResponse(code=404, message="记录不存在", data=None)
    except Exception:
        # 异常细节仅记录日志，不暴露给客户端
        logger.exception("URS PDF 导出失败: report_id=%s", report_id)
        return ApiResponse(code=500, message="PDF 生成失败", data=None)

    filename = f"{report.urs_no}_URS审核报告_{dt_module.now().strftime('%Y%m%d')}.pdf"
    ascii_filename = f"URS_{report.urs_no}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{ascii_filename}\"; "
                f"filename*=UTF-8''{quote(filename)}"
            ),
            "Content-Length": str(len(pdf_bytes)),
        },
    )
