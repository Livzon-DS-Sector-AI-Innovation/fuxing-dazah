"""物料赋码 API：批量赋码、台账查询、进出库、标签、物料字典、库存概览。"""

import uuid
from io import BytesIO
from urllib.parse import quote

from fastapi import Body, Depends, File, HTTPException, Query, Response, UploadFile
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
    create_container_movement,
    create_inspection_plan,
    create_lab_item,
    create_material,
    create_material_standard,
    create_material_standard_item,
    create_micro_record,
    create_retained_sample,
    create_supplier,
    delete_lab_item,
    delete_material,
    delete_micro_record,
    delete_retained_sample,
    delete_supplier,
    get_material_by_code,
    get_material_container_by_no,
    get_material_standard,
    get_material_standard_by_key,
    get_micro_record,
    get_retained_sample,
    get_retained_sample_with_names,
    get_stocktake_sheet,
    get_supplier_by_code,
    list_container_movements,
    list_containers_by_nos,
    list_containers_by_request,
    list_in_stock_containers,
    list_inspection_plans,
    list_lab_items,
    list_material_containers,
    list_material_movements,
    list_material_requests,
    list_material_standard_items,
    list_materials,
    list_micro_records,
    list_plans_board,
    list_retained_samples,
    list_retained_samples_with_names,
    list_slow_moving_containers,
    list_stocktake_items,
    list_stocktake_sheets,
    list_suppliers,
    material_consumption_trend,
    material_monthly_report,
    material_stock_summary,
    material_today_stats,
    update_container_location,
    update_inspection_plan_status,
    update_lab_item,
    update_material,
    update_micro_record,
    update_retained_sample,
    update_supplier,
)
from app.modules.quality.schemas import (
    ContainerBatchMoveRequest,
    ContainerLabelRequest,
    ContainerLocationUpdate,
    ContainerMovementOut,
    ContainerMoveRequest,
    ContainerStatusUpdate,
    InspectionPlanCreate,
    InspectionPlanOut,
    InspectionPlanUpdate,
    LabItemCreate,
    LabItemOut,
    LabItemUpdate,
    MaterialContainerGenerateRequest,
    MaterialContainerListItem,
    MaterialContainerOut,
    MaterialCreate,
    MaterialOut,
    MaterialRequestCreate,
    MaterialRequestOut,
    MaterialRequestRelease,
    MaterialRequestSample,
    MaterialStandardCreate,
    MaterialStandardItemCreate,
    MaterialStandardItemOut,
    MaterialStandardOut,
    MaterialSummaryItem,
    MaterialUpdate,
    MicroRecordCreate,
    MicroRecordOut,
    MicroRecordUpdate,
    MonthlyReportItem,
    PlanAssignmentsSave,
    RetainedSampleCreate,
    RetainedSampleDestroy,
    RetainedSampleOut,
    RetainedSampleUpdate,
    StocktakeCreate,
    StocktakeItemOut,
    StocktakeScanRequest,
    StocktakeSheetOut,
    SupplierCreate,
    SupplierOut,
    SupplierUpdate,
)
from app.modules.quality.service import material_container_service
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission


@router.post("/material/containers/generate", summary="批量赋码：生成连续容器号（MC-物料代码-日期-流水）")
async def generate_containers_endpoint(
    payload: MaterialContainerGenerateRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    containers = await material_container_service.generate_containers(db, payload, issued_by=user.id)
    return success_response(
        data=[MaterialContainerListItem.model_validate(c).model_dump(mode="json") for c in containers],
        message=f"已赋码 {len(containers)} 个容器（{containers[0].container_no} 起）" if containers else "已赋码 0 个容器",
    )


@router.get("/material/containers", summary="物料容器台账列表")
async def list_containers_endpoint(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None, description="状态筛选"),
    batch_no: str | None = Query(default=None, description="进厂批号模糊搜索"),
    material_code: str | None = Query(default=None, description="物料代码模糊搜索"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> JSONResponse:
    rows, total = await list_material_containers(
        db, page=page, page_size=page_size, status=status, batch_no=batch_no, material_code=material_code
    )
    items = [MaterialContainerListItem.model_validate(r).model_dump(mode="json") for r in rows]
    return paginated_response(data=items, total=total, page=page, page_size=page_size)


@router.post("/material/containers/batch-move", summary="批量进出库（逐容器独立校验，返回逐条结果）")
async def batch_move_endpoint(
    payload: ContainerBatchMoveRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    results = await material_container_service.batch_move(db, payload, operator=user.id)
    ok_count = sum(1 for r in results if r.get("ok"))
    fail_count = len(results) - ok_count
    return success_response(
        data={"results": results, "updated": ok_count, "failed": fail_count},
        message=f"已处理 {ok_count} 个容器" + (f"，失败 {fail_count} 个（详见结果）" if fail_count else ""),
    )


@router.get("/material/containers/{container_no}", summary="按容器号查询（扫码入口共用）")
async def get_container_endpoint(
    container_no: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> JSONResponse:
    container = await get_material_container_by_no(db, container_no)
    if container is None:
        raise HTTPException(status_code=404, detail=f"容器 {container_no} 不存在")
    movements = await list_container_movements(db, container.id)
    return success_response(data={
        "container": MaterialContainerOut.model_validate(container).model_dump(mode="json"),
        "movements": [ContainerMovementOut.model_validate(m).model_dump(mode="json") for m in movements],
    })


@router.post("/material/containers/{container_no}/move", summary="进出库：in 入库登记 / out 领料出库")
async def move_container_endpoint(
    container_no: str,
    payload: ContainerMoveRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    container = await material_container_service.move_container(db, container_no, payload, operator=user.id)
    message = {
        "in_warehouse": "已入库登记",
        "returned": "已退库",
    }.get(container.status, "已领料出库")
    return success_response(
        data=MaterialContainerOut.model_validate(container).model_dump(mode="json"),
        message=message,
    )


@router.put("/material/containers/{container_no}/status", summary="人工状态流转（阶段1：手动合格/作废）")
async def update_container_status_endpoint(
    container_no: str,
    payload: ContainerStatusUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    container = await material_container_service.update_status(
        db, container_no, payload.status, operator=user.id, remark=payload.remark,
    )
    return success_response(
        data=MaterialContainerOut.model_validate(container).model_dump(mode="json"),
        message=f"状态已变更为 {payload.status}",
    )


@router.post("/material/containers/label", summary="批量标签 PDF（A4 不干胶 2×4 排版）")
async def container_label_endpoint(
    payload: ContainerLabelRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:material:read")),
) -> StreamingResponse:
    pdf_bytes = await material_container_service.build_label_pdf(db, payload.container_nos)
    # 补印留痕：reprint=True 时为每个容器记一条补印流水（防重复贴标审计）
    if payload.reprint:
        containers = await list_containers_by_nos(db, payload.container_nos)
        for c in containers:
            await create_container_movement(
                db,
                container_id=c.id,
                container_no=c.container_no,
                op_type="reprint",
                from_status=c.status,
                to_status=c.status,
                operator=user.id,
                remark="标签补印",
            )
    encoded = quote(f"物料标签-{len(payload.container_nos)}张.pdf")
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="labels.pdf"; filename*=UTF-8\'\'{encoded}'},
    )


# ─── 物料字典 ───


@router.get("/material/dict", summary="物料字典（搜索：代码/名称模糊）")
async def list_material_dict_endpoint(
    q: str | None = Query(default=None, description="代码/名称模糊搜索"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> JSONResponse:
    rows, total = await list_materials(db, q=q, page=page, page_size=page_size)
    items = [MaterialOut.model_validate(r).model_dump(mode="json") for r in rows]
    return paginated_response(data=items, total=total, page=page, page_size=page_size)


@router.post("/material/dict", summary="新增物料（字典）", status_code=201)
async def create_material_endpoint(
    payload: MaterialCreate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    code = payload.code.strip()
    if not code or "/" in code or " " in code:
        raise HTTPException(status_code=400, detail="物料代码不能为空且不能含空格/斜杠")
    if await get_material_by_code(db, code):
        raise HTTPException(status_code=409, detail=f"物料代码 {code} 已存在")
    material = await create_material(db, {
        "code": code,
        "name": payload.name,
        "category": payload.category,
        "vendor_name": payload.vendor_name,
        "vendor_code": payload.vendor_code,
        "pack_spec": payload.pack_spec,
        "min_stock": payload.min_stock,
        "valid_months": payload.valid_months,
        "remark": payload.remark,
    })
    return success_response(
        data=MaterialOut.model_validate(material).model_dump(mode="json"),
        message="物料已新增", status_code=201,
    )


@router.put("/material/dict/{dict_id}", summary="更新物料字典")
async def update_material_endpoint(
    dict_id: uuid.UUID,
    payload: MaterialUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    material = await update_material(db, dict_id, payload.model_dump(exclude_none=True))
    if material is None:
        raise HTTPException(status_code=404, detail="物料不存在")
    return success_response(
        data=MaterialOut.model_validate(material).model_dump(mode="json"),
        message="物料已更新",
    )


@router.delete("/material/dict/{dict_id}", summary="删除物料（软删除）")
async def delete_material_endpoint(
    dict_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    if not await delete_material(db, dict_id):
        raise HTTPException(status_code=404, detail="物料不存在")
    return success_response(message="已删除")


# ─── 库存概览与台账 ───


@router.get("/material/trend", summary="物料领用趋势（近 N 个月出入库笔数，北京时区）")
async def material_trend_endpoint(
    material_code: str = Query(..., description="物料代码"),
    months: int = Query(default=6, ge=1, le=24),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> JSONResponse:
    trend = await material_consumption_trend(db, material_code, months)
    out_values = [t["out"] for t in trend]
    active_months = [t for t in trend if t["out"] > 0]
    monthly_avg = round(sum(out_values) / len(active_months), 1) if active_months else 0
    return success_response(data={
        "trend": trend,
        "monthly_avg_out": monthly_avg,
        "suggested_min_stock": int(monthly_avg * 2) if monthly_avg else None,
    })


@router.get("/material/today-stats", summary="今日出入库笔数（看板卡片）")
async def material_today_stats_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> JSONResponse:
    stats = await material_today_stats(db)
    return success_response(data=stats)


@router.get("/material/summary", summary="按物料聚合的库存概览（含临效期/过期/低于安全库存）")
async def material_summary_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> JSONResponse:
    rows = await material_stock_summary(db)
    items = [MaterialSummaryItem.model_validate(r).model_dump(mode="json") for r in rows]
    return success_response(data=items)


@router.get("/material/movements", summary="出入库流水台账（联容器物料信息）")
async def list_movements_endpoint(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    material_q: str | None = Query(default=None, description="物料代码/名称模糊"),
    op_type: str | None = Query(default=None, description="in/out/status"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> JSONResponse:
    rows, total = await list_material_movements(
        db, page=page, page_size=page_size, material_q=material_q, op_type=op_type
    )
    items = []
    for movement, material_code, material_name in rows:
        items.append({
            "id": movement.id,
            "container_no": movement.container_no,
            "material_code": material_code,
            "material_name": material_name,
            "op_type": movement.op_type,
            "from_status": movement.from_status,
            "to_status": movement.to_status,
            "related_doc": movement.related_doc,
            "remark": movement.remark,
            "op_at": movement.op_at.isoformat() if movement.op_at else None,
        })
    return paginated_response(data=items, total=total, page=page, page_size=page_size)


@router.get("/material/movements/export", summary="出入库台账导出 Excel")
async def export_movements_endpoint(
    material_q: str | None = Query(default=None),
    op_type: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> StreamingResponse:
    import io as _io

    import openpyxl

    from app.modules.quality import lc_template_parser

    rows, _total = await list_material_movements(
        db, page=1, page_size=5000, material_q=material_q, op_type=op_type
    )
    wb = openpyxl.Workbook()
    ws = lc_template_parser.active_sheet(wb)
    ws.title = "出入库台账"
    ws.append(["操作时间", "容器号", "物料代码", "物料名称", "操作", "原状态", "新状态", "关联单据", "备注"])
    for movement, material_code, material_name in rows:
        ws.append([
            movement.op_at.strftime("%Y-%m-%d %H:%M") if movement.op_at else "",
            movement.container_no,
            material_code,
            material_name,
            movement.op_type,
            movement.from_status,
            movement.to_status,
            movement.related_doc or "",
            movement.remark or "",
        ])
    buf = _io.BytesIO()
    wb.save(buf)
    encoded = quote("物料出入库台账.xlsx")
    return StreamingResponse(
        BytesIO(buf.getvalue()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="movements.xlsx"; filename*=UTF-8\'\'{encoded}'},
    )


# ─── 采购建议 ───


@router.get("/material/purchase-suggestions", summary="采购建议（可用库存低于安全库存阈值的物料）")
async def purchase_suggestions_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> JSONResponse:
    suggestions = await material_container_service.purchase_suggestions(db)
    return success_response(data=suggestions)


@router.get("/material/purchase-suggestions/export", summary="采购建议导出 Excel")
async def purchase_suggestions_export_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> StreamingResponse:
    import io as _io

    import openpyxl

    from app.modules.quality import lc_template_parser

    suggestions = await material_container_service.purchase_suggestions(db)
    wb = openpyxl.Workbook()
    ws = lc_template_parser.active_sheet(wb)
    ws.title = "采购建议"
    ws.append(["物料代码", "物料名称", "供应商", "包装规格", "可用库存", "安全库存阈值", "建议采购量"])
    for s in suggestions:
        ws.append([
            s["material_code"], s["material_name"], s["vendor_name"] or "",
            s["pack_spec"] or "", s["available"], s["min_stock"], s["gap"],
        ])
    buf = _io.BytesIO()
    wb.save(buf)
    encoded = quote("采购建议清单.xlsx")
    return StreamingResponse(
        BytesIO(buf.getvalue()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="purchase.xlsx"; filename*=UTF-8\'\'{encoded}'},
    )


# ─── 供应商主数据 ───


@router.get("/material/suppliers", summary="供应商主数据（搜索：代码/名称模糊）")
async def list_suppliers_endpoint(
    q: str | None = Query(default=None, description="代码/名称模糊搜索"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> JSONResponse:
    rows = await list_suppliers(db, q=q)
    items = [SupplierOut.model_validate(r).model_dump(mode="json") for r in rows]
    return success_response(data=items)


@router.post("/material/suppliers", summary="新增供应商", status_code=201)
async def create_supplier_endpoint(
    payload: SupplierCreate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    code = payload.code.strip()
    if not code or "/" in code or " " in code:
        raise HTTPException(status_code=400, detail="供应商代码不能为空且不能含空格/斜杠")
    if await get_supplier_by_code(db, code):
        raise HTTPException(status_code=409, detail=f"供应商代码 {code} 已存在")
    supplier = await create_supplier(db, {
        "code": code,
        "name": payload.name,
        "contact": payload.contact,
        "phone": payload.phone,
        "qual_expiry_date": payload.qual_expiry_date,
        "remark": payload.remark,
    })
    return success_response(
        data=SupplierOut.model_validate(supplier).model_dump(mode="json"),
        message="供应商已新增", status_code=201,
    )


@router.put("/material/suppliers/{supplier_id}", summary="更新供应商")
async def update_supplier_endpoint(
    supplier_id: uuid.UUID,
    payload: SupplierUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    supplier = await update_supplier(db, supplier_id, payload.model_dump(exclude_none=True))
    if supplier is None:
        raise HTTPException(status_code=404, detail="供应商不存在")
    return success_response(
        data=SupplierOut.model_validate(supplier).model_dump(mode="json"),
        message="供应商已更新",
    )


@router.delete("/material/suppliers/{supplier_id}", summary="删除供应商（软删除）")
async def delete_supplier_endpoint(
    supplier_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    if not await delete_supplier(db, supplier_id):
        raise HTTPException(status_code=404, detail="供应商不存在")
    return success_response(message="已删除")


# ─── 库存盘点 ───


@router.post("/material/stocktakes", summary="创建盘点单（范围可选物料，空=全部在库）", status_code=201)
async def create_stocktake_endpoint(
    payload: StocktakeCreate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    sheet = await material_container_service.create_stocktake(
        db, payload.scope_material_code, payload.remark
    )
    return success_response(
        data=StocktakeSheetOut.model_validate(sheet).model_dump(mode="json"),
        message=f"盘点单 {sheet.sheet_no} 已创建（系统在库 {sheet.expected_count} 个容器）",
        status_code=201,
    )


@router.get("/material/stocktakes", summary="盘点单列表")
async def list_stocktakes_endpoint(
    status: str | None = Query(default=None, description="in_progress/completed/void"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> JSONResponse:
    sheets = await list_stocktake_sheets(db, status=status)
    items = [StocktakeSheetOut.model_validate(s).model_dump(mode="json") for s in sheets]
    return success_response(data=items)


@router.post("/material/stocktakes/{sheet_id}/scan", summary="盘点扫码（按容器号去重分类）")
async def scan_stocktake_endpoint(
    sheet_id: uuid.UUID,
    payload: StocktakeScanRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    item = await material_container_service.scan_stocktake(
        db, sheet_id, payload.container_no.strip(), operator=user.id
    )
    return success_response(
        data=StocktakeItemOut.model_validate(item).model_dump(mode="json"),
        message={"matched": "已记录（在库匹配）", "out_of_scope": "已记录（系统有但不在库，计入盘盈）", "not_found": "已记录（系统不存在，标记异常）"}.get(item.result, "已记录"),
    )


@router.post("/material/stocktakes/{sheet_id}/finish", summary="结束盘点（计算盘亏/盘盈差异）")
async def finish_stocktake_endpoint(
    sheet_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    sheet = await material_container_service.finish_stocktake(db, sheet_id)
    return success_response(
        data=StocktakeSheetOut.model_validate(sheet).model_dump(mode="json"),
        message=f"盘点完成：系统在库 {sheet.expected_count}，实扫 {sheet.scanned_count}，盘亏 {sheet.missing_count}，盘盈 {sheet.extra_count}",
    )


@router.get("/material/stocktakes/{sheet_id}", summary="盘点详情（含扫码明细）")
async def stocktake_detail_endpoint(
    sheet_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> JSONResponse:
    sheet = await get_stocktake_sheet(db, sheet_id)
    if sheet is None:
        raise HTTPException(status_code=404, detail="盘点单不存在")
    items = await list_stocktake_items(db, sheet_id)
    # 盘亏明细 = 在库但未扫到
    in_stock = {c.container_no: c for c in await list_in_stock_containers(db, sheet.scope_material_code)}
    scanned = {i.container_no for i in items}
    missing = [
        {"container_no": no, "material_name": c.material_name, "material_code": c.material_code, "status": c.status}
        for no, c in in_stock.items() if no not in scanned
    ]
    return success_response(data={
        "sheet": StocktakeSheetOut.model_validate(sheet).model_dump(mode="json"),
        "items": [StocktakeItemOut.model_validate(i).model_dump(mode="json") for i in items],
        "missing": missing,
    })


@router.get("/material/stocktakes/{sheet_id}/export", summary="盘点差异清单导出 Excel")
async def stocktake_export_endpoint(
    sheet_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> StreamingResponse:
    import io as _io

    import openpyxl

    from app.modules.quality import lc_template_parser

    sheet = await get_stocktake_sheet(db, sheet_id)
    if sheet is None:
        raise HTTPException(status_code=404, detail="盘点单不存在")
    items = await list_stocktake_items(db, sheet_id)
    in_stock = {c.container_no: c for c in await list_in_stock_containers(db, sheet.scope_material_code)}
    scanned = {i.container_no for i in items}
    wb = openpyxl.Workbook()
    ws = lc_template_parser.active_sheet(wb)
    ws.title = "盘点差异"
    ws.append(["盘点单号", sheet.sheet_no, "状态", sheet.status])
    ws.append(["系统在库", sheet.expected_count, "实扫", sheet.scanned_count, "盘亏", sheet.missing_count, "盘盈", sheet.extra_count, "异常", sheet.anomaly_count])
    ws.append([])
    ws.append(["容器号", "物料名称", "物料代码", "分类", "扫描时状态"])
    for i in items:
        ws.append([i.container_no, i.material_name or "-", i.material_code or "-",
                   {"matched": "在库匹配", "out_of_scope": "盘盈(系统不在库)", "not_found": "异常(系统不存在)"}.get(i.result, i.result),
                   i.status_snapshot or "-"])
    ws.append([])
    ws.append(["盘亏清单（系统在库未扫到）"])
    for no, c in in_stock.items():
        if no not in scanned:
            ws.append([no, c.material_name, c.material_code, "盘亏", c.status])
    buf = _io.BytesIO()
    wb.save(buf)
    encoded = quote(f"盘点差异-{sheet.sheet_no}.xlsx")
    return StreamingResponse(
        BytesIO(buf.getvalue()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="stocktake.xlsx"; filename*=UTF-8\'\'{encoded}'},
    )


# ─── 月度汇总报表 ───


@router.get("/material/monthly-report", summary="月度汇总报表（按物料的当月出入库笔数与当前可用）")
async def monthly_report_endpoint(
    month: str = Query(..., description="YYYY-MM"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> JSONResponse:
    rows = await material_monthly_report(db, month)
    items = [MonthlyReportItem.model_validate(r).model_dump(mode="json") for r in rows]
    return success_response(data=items)


@router.get("/material/monthly-report/export", summary="月度汇总报表导出 Excel")
async def monthly_report_export_endpoint(
    month: str = Query(..., description="YYYY-MM"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> StreamingResponse:
    import io as _io

    import openpyxl

    from app.modules.quality import lc_template_parser

    rows = await material_monthly_report(db, month)
    wb = openpyxl.Workbook()
    ws = lc_template_parser.active_sheet(wb)
    ws.title = f"{month} 物料汇总"
    ws.append(["物料代码", "物料名称", "入库", "出库", "退库", "状态流转", "当前可用"])
    for r in rows:
        ws.append([r["material_code"], r["material_name"], r["in_count"], r["out_count"],
                   r["return_count"], r["status_count"], r["available"]])
    buf = _io.BytesIO()
    wb.save(buf)
    encoded = quote(f"物料月度汇总-{month}.xlsx")
    return StreamingResponse(
        BytesIO(buf.getvalue()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="monthly.xlsx"; filename*=UTF-8\'\'{encoded}'},
    )


# ─── Excel 导入 / 库位 / 呆滞 ───


@router.get("/material/import-template", summary="导入模板下载（dict=物料字典 / containers=容器）")
async def import_template_endpoint(
    kind: str = Query(..., description="dict / containers"),
    _user: User = Depends(require_permission("quality:material:manage")),
) -> StreamingResponse:
    if kind not in ("dict", "containers"):
        raise HTTPException(status_code=400, detail="kind 仅支持 dict / containers")
    xlsx = material_container_service.build_import_template(kind)
    encoded = quote(f"导入模板-{kind}.xlsx")
    return StreamingResponse(
        BytesIO(xlsx),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="template.xlsx"; filename*=UTF-8\'\'{encoded}'},
    )


@router.post("/material/dict/import", summary="批量导入物料字典（Excel，逐行校验跳过重复）")
async def import_dict_endpoint(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    result = await material_container_service.import_dict_rows(db, content)
    return success_response(
        data=result,
        message=f"已导入 {len(result['created'])} 个物料" + (f"，跳过 {len(result['skipped'])} 条" if result["skipped"] else ""),
    )


@router.post("/material/containers/import", summary="批量导入存量容器（Excel，逐行校验跳过重复）")
async def import_containers_endpoint(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    result = await material_container_service.import_container_rows(db, content)
    return success_response(
        data=result,
        message=f"已导入 {len(result['created'])} 个容器" + (f"，跳过 {len(result['skipped'])} 条" if result["skipped"] else ""),
    )


@router.put("/material/containers/{container_no}/location", summary="维护容器库位")
async def update_location_endpoint(
    container_no: str,
    payload: ContainerLocationUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    container = await get_material_container_by_no(db, container_no)
    if container is None:
        raise HTTPException(status_code=404, detail=f"容器 {container_no} 不存在")
    updated = await update_container_location(db, container.id, payload.location.strip())
    return success_response(
        data=MaterialContainerOut.model_validate(updated).model_dump(mode="json"),
        message="库位已更新",
    )


@router.get("/material/slow-moving", summary="呆滞库存（在库且入库超 N 天，账龄=今天-入库日期）")
async def slow_moving_endpoint(
    min_age: int = Query(default=30, ge=1, description="最小账龄天数"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> JSONResponse:
    rows = await list_slow_moving_containers(db, min_age)
    return success_response(data={"items": rows, "total": len(rows)})


# ─── 物料请验 / 物料标准 / 放行 ───


@router.post("/material/requests", summary="创建物料请验单（MR+YYMMDD+序号，字典带出物料快照）", status_code=201)
async def create_material_request_endpoint(
    payload: MaterialRequestCreate = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    req = await material_container_service.create_request(db, payload, operator=user.id)
    return success_response(
        data=MaterialRequestOut.model_validate(req).model_dump(mode="json"),
        message=f"请验单 {req.request_no} 已创建", status_code=201,
    )


@router.get("/material/requests", summary="物料请验单列表")
async def list_material_requests_endpoint(
    status: str | None = Query(default=None),
    batch_no: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> JSONResponse:
    rows = await list_material_requests(db, status=status, batch_no=batch_no)
    items = []
    for r in rows:
        item = MaterialRequestOut.model_validate(r).model_dump(mode="json")
        item["linked_containers"] = len(await list_containers_by_request(db, r.id))
        items.append(item)
    return success_response(data=items)


@router.post("/material/requests/{request_id}/sample", summary="取样登记")
async def sample_material_request_endpoint(
    request_id: uuid.UUID,
    payload: MaterialRequestSample = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    req = await material_container_service.sample_request(db, request_id, payload, operator=user.id)
    return success_response(
        data=MaterialRequestOut.model_validate(req).model_dump(mode="json"),
        message="取样已登记",
    )


@router.post("/material/requests/{request_id}/task", summary="按物料标准快照建物料检验任务（复用检验填报链路）", status_code=201)
async def create_material_task_endpoint(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:task:create")),
) -> JSONResponse:
    task = await material_container_service.create_material_task(db, request_id)
    return success_response(
        data={"task_id": str(task.id), "batch_number": task.batch_number, "product_name": task.product_name},
        message="物料检验任务已创建，请到检验填报页完成填报与复核", status_code=201,
    )


@router.post("/material/requests/{request_id}/release", summary="放行结论（release/reject/concede，联动容器状态）")
async def release_material_request_endpoint(
    request_id: uuid.UUID,
    payload: MaterialRequestRelease = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:material:release")),
) -> JSONResponse:
    linked = await list_containers_by_request(db, request_id)
    req = await material_container_service.release_request(db, request_id, payload, operator=user.id)
    verdict_label = {"release": "已放行", "reject": "已拒收", "concede": "让步接收"}[payload.verdict]
    suffix = f"，该批 {len(linked)} 个容器已同步更新状态" if linked else "（无挂单容器）"
    return success_response(
        data=MaterialRequestOut.model_validate(req).model_dump(mode="json"),
        message=f"请验单 {req.request_no} {verdict_label}{suffix}",
    )


# ─── 物料标准库 ───


@router.post("/material/standards", summary="新建物料质量标准（物料+供应商，同键已存在则 409）", status_code=201)
async def create_material_standard_endpoint(
    payload: MaterialStandardCreate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:standard:manage")),
) -> JSONResponse:
    code = payload.material_code.strip()
    from app.modules.quality.repository import get_material_by_code

    material = await get_material_by_code(db, code)
    if material is None:
        raise HTTPException(status_code=404, detail=f"物料代码 {code} 不在字典中")
    if await get_material_standard_by_key(db, code, payload.vendor_code):
        raise HTTPException(status_code=409, detail="该物料+供应商的标准已存在")
    std = await create_material_standard(db, {
        "material_code": code,
        "material_name": material.name,
        "vendor_code": payload.vendor_code,
        "version": payload.version,
        "remark": payload.remark,
    })
    return success_response(
        data=MaterialStandardOut.model_validate(std).model_dump(mode="json"),
        message="物料标准已创建", status_code=201,
    )


@router.post("/material/standards/{standard_id}/items", summary="新增物料标准检验项目行", status_code=201)
async def create_material_standard_item_endpoint(
    standard_id: uuid.UUID,
    payload: MaterialStandardItemCreate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:standard:manage")),
) -> JSONResponse:
    std = await get_material_standard(db, standard_id)
    if std is None:
        raise HTTPException(status_code=404, detail="物料标准不存在")
    item = await create_material_standard_item(db, {
        "standard_id": standard_id,
        "seq": payload.seq,
        "category": payload.category,
        "item_name": payload.item_name,
        "sop_no": payload.sop_no,
        "standard_text": payload.standard_text,
        "operator": payload.operator,
        "limit_min": payload.limit_min,
        "limit_max": payload.limit_max,
        "method_source": payload.method_source,
        "remark": payload.remark,
    })
    return success_response(
        data=MaterialStandardItemOut.model_validate(item).model_dump(mode="json"),
        message="项目行已添加", status_code=201,
    )


@router.get("/material/standards/{standard_id}/items", summary="物料标准检验项目行列表")
async def list_material_standard_items_endpoint(
    standard_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> JSONResponse:
    items = await list_material_standard_items(db, standard_id)
    return success_response(
        data=[MaterialStandardItemOut.model_validate(i).model_dump(mode="json") for i in items]
    )


# ─── 试剂/仪器台账 ───


@router.get("/lab-items", summary="试剂/对照品/滴定液/仪器校验台账列表")
async def list_lab_items_endpoint(
    item_type: str | None = Query(default=None, description="reagent/reference_standard/titrant/instrument"),
    q: str | None = Query(default=None, description="名称模糊"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> JSONResponse:
    rows = await list_lab_items(db, item_type=item_type, q=q)
    items = [LabItemOut.model_validate(r).model_dump(mode="json") for r in rows]
    return success_response(data=items)


@router.post("/lab-items", summary="新增台账条目", status_code=201)
async def create_lab_item_endpoint(
    payload: LabItemCreate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    item = await create_lab_item(db, payload.model_dump())
    return success_response(
        data=LabItemOut.model_validate(item).model_dump(mode="json"),
        message="已新增", status_code=201,
    )


@router.put("/lab-items/{item_id}", summary="更新台账条目")
async def update_lab_item_endpoint(
    item_id: uuid.UUID,
    payload: LabItemUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    item = await update_lab_item(db, item_id, payload.model_dump(exclude_none=True))
    if item is None:
        raise HTTPException(status_code=404, detail="条目不存在")
    return success_response(
        data=LabItemOut.model_validate(item).model_dump(mode="json"),
        message="已更新",
    )


@router.delete("/lab-items/{item_id}", summary="删除台账条目（软删除）")
async def delete_lab_item_endpoint(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    if not await delete_lab_item(db, item_id):
        raise HTTPException(status_code=404, detail="条目不存在")
    return success_response(message="已删除")


# ─── 请检计划 ───


@router.get("/plans/board", summary="请检计划排班看板（今天及以后计划 + 待检 SOP + 排班）")
async def plans_board_endpoint(
    date_from: str | None = Query(default=None, description="YYYY-MM-DD，默认今天"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> JSONResponse:
    from app.core.time import today as _today

    items = await list_plans_board(db, date_from or _today().isoformat())
    return success_response(data=items)


@router.put("/inspection-plans/{plan_id}/assignments", summary="请检计划排班（SOP→人员；已建任务自动同步任务分工）")
async def save_plan_assignments_endpoint(
    plan_id: uuid.UUID,
    payload: PlanAssignmentsSave = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:task:create")),
) -> JSONResponse:
    from app.modules.quality.repository import (
        get_inspection_plan,
        get_test_task_by_batch_number,
        list_test_results,
        replace_task_assignments,
    )

    plan = await get_inspection_plan(db, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="请检计划不存在")
    rows = [
        {"sop_no": a.sop_no.strip(), "assignee_id": str(a.assignee_id)}
        for a in payload.assignments
    ]
    plan.assignments = rows
    await db.flush()
    # 已建任务：同步任务分工
    task = await get_test_task_by_batch_number(db, plan.batch_no) if plan.batch_no else None
    if task is not None:
        valid = {(r.sop_no or "").strip() for r in await list_test_results(db, task.id) if (r.sop_no or "").strip()}
        await replace_task_assignments(db, task.id, [
            {"task_id": task.id, "sop_no": a["sop_no"], "assignee_id": uuid.UUID(a["assignee_id"]),
             "assigned_by": user.id, "created_by": user.id}
            for a in rows if a["sop_no"] in valid
        ])
    items = await list_plans_board(db, "0000-01-01")
    item = next((x for x in items if x["plan_id"] == plan.id), None)
    return success_response(data=item, message=f"排班已保存（{len(rows)} 个 SOP）")


@router.get("/inspection-plans", summary="请检计划列表（可按日期/车间筛选）")
async def list_inspection_plans_endpoint(
    date: str | None = Query(default=None, description="计划日期 YYYY-MM-DD"),
    department: str | None = Query(default=None, description="车间模糊"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> JSONResponse:
    rows = await list_inspection_plans(db, date_str=date, department=department)
    items = [InspectionPlanOut.model_validate(r).model_dump(mode="json") for r in rows]
    return success_response(data=items)


@router.post("/inspection-plans", summary="手动新增请检计划", status_code=201)
async def create_inspection_plan_endpoint(
    payload: InspectionPlanCreate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    plan = await create_inspection_plan(db, payload.model_dump())
    return success_response(
        data=InspectionPlanOut.model_validate(plan).model_dump(mode="json"),
        message="计划已新增", status_code=201,
    )


@router.put("/inspection-plans/{plan_id}/status", summary="请检计划状态（待请检/已请检）")
async def update_inspection_plan_endpoint(
    plan_id: uuid.UUID,
    payload: InspectionPlanUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    plan = await update_inspection_plan_status(db, plan_id, payload.status)
    if plan is None:
        raise HTTPException(status_code=404, detail="计划不存在")
    return success_response(
        data=InspectionPlanOut.model_validate(plan).model_dump(mode="json"),
        message="状态已更新",
    )


@router.post("/inspection-plans/import", summary="批量导入请检计划（Excel：车间/品种/批号/计划请检时间/备注）")
async def import_inspection_plans_endpoint(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    import io as _io

    import openpyxl

    from app.modules.quality import lc_template_parser

    wb = openpyxl.load_workbook(_io.BytesIO(content))
    ws = lc_template_parser.active_sheet(wb)
    created: list[str] = []
    skipped: list[str] = []
    header = next(ws.iter_rows(values_only=True), None)
    columns = [str(h).strip() if h else "" for h in (header or [])]
    for raw in ws.iter_rows(min_row=2, values_only=True):
        if not raw or all(v is None or str(v).strip() == "" for v in raw):
            continue
        row = {col: (str(raw[i]).strip() if i < len(raw) and raw[i] is not None else "") for i, col in enumerate(columns) if col}
        dept = row.get("车间") or row.get("department") or ""
        product = row.get("品种") or row.get("product_name") or ""
        plan_time = row.get("计划请检时间") or row.get("plan_time") or ""
        if not dept or not product or not plan_time:
            skipped.append(f"{product or '(缺品种)'}:字段缺失")
            continue
        async with db.begin_nested():
            await create_inspection_plan(db, {
                "department": dept,
                "product_name": product,
                "batch_no": row.get("批号") or row.get("batch_no") or None,
                "plan_time": plan_time,
                "remark": row.get("备注") or row.get("remark") or None,
            })
        created.append(f"{dept}-{product}")
    return success_response(
        data={"created": created, "skipped": skipped},
        message=f"已导入 {len(created)} 条" + (f"，跳过 {len(skipped)} 条" if skipped else ""),
    )


@router.get("/inspection-plans/template", summary="请检计划导入模板下载")
async def inspection_plan_template_endpoint(
    _user: User = Depends(require_permission("quality:material:manage")),
) -> StreamingResponse:
    import io as _io

    import openpyxl

    from app.modules.quality import lc_template_parser

    wb = openpyxl.Workbook()
    ws = lc_template_parser.active_sheet(wb)
    ws.append(["车间", "品种", "批号", "计划请检时间", "备注"])
    ws.append(["发酵一车间", "盐酸万古霉素", "HAF2610001", "2026-10-20 09:00", "示例"])
    buf = _io.BytesIO()
    wb.save(buf)
    encoded = quote("请检计划导入模板.xlsx")
    return StreamingResponse(
        BytesIO(buf.getvalue()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="plan-template.xlsx"; filename*=UTF-8\'\'{encoded}'},
    )


# ─── 微生物限度/菌落计数登记 ───


def _micro_judge(count: int | None, alert: float | None, action: float | None) -> str | None:
    """判定：超标准限 action / 超警戒线 alert / 其余 pass；无计数不判定。"""
    if count is None:
        return None
    if action is not None and count > action:
        return "action"
    if alert is not None and count > alert:
        return "alert"
    return "pass"


@router.get("/micro-records", summary="微生物限度/菌落计数登记列表")
async def list_micro_records_endpoint(
    batch_no: str | None = Query(default=None, description="批号模糊"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> JSONResponse:
    rows = await list_micro_records(db, batch_no=batch_no)
    items = [MicroRecordOut.model_validate(r).model_dump(mode="json") for r in rows]
    return success_response(data=items)


@router.post("/micro-records", summary="新增微生物登记（按人工确认数判定，AI 预计数可选）", status_code=201)
async def create_micro_record_endpoint(
    payload: MicroRecordCreate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    rec = await create_micro_record(db, {
        **payload.model_dump(),
        "judge": _micro_judge(payload.colony_count, payload.alert_limit, payload.action_limit),
    })
    return success_response(
        data=MicroRecordOut.model_validate(rec).model_dump(mode="json"),
        message="登记已保存", status_code=201,
    )


@router.put("/micro-records/{record_id}", summary="更新微生物登记（重新判定）")
async def update_micro_record_endpoint(
    record_id: uuid.UUID,
    payload: MicroRecordUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    rec = await get_micro_record(db, record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    data = payload.model_dump(exclude_none=True)
    data["judge"] = _micro_judge(
        data.get("colony_count", rec.colony_count),
        data.get("alert_limit", rec.alert_limit),
        data.get("action_limit", rec.action_limit),
    )
    updated = await update_micro_record(db, record_id, data)
    return success_response(
        data=MicroRecordOut.model_validate(updated).model_dump(mode="json"),
        message="登记已更新",
    )


@router.post("/micro-records/{record_id}/photos", summary="上传平皿照片（多张，归档为原始证据）")
async def upload_micro_photos_endpoint(
    record_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    rec = await get_micro_record(db, record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    keys = list(rec.photo_keys or [])
    for f in files[:10]:
        content = await f.read()
        if not content or len(content) > 20 * 1024 * 1024:
            continue
        key = f"micro/{record_id}/{uuid.uuid4().hex[:12]}_{_safe_filename(f.filename or 'photo.jpg')}"
        quality_storage.upload_attachment(key, content, f.content_type or "image/jpeg")
        keys.append(key)
    await update_micro_record(db, record_id, {"photo_keys": keys})
    return success_response(data={"photo_keys": keys}, message=f"已归档 {len(keys)} 张照片")


@router.get("/micro-records/{record_id}/photos/{key:path}", summary="平皿照片查看（原始证据）")
async def get_micro_photo_endpoint(
    record_id: uuid.UUID,
    key: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> Response:
    rec = await get_micro_record(db, record_id)
    if rec is None or not rec.photo_keys or key not in rec.photo_keys:
        raise HTTPException(status_code=404, detail="照片不存在")
    data = quality_storage.read_attachment(key)
    if data is None:
        raise HTTPException(status_code=404, detail="照片文件缺失")
    return Response(content=data, media_type="image/jpeg")


@router.delete("/micro-records/{record_id}", summary="删除微生物登记（软删除）")
async def delete_micro_record_endpoint(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    if not await delete_micro_record(db, record_id):
        raise HTTPException(status_code=404, detail="记录不存在")
    return success_response(message="已删除")


@router.get("/micro-records/export", summary="微生物登记表导出 Excel")
async def export_micro_records_endpoint(
    batch_no: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> StreamingResponse:
    import io as _io

    import openpyxl

    from app.modules.quality import lc_template_parser

    rows = await list_micro_records(db, batch_no=batch_no)
    wb = openpyxl.Workbook()
    ws = lc_template_parser.active_sheet(wb)
    ws.title = "微生物登记"
    ws.append(["品名", "批号", "检测日期", "菌落计数", "警戒线", "标准限", "判定", "备注"])
    judge_label = {"pass": "合格", "alert": "超警戒", "action": "超标准"}
    for r in rows:
        ws.append([
            r.sample_name, r.batch_number or "-", r.sample_date or "-",
            r.colony_count if r.colony_count is not None else "-",
            r.alert_limit if r.alert_limit is not None else "-",
            r.action_limit if r.action_limit is not None else "-",
            judge_label.get(r.judge or "", r.judge or "-"),
            r.remark or "-",
        ])
    buf = _io.BytesIO()
    wb.save(buf)
    encoded = quote("微生物登记表.xlsx")
    return StreamingResponse(
        BytesIO(buf.getvalue()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="micro.xlsx"; filename*=UTF-8\'\'{encoded}'},
    )


# ─── 留样台账 ───


@router.get("/retained-samples", summary="留样台账列表")
async def list_retained_samples_endpoint(
    source_type: str | None = Query(default=None, description="product 成品 / material 物料"),
    batch_no: str | None = Query(default=None, description="批号模糊"),
    status: str | None = Query(default=None, description="active 在留 / destroyed 已销毁"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> JSONResponse:
    items = await list_retained_samples_with_names(db, source_type, batch_no, status)
    return success_response(data=[RetainedSampleOut.model_validate(i).model_dump(mode="json") for i in items])


@router.post("/retained-samples", summary="留样登记（成品/物料批留样台账）", status_code=201)
async def create_retained_sample_endpoint(
    payload: RetainedSampleCreate = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    existing = [r for r in await list_retained_samples(db, batch_no=payload.batch_no) if r.batch_no == payload.batch_no]
    if existing:
        raise HTTPException(status_code=409, detail=f"批号 {payload.batch_no} 已有留样登记，请直接编辑已有记录")
    rec = await create_retained_sample(db, {**payload.model_dump(), "created_by": user.id})
    item = await get_retained_sample_with_names(db, rec.id)
    return success_response(
        data=RetainedSampleOut.model_validate(item).model_dump(mode="json"),
        message="留样登记已保存", status_code=201,
    )


@router.put("/retained-samples/{record_id}", summary="更新留样登记")
async def update_retained_sample_endpoint(
    record_id: uuid.UUID,
    payload: RetainedSampleUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    rec = await get_retained_sample(db, record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    if rec.status == "destroyed":
        raise HTTPException(status_code=400, detail="已销毁的留样不可修改")
    if rec.destroyed_by is not None:
        raise HTTPException(status_code=400, detail="销毁登记已提交、等待第二人确认，暂不可编辑")
    data = {**payload.model_dump(exclude_none=True), "updated_by": user.id}
    await update_retained_sample(db, record_id, data)
    item = await get_retained_sample_with_names(db, record_id)
    return success_response(
        data=RetainedSampleOut.model_validate(item).model_dump(mode="json"),
        message="留样登记已更新",
    )


@router.post("/retained-samples/{record_id}/destroy", summary="销毁登记（双人确认：第一人登记，第二人确认后状态转已销毁）")
async def destroy_retained_sample_endpoint(
    record_id: uuid.UUID,
    payload: RetainedSampleDestroy = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    rec = await get_retained_sample(db, record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    if rec.status == "destroyed":
        raise HTTPException(status_code=400, detail="该留样已销毁")
    if rec.destroyed_by is None:
        # 第一人：登记销毁日期
        data = {
            "destroyed_at": payload.destroyed_at,
            "destroyed_by": user.id,
            "remark": payload.remark or rec.remark,
            "updated_by": user.id,
        }
        await update_retained_sample(db, record_id, data)
        item = await get_retained_sample_with_names(db, record_id)
        return success_response(
            data=RetainedSampleOut.model_validate(item).model_dump(mode="json"),
            message="销毁登记已记录，等待第二人确认",
        )
    if rec.destroyed_by == user.id:
        raise HTTPException(status_code=400, detail="同一人不能登记又确认，请另一位同事确认")
    # 第二人：确认销毁，状态转已销毁
    data = {
        "destroy_confirm_by": user.id,
        "status": "destroyed",
        "updated_by": user.id,
    }
    await update_retained_sample(db, record_id, data)
    item = await get_retained_sample_with_names(db, record_id)
    return success_response(
        data=RetainedSampleOut.model_validate(item).model_dump(mode="json"),
        message="销毁已确认，留样状态已转已销毁",
    )


@router.delete("/retained-samples/{record_id}", summary="删除留样登记（软删除）")
async def delete_retained_sample_endpoint(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    if not await delete_retained_sample(db, record_id):
        raise HTTPException(status_code=404, detail="记录不存在")
    return success_response(message="已删除")


@router.get("/retained-samples/export", summary="留样台账导出 Excel")
async def export_retained_samples_endpoint(
    source_type: str | None = Query(default=None),
    batch_no: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> StreamingResponse:
    import io as _io

    import openpyxl

    from app.modules.quality import lc_template_parser

    rows = await list_retained_samples_with_names(
        db, source_type=source_type, batch_no=batch_no, status=status
    )
    wb = openpyxl.Workbook()
    ws = lc_template_parser.active_sheet(wb)
    ws.title = "留样台账"
    ws.append([
        "类型", "品名", "批号", "留样量", "贮存位置", "留样日期", "销毁到期日",
        "销毁日期", "销毁登记人", "销毁确认人", "状态", "备注",
    ])
    type_label = {"product": "成品", "material": "物料"}
    for r in rows:
        ws.append([
            type_label.get(r["source_type"], r["source_type"]),
            r["sample_name"], r["batch_no"],
            r["qty"] or "-", r["location"] or "-",
            r["retained_at"] or "-", r["destroy_due_date"] or "-",
            r["destroyed_at"] or "-",
            r["destroyed_by_name"] or "-",
            r["destroy_confirm_by_name"] or "-",
            "已销毁" if r["status"] == "destroyed" else "在留",
            r["remark"] or "-",
        ])
    buf = _io.BytesIO()
    wb.save(buf)
    encoded = quote("留样台账.xlsx")
    return StreamingResponse(
        BytesIO(buf.getvalue()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="retained.xlsx"; filename*=UTF-8\'\'{encoded}'},
    )
