"""summary API 路由（api.py 拆分）。"""

import uuid
from datetime import datetime
from io import BytesIO
from urllib.parse import quote

from fastapi import (
    Depends,
    HTTPException,
    Query,
)
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.core.time import APP_TZ, today
from app.modules.quality.api._common import (
    router,
)
from app.modules.quality.repository import (
    get_product_names,
    get_summary_by_product,
    list_report_records_between,
    list_report_records_by_date,
)
from app.modules.quality.service import (
    lc_report_service,
    test_task_service,
)

# ─── 汇总表 ───


@router.get("/summary/batch/{record_id}", summary="单批次汇总")
async def batch_summary(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    detail = await lc_report_service.get_record_detail(db, record_id)
    if not detail:
        raise HTTPException(status_code=404, detail="检验记录不存在")

    # 生成文字化判定摘要
    lines = [
        f"产品：{detail.product_name}",
        f"批号：{detail.batch_number}",
        f"标准：{detail.standard_type or '-'}",
        f"总体判定：{'合格' if detail.all_pass else '不合格'}",
        f"杂质项目数：{len(detail.impurities)}",
    ]
    if detail.report.vancomycin_b:
        vb = detail.report.vancomycin_b
        lines.append(
            f"万古霉素B：{vb.rounded_first} (判定：{'合格' if vb.is_pass else '不合格'})"
        )
    if detail.report.total_impurities:
        ti = detail.report.total_impurities
        lines.append(
            f"总杂质：{ti.rounded_first} (判定：{'合格' if ti.is_pass else '不合格'})"
        )

    return success_response(
        data={
            "record": detail.model_dump(mode="json"),
            "summary_text": "\n".join(lines),
        }
    )


@router.get("/summary/history", summary="多批次历史汇总")
async def history_summary(
    product_name: str | None = Query(default=None, description="产品名称"),
    date_from: str | None = Query(default=None, description="起始日期 ISO 格式"),
    date_to: str | None = Query(default=None, description="结束日期 ISO 格式"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    dt_from = datetime.fromisoformat(date_from) if date_from else None
    dt_to = datetime.fromisoformat(date_to) if date_to else None

    summary = await get_summary_by_product(
        db, product_name=product_name, date_from=dt_from, date_to=dt_to
    )
    return success_response(data=summary)


@router.get("/summary/daily-reports", summary="每日报告单汇总（流水号+产品+批号）")
async def daily_reports(
    date: str | None = Query(default=None, description="日期 YYYY-MM-DD，默认今天"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    day = date or today().isoformat()
    items = await list_report_records_by_date(db, day)
    return success_response(data=[
        {
            "serial_no": it.serial_no or "-",
            "product_name": it.product_name,
            "batch_number": it.batch_number,
            "template_path": it.template_path,
            "report_id": str(it.id),
            "created_at": it.created_at.astimezone(APP_TZ).strftime("%H:%M") if it.created_at else None,
        }
        for it in items
    ])


@router.get("/summary/monthly-reports", summary="按月汇总报告单流水（月末归档对账）")
async def monthly_reports(
    month: str | None = Query(default=None, description="月份 YYYY-MM，默认当月"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    m = month or today().strftime("%Y-%m")
    start = datetime.fromisoformat(f"{m}-01").replace(tzinfo=APP_TZ)
    end = (start.replace(month=start.month + 1) if start.month < 12
           else start.replace(year=start.year + 1, month=1))
    items = await list_report_records_between(db, start, end)
    by_day: dict[str, list] = {}
    for it in items:
        d = it.created_at.astimezone(APP_TZ).strftime("%Y-%m-%d")
        by_day.setdefault(d, []).append(it)
    return success_response(data={
        "month": m,
        "total": len(items),
        "days": [
            {
                "date": d,
                "count": len(lst),
                "items": [
                    {
                        "serial_no": it.serial_no or "-",
                        "product_name": it.product_name,
                        "batch_number": it.batch_number,
                        "template_path": it.template_path,
                        "report_id": str(it.id),
                        "created_at": it.created_at.astimezone(APP_TZ).strftime("%H:%M") if it.created_at else None,
                    }
                    for it in lst
                ],
            }
            for d, lst in sorted(by_day.items())
        ],
    })


@router.get("/dashboard/summary", summary="质量总览看板数据")
async def quality_dashboard(
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    data = await test_task_service.build_dashboard(db)
    return success_response(data=data)


@router.get("/tasks/report-date-template", summary="下载出报日期批量补录 Excel 模板")
async def report_date_template_endpoint():
    import io as _io

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "出报日期补录"
    ws.append(["批号", "出报日期"])
    ws.append(["HAF2608001B", "2026-09-18"])
    buf = _io.BytesIO()
    wb.save(buf)
    encoded = quote("出报日期补录模板.xlsx")
    return StreamingResponse(
        BytesIO(buf.getvalue()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="template.xlsx"; filename*=UTF-8\'\'{encoded}'},
    )


@router.get("/summary/matrix", summary="QC 汇总表矩阵：行=批次，列=全部检验项目横向列出")
async def summary_matrix(
    product_name: str | None = Query(default=None, description="产品名称"),
    date_from: str | None = Query(default=None, description="起始日期 YYYY-MM-DD"),
    date_to: str | None = Query(default=None, description="结束日期 YYYY-MM-DD"),
    include_in_progress: bool = Query(default=False, description="包含填报中的批次"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    data = await test_task_service.build_summary_matrix(
        db, product_name=product_name, date_from=date_from, date_to=date_to,
        include_in_progress=include_in_progress,
    )
    return success_response(data=data)


@router.get("/summary/matrix/export", summary="导出 QC 汇总表 Excel")
async def summary_matrix_export(
    product_name: str | None = Query(default=None, description="产品名称"),
    date_from: str | None = Query(default=None, description="起始日期 YYYY-MM-DD"),
    date_to: str | None = Query(default=None, description="结束日期 YYYY-MM-DD"),
    include_in_progress: bool = Query(default=False, description="包含填报中的批次"),
    db: AsyncSession = Depends(get_db),
):
    import io as _io

    import openpyxl

    data = await test_task_service.build_summary_matrix(
        db, product_name=product_name, date_from=date_from, date_to=date_to,
        include_in_progress=include_in_progress,
    )
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "QC汇总表"
    headers = ["产品名称", "批号", "生产日期", "状态", "判定"] + [c["name"] for c in data["columns"]]
    ws.append(headers)
    status_label = {"completed": "已完成", "pending_review": "待复核", "in_progress": "填报中"}
    for r in data["rows"]:
        row = [
            r["product_name"], r["batch_number"], r["production_date"] or "",
            status_label.get(r["status"], r["status"]), "合格" if r["all_pass"] else "不合格",
        ]
        for c in data["columns"]:
            cell = r["cells"].get(c["name"])
            row.append(f'{cell["value"]}{cell["unit"]}' if cell else "")
        ws.append(row)
    buf = _io.BytesIO()
    wb.save(buf)
    encoded = quote("QC汇总表.xlsx")
    return StreamingResponse(
        BytesIO(buf.getvalue()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="matrix.xlsx"; filename*=UTF-8\'\'{encoded}'},
    )


@router.get("/summary/trend", summary="项目跨批次趋势（数值序列+限度参考）")
async def summary_trend(
    item_name: str = Query(..., description="检验项目名称"),
    product_name: str | None = Query(default=None, description="产品名称"),
    limit: int = Query(default=50, ge=2, le=200),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    data = await test_task_service.build_item_trend(
        db, item_name, product_name=product_name, limit=limit,
    )
    return success_response(data=data)


@router.get("/summary/products", summary="已检验产品列表")
async def list_summary_products(
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    names = await get_product_names(db)
    return success_response(data=names)
