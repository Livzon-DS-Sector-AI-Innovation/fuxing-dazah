"""物料赋码 API：批量赋码、台账查询、进出库、标签、物料字典、库存概览。"""

import uuid
from io import BytesIO
from urllib.parse import quote

from fastapi import Body, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.quality.api._common import router
from app.modules.quality.repository import (
    create_container_movement,
    create_material,
    delete_material,
    get_material_by_code,
    get_material_container_by_no,
    list_container_movements,
    list_containers_by_nos,
    list_material_containers,
    list_material_movements,
    list_materials,
    material_consumption_trend,
    material_stock_summary,
    material_today_stats,
    update_material,
)
from app.modules.quality.schemas import (
    ContainerBatchMoveRequest,
    ContainerLabelRequest,
    ContainerMovementOut,
    ContainerMoveRequest,
    ContainerStatusUpdate,
    MaterialContainerGenerateRequest,
    MaterialContainerListItem,
    MaterialContainerOut,
    MaterialCreate,
    MaterialOut,
    MaterialSummaryItem,
    MaterialUpdate,
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
