"""五金库 REST 子路由：挂 warehouse api.py 聚合处 → /api/v1/warehouse/hardware/*。

只做入参、依赖注入、调 service、统一响应；权限码 warehouse:hardware:*。
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.warehouse.hardware import service
from app.modules.warehouse.hardware.schemas import (
    CodeBackfillStatsResponse,
    ImportStatsResponse,
    LocationCreate,
    LocationResponse,
    MaterialCreate,
    MaterialResponse,
    MaterialStockDetailResponse,
    MaterialUpdate,
    MovementErpMark,
    MovementResponse,
    ReceiptAccept,
    ReceiptCreate,
    ReceiptReject,
    ReceiptResponse,
    RequisitionApprove,
    RequisitionCreate,
    RequisitionIssue,
    RequisitionReject,
    RequisitionResponse,
    ReturnAcceptBody,
    ReturnCreate,
    ReturnReject,
    ReturnResponse,
    ReturnSign,
    StockRowResponse,
    StocktakeConfirm,
    StocktakeCreate,
    StocktakeItemFill,
    StocktakeItemResponse,
    StocktakeResponse,
    StocktakeReview,
)
from app.modules.warehouse.hardware import stocktake as stocktake_service
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hardware", tags=["warehouse-hardware"])


def _clean(value: str | None) -> str | None:
    text = value.strip() if value else ""
    return text or None


def _material_response(m: Any) -> dict[str, Any]:
    return MaterialResponse.model_validate(m).model_dump(mode="json")


def _movement_response(m: Any) -> dict[str, Any]:
    return MovementResponse.model_validate(m).model_dump(mode="json")


# ── 库存总览 ──


@router.get("/stock", summary="五金库库存总览（available=on_hand−reserved）")
async def list_stock(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    keyword: str | None = Query(default=None, description="名称/规格/编码关键词"),
    category: str | None = Query(default=None, description="类别"),
    managed_class: str | None = Query(default="stocked", description="stocked/direct/空=全部"),
    low_only: bool = Query(default=False, description="只看安全库存预警"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:stock:read")),
) -> JSONResponse:
    rows, total = await service.list_stock_rows(
        db,
        keyword=_clean(keyword),
        category=_clean(category),
        managed_class=_clean(managed_class),
        low_only=low_only,
        page=page,
        page_size=page_size,
    )
    data = [
        {
            **StockRowResponse(
                material=MaterialResponse.model_validate(r["material"]),
                on_hand=r["on_hand"],
                reserved=r["reserved"],
                available=r["available"],
                is_low=r["is_low"],
                low_gap=r["low_gap"],
            ).model_dump(mode="json"),
            "category": r["material"].category,
            "name": r["material"].name,
            "spec": r["material"].spec,
            "unit": r["material"].unit,
            "code": r["material"].code,
            "safety_stock": float(r["material"].safety_stock),
        }
        for r in rows
    ]
    return paginated_response(data, page, page_size, total)


@router.get("/stock/summary", summary="库存概览统计（物料数/预警数/在手总量）")
async def stock_summary(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:stock:read")),
) -> JSONResponse:
    rows, _total = await service.list_stock_rows(
        db, page=1, page_size=1, managed_class=None
    )
    # 全量拉取聚合（492 项规模一次查询可承受）
    all_rows, total = await service.list_stock_rows(
        db, page=1, page_size=5000, managed_class=None
    )
    low = [r for r in all_rows if r["is_low"]]
    stocked = [r for r in all_rows if r["material"].managed_class == "stocked"]
    return success_response(
        {
            "total_materials": total,
            "stocked_materials": len(stocked),
            "low_count": len(low),
            "on_hand_total": float(sum((r["on_hand"] for r in all_rows), start=0)),
            "reserved_total": float(sum((r["reserved"] for r in all_rows), start=0)),
            "low_materials": [
                {
                    "id": str(r["material"].id),
                    "name": r["material"].name,
                    "spec": r["material"].spec,
                    "available": float(r["available"]),
                    "safety_stock": float(r["material"].safety_stock),
                }
                for r in low[:20]
            ],
        }
    )


@router.get("/stock/{material_id}", summary="物料库存详情（批次 FIFO 序+近流水）")
async def get_stock_detail(
    material_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:stock:read")),
) -> JSONResponse:
    detail = await service.get_material_stock(db, material_id)
    data = MaterialStockDetailResponse(
        stock=StockRowResponse(
            material=MaterialResponse.model_validate(detail["material"]),
            on_hand=detail["on_hand"],
            reserved=detail["reserved"],
            available=detail["available"],
            is_low=detail["is_low"],
            low_gap=detail["low_gap"],
        ),
        lots=detail["lots"],
        recent_movements=[
            MovementResponse.model_validate(m) for m in detail["recent_movements"]
        ],
    )
    return success_response(data.model_dump(mode="json"))


@router.get("/stock/{material_id}/fifo-suggestion", summary="发料 FIFO 批次建议")
async def fifo_suggestion(
    material_id: UUID,
    qty: str = Query(..., description="需发数量"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:stock:read")),
) -> JSONResponse:
    from decimal import Decimal, InvalidOperation

    try:
        qty_dec = Decimal(qty)
    except InvalidOperation as exc:
        raise HTTPException(status_code=422, detail="数量格式错误") from exc
    plan = await service.suggest_fifo_allocation(db, material_id, qty_dec)
    return success_response(plan)


# ── 物料主数据 ──


@router.get("/materials", summary="物料主数据分页列表")
async def list_materials(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    keyword: str | None = Query(default=None),
    category: str | None = Query(default=None),
    managed_class: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:stock:read")),
) -> JSONResponse:
    items, total = await service.list_materials(
        db,
        keyword=_clean(keyword),
        category=_clean(category),
        managed_class=_clean(managed_class),
        page=page,
        page_size=page_size,
    )
    return paginated_response(
        [MaterialResponse.model_validate(m).model_dump(mode="json") for m in items],
        page, page_size, total,
    )


@router.post("/materials", status_code=201, summary="新增物料（主数据维护）")
async def create_material(
    payload: MaterialCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:material:manage")),
) -> JSONResponse:
    material = await service.create_material_manual(db, payload, user)
    return success_response(
        MaterialResponse.model_validate(material).model_dump(mode="json"), status_code=201
    )


@router.put("/materials/{material_id}", summary="编辑物料")
async def update_material(
    material_id: UUID,
    payload: MaterialUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:material:manage")),
) -> JSONResponse:
    material = await service.update_material(db, material_id, payload, user)
    return success_response(MaterialResponse.model_validate(material).model_dump(mode="json"))


@router.post(
    "/materials/import",
    status_code=201,
    summary="导入物资清单 xlsx（幂等 upsert，code 留空）",
)
async def import_materials(
    file: UploadFile = File(..., description="五金库物资清单 xlsx"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:material:manage")),
) -> JSONResponse:
    import tempfile
    from pathlib import Path

    from app.modules.warehouse.hardware.importer import import_materials

    suffix = Path(file.filename or "").suffix or ".xlsx"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)
    try:
        stats = await import_materials(db, tmp_path, user_id=user.id)
    finally:
        tmp_path.unlink(missing_ok=True)
    return success_response(
        ImportStatsResponse(**stats).model_dump(mode="json"), status_code=201
    )


@router.post(
    "/materials/import-codes",
    status_code=201,
    summary="编码表回填（P2 通道：采购部《物料编码表》Excel 到位后执行）",
)
async def import_codes(
    file: UploadFile = File(..., description="采购物料编码表 xlsx"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:material:manage")),
) -> JSONResponse:
    import tempfile
    from pathlib import Path

    from app.modules.warehouse.hardware.importer import backfill_codes

    suffix = Path(file.filename or "").suffix or ".xlsx"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)
    try:
        stats = await backfill_codes(db, tmp_path, user_id=user.id)
    finally:
        tmp_path.unlink(missing_ok=True)
    return success_response(
        CodeBackfillStatsResponse(**stats).model_dump(mode="json"), status_code=201
    )


# ── 库位 ──


@router.get("/locations", summary="五金库库位列表")
async def list_locations(
    keyword: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:stock:read")),
) -> JSONResponse:
    locs = await service.list_locations(db, keyword=_clean(keyword))
    return success_response(
        [LocationResponse.model_validate(loc).model_dump(mode="json") for loc in locs]
    )


@router.post("/locations", status_code=201, summary="新增库位")
async def create_location(
    payload: LocationCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:location:manage")),
) -> JSONResponse:
    loc = await service.create_location(
        db, code=payload.code, zone=payload.zone, description=payload.description, user=user
    )
    return success_response(
        LocationResponse.model_validate(loc).model_dump(mode="json"), status_code=201
    )


# ── 入库单（M2 起用；API 契约 M1 一并立好）──


@router.get("/receipts", summary="入库单分页列表")
async def list_receipts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    status: str | None = Query(default=None, description="draft/accepted/rejected"),
    source: str | None = Query(default=None, description="ocr/manual/erp_import"),
    keyword: str | None = Query(default=None, description="单号/供应商/送货单号"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:inbound:read")),
) -> JSONResponse:
    items, total = await service.list_receipts(
        db, status=_clean(status), source=_clean(source), keyword=_clean(keyword),
        page=page, page_size=page_size,
    )
    data = [
        ReceiptResponse.model_validate(
            await _receipt_with_items(db, r)
        ).model_dump(mode="json")
        for r in items
    ]
    return paginated_response(data, page, page_size, total)


async def _receipt_with_items(db: AsyncSession, receipt: Any) -> Any:
    """组装响应（items + 物料名冗余，避免前端二次查询）。"""
    from app.modules.warehouse.hardware.models import HardwareMaterial
    from sqlalchemy import select

    items = await service.list_receipt_items(db, receipt.id)
    material_ids = {i.material_id for i in items if i.material_id}
    materials: dict[UUID, HardwareMaterial] = {}
    if material_ids:
        rows = (
            await db.execute(
                select(HardwareMaterial).where(HardwareMaterial.id.in_(material_ids))
            )
        ).scalars().all()
        materials = {m.id: m for m in rows}
    payload = ReceiptResponse.model_validate(receipt)
    payload.items = [
        {
            "id": str(i.id),
            "material_id": str(i.material_id) if i.material_id else None,
            "material_name": materials[i.material_id].name if i.material_id in materials else None,
            "material_code": materials[i.material_id].code if i.material_id in materials else None,
            "name": i.name,
            "spec": i.spec,
            "unit": i.unit,
            "quantity": i.quantity,
            "location_id": str(i.location_id) if i.location_id else None,
            "lot_no": i.lot_no,
            "expiry_date": i.expiry_date,
            "remaining_quantity": i.remaining_quantity,
            "match_confidence": i.match_confidence,
            "match_score": i.match_score,
            "unit_price": i.unit_price,
        }
        for i in items
    ]
    return payload


@router.get("/receipts/{receipt_id}", summary="入库单详情")
async def get_receipt(
    receipt_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:inbound:read")),
) -> JSONResponse:
    receipt = await service.get_receipt(db, receipt_id)
    return success_response(
        ReceiptResponse.model_validate(
            await _receipt_with_items(db, receipt)
        ).model_dump(mode="json")
    )


@router.post("/receipts/ocr", status_code=201, summary="送货单拍照 OCR → 入库草稿（不动账）")
async def ocr_receipt(
    file: UploadFile = File(..., description="送货单照片"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:inbound:create")),
) -> JSONResponse:
    import base64

    from app.modules.warehouse.hardware.receipt_pipeline import (
        ScenarioDisabled as HwScenarioDisabled,
        build_ocr_draft,
    )

    content = await file.read()
    content_type = file.content_type or "image/jpeg"
    if content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(status_code=422, detail="仅支持 JPEG/PNG 图片")
    image_b64 = base64.b64encode(content).decode()
    try:
        receipt, summary = await build_ocr_draft(
            db, image_b64=image_b64, content_type=content_type,
            operator=user.display_name if hasattr(user, "display_name") else None,
        )
    except HwScenarioDisabled as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — LLM 失败转可读错误
        logger.exception("五金送货单 OCR 失败")
        raise HTTPException(status_code=502, detail=f"识别失败，请用手动登记兜底: {exc}") from exc
    payload = await _receipt_with_items(db, receipt)
    return success_response(
        {"receipt": payload.model_dump(mode="json"), "match_summary": summary["rows"],
         "matched_stocked": summary["matched_stocked"], "unmatched": summary["unmatched"]},
        status_code=201,
    )


@router.post("/receipts", status_code=201, summary="登记入库草稿（manual 兜底/OCR 落库）")
async def create_receipt(
    payload: ReceiptCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:inbound:create")),
) -> JSONResponse:
    receipt = await service.create_receipt(db, payload, user=user)
    return success_response(
        ReceiptResponse.model_validate(
            await _receipt_with_items(db, receipt)
        ).model_dump(mode="json"), status_code=201,
    )


@router.post("/receipts/{receipt_id}/accept", summary="确认入账（双签，库存+）")
async def accept_receipt(
    receipt_id: UUID,
    payload: ReceiptAccept,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:inbound:confirm")),
) -> JSONResponse:
    receipt = await service.accept_receipt(
        db, receipt_id,
        inspected_by_warehouse=payload.inspected_by_warehouse,
        inspected_by_dept=payload.inspected_by_dept,
        inspect_checklist=payload.inspect_checklist,
        items=payload.items,
        user=user,
    )
    return success_response(
        ReceiptResponse.model_validate(
            await _receipt_with_items(db, receipt)
        ).model_dump(mode="json")
    )


@router.post("/receipts/{receipt_id}/reject", summary="拒收退供应商（留证+通知采购）")
async def reject_receipt(
    receipt_id: UUID,
    payload: ReceiptReject,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:inbound:confirm")),
) -> JSONResponse:
    receipt = await service.reject_receipt(db, receipt_id, reason=payload.reason, user=user)
    await _notify_receipt_rejected(db, receipt)
    return success_response(
        ReceiptResponse.model_validate(
            await _receipt_with_items(db, receipt)
        ).model_dump(mode="json")
    )


async def _notify_receipt_rejected(db: AsyncSession, receipt: Any) -> None:
    """拒收通知采购（push 事件，失败不影响主业务）。"""
    try:
        from app.modules.warehouse.push_center.events import fire_push_event

        await fire_push_event(
            db,
            "hardware_receipt_rejected",
            {
                "receipt_no": receipt.receipt_no,
                "supplier_name": receipt.supplier_name or "-",
                "reason": receipt.rejected_reason or "-",
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception("拒收通知推送失败（不影响拒收主流程）")


# ── 领用申请（M3 起用；API 契约 M1 一并立好）──


@router.get("/requisitions", summary="领用申请分页列表")
async def list_requisitions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    status: str | None = Query(default=None),
    dept_name: str | None = Query(default=None),
    req_type: str | None = Query(default=None),
    keyword: str | None = Query(default=None, description="单号/领用人"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:requisition:read")),
) -> JSONResponse:
    items, total = await service.list_requisitions(
        db, status=_clean(status), dept_name=_clean(dept_name),
        req_type=_clean(req_type), keyword=_clean(keyword),
        page=page, page_size=page_size,
    )
    data = [await _requisition_response(db, r) for r in items]
    return paginated_response(data, page, page_size, total)


async def _requisition_response(db: AsyncSession, req: Any) -> dict[str, Any]:
    from sqlalchemy import select

    from app.modules.warehouse.hardware.models import HardwareMaterial

    items = await service.list_requisition_items(db, req.id)
    material_ids = {i.material_id for i in items}
    materials: dict[UUID, HardwareMaterial] = {}
    if material_ids:
        rows = (
            await db.execute(
                select(HardwareMaterial).where(HardwareMaterial.id.in_(material_ids))
            )
        ).scalars().all()
        materials = {m.id: m for m in rows}
    payload = RequisitionResponse.model_validate(req)
    payload.items = [
        {
            "id": str(i.id),
            "material_id": str(i.material_id),
            "material_name": materials[i.material_id].name,
            "material_code": materials[i.material_id].code,
            "spec": materials[i.material_id].spec,
            "unit": materials[i.material_id].unit,
            "need_qty": i.need_qty,
            "issued_qty": i.issued_qty,
            "fifo_lot_allocations": i.fifo_lot_allocations,
        }
        for i in items
    ]
    return payload.model_dump(mode="json")


@router.get("/requisitions/{requisition_id}", summary="领用申请详情")
async def get_requisition(
    requisition_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:requisition:read")),
) -> JSONResponse:
    req = await service.get_requisition(db, requisition_id)
    return success_response(await _requisition_response(db, req))


@router.post("/requisitions", status_code=201, summary="创建领用申请（草稿）")
async def create_requisition(
    payload: RequisitionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:requisition:create")),
) -> JSONResponse:
    req = await service.create_requisition(db, payload, user=user)
    return success_response(await _requisition_response(db, req), status_code=201)


@router.post("/requisitions/{requisition_id}/submit", summary="提交审批（预扣生效）")
async def submit_requisition(
    requisition_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:requisition:create")),
) -> JSONResponse:
    req = await service.submit_requisition(db, requisition_id, user=user)
    await _after_submit_channel(db, req)
    return success_response(await _requisition_response(db, req))


async def _after_submit_channel(db: AsyncSession, req: Any) -> None:
    """提交后按配置创建审批实例（feishu 通道；M3 接入，未配置自动 manual）。"""
    try:
        from app.modules.warehouse.hardware.approval_channel import submit_approval

        await submit_approval(db, req)
    except Exception:  # noqa: BLE001
        logger.exception("审批通道提交失败（不影响申请主流程）")


@router.post("/requisitions/{requisition_id}/approve", summary="审批通过（manual 通道代录）")
async def approve_requisition(
    requisition_id: UUID,
    payload: RequisitionApprove,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:requisition:approve")),
) -> JSONResponse:
    req = await service.approve_requisition(
        db, requisition_id, approver=payload.approver, note=payload.note, user=user
    )
    return success_response(await _requisition_response(db, req))


@router.post("/requisitions/{requisition_id}/reject", summary="驳回（释放预扣）")
async def reject_requisition(
    requisition_id: UUID,
    payload: RequisitionReject,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:requisition:approve")),
) -> JSONResponse:
    req = await service.reject_requisition(
        db, requisition_id, approver=payload.approver, reason=payload.reason, user=user
    )
    await _notify_requisition_rejected(db, req)
    return success_response(await _requisition_response(db, req))


async def _notify_requisition_rejected(db: AsyncSession, req: Any) -> None:
    try:
        from app.modules.warehouse.push_center.events import fire_push_event

        await fire_push_event(
            db,
            "hardware_requisition_rejected",
            {"req_no": req.req_no, "applicant": req.applicant, "reason": req.rejected_reason or "-"},
        )
    except Exception:  # noqa: BLE001
        logger.exception("驳回通知推送失败（不影响主流程）")


@router.post("/requisitions/{requisition_id}/cancel", summary="取消申请（pending 取消=释放预扣）")
async def cancel_requisition(
    requisition_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:requisition:create")),
) -> JSONResponse:
    req = await service.cancel_requisition(db, requisition_id, user=user)
    return success_response(await _requisition_response(db, req))


@router.post("/requisitions/{requisition_id}/issue", summary="发料确认（FIFO 实扣+点收）")
async def issue_requisition(
    requisition_id: UUID,
    payload: RequisitionIssue,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:requisition:issue")),
) -> JSONResponse:
    req = await service.issue_requisition(
        db, requisition_id,
        issued_by=payload.issued_by,
        received_by=payload.received_by,
        items=[i.model_dump(mode="json") for i in payload.items],
        user=user,
    )
    return success_response(await _requisition_response(db, req))


# ── 流水 ──


@router.get("/movements", summary="五金库出入库流水分页")
async def list_movements(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    direction: str | None = Query(default=None, description="inbound/outbound/adjust"),
    business_type: str | None = Query(default=None),
    keyword: str | None = Query(default=None, description="单号/品名/批次"),
    dept_name: str | None = Query(default=None, description="部门（direct 明细/领用部门）"),
    erp_status: str | None = Query(default=None, description="pending/entered"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:report:read")),
) -> JSONResponse:
    items, total = await service.list_movements(
        db, direction=_clean(direction), business_type=_clean(business_type),
        keyword=_clean(keyword), dept_name=_clean(dept_name), erp_status=_clean(erp_status),
        page=page, page_size=page_size,
    )
    return paginated_response(
        [MovementResponse.model_validate(m).model_dump(mode="json") for m in items],
        page, page_size, total,
    )


@router.post("/movements/mark-entered", summary="ERP 已录标记（月度对账）")
async def mark_movements_entered(
    payload: MovementErpMark,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:report:read")),
) -> JSONResponse:
    count = await service.mark_movements_entered(
        db, [UUID(mid) for mid in payload.movement_ids],
        erp_operator=payload.erp_operator, user=user,
    )
    return success_response({"marked": count})


# ── 盘点（二期 M4：闭环=生成→实盘直填→差异表→人确认→ADJ 入账）──


def _stocktake_response(t: Any) -> dict[str, Any]:
    return StocktakeResponse.model_validate(t).model_dump(mode="json")


@router.get("/stocktakes", summary="盘点单分页列表")
async def list_stocktakes(
    status: str | None = Query(default=None),
    take_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:stocktake:read")),
) -> JSONResponse:
    items, total = await stocktake_service.list_stocktakes(
        db, status=status, take_type=take_type, page=page, page_size=page_size
    )
    return paginated_response(
        [_stocktake_response(t) for t in items], total=total, page=page, page_size=page_size
    )


@router.post("/stocktakes", status_code=201, summary="生成盘点单（book 快照自当前批次余额）")
async def create_stocktake(
    payload: StocktakeCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:stocktake:manage")),
) -> JSONResponse:
    creator = getattr(user, "display_name", None) or str(user.id)
    take = await stocktake_service.create_stocktake(
        db, take_type=payload.take_type, creator=creator, note=payload.note, user=user
    )
    return success_response(_stocktake_response(take))


@router.get("/stocktakes/{stocktake_id}", summary="盘点单详情（含明细行）")
async def get_stocktake(
    stocktake_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:stocktake:read")),
) -> JSONResponse:
    take = await stocktake_service.get_stocktake(db, stocktake_id)
    items = await stocktake_service.list_stocktake_items(db, stocktake_id)
    return success_response({
        **_stocktake_response(take),
        "items": [
            StocktakeItemResponse.model_validate(i).model_dump(mode="json") for i in items
        ],
    })


@router.put(
    "/stocktakes/{stocktake_id}/items/{item_id}",
    summary="实盘直填（手机；填数即算差异）",
)
async def fill_stocktake_item(
    stocktake_id: UUID,
    item_id: UUID,
    payload: StocktakeItemFill,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:stocktake:manage")),
) -> JSONResponse:
    item = await stocktake_service.fill_stocktake_item(
        db, stocktake_id, item_id,
        actual_qty=payload.actual_qty, explanation=payload.explanation,
    )
    return success_response(StocktakeItemResponse.model_validate(item).model_dump(mode="json"))


@router.get("/stocktakes/{stocktake_id}/export", summary="差异表导出 Excel（报财务）")
async def export_stocktake(
    stocktake_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:stocktake:read")),
):
    from datetime import datetime as _dt
    from urllib.parse import quote

    from fastapi.responses import Response

    xlsx = await stocktake_service.export_stocktake_excel(db, stocktake_id)
    take = await stocktake_service.get_stocktake(db, stocktake_id)
    filename = f"五金库盘点差异表_{take.take_no}_{_dt.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return Response(
        content=xlsx,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.post("/stocktakes/{stocktake_id}/review", summary="差异复核（全行盘完才可）")
async def review_stocktake(
    stocktake_id: UUID,
    payload: StocktakeReview,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:stocktake:manage")),
) -> JSONResponse:
    take = await stocktake_service.review_stocktake(
        db, stocktake_id, explained_by=payload.explained_by, note=payload.note
    )
    return success_response(_stocktake_response(take))


@router.post(
    "/stocktakes/{stocktake_id}/confirm",
    summary="确认入账（Web 确认门：人确认才 ADJ 入账）",
)
async def confirm_stocktake(
    stocktake_id: UUID,
    payload: StocktakeConfirm,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:stocktake:manage")),
) -> JSONResponse:
    take = await stocktake_service.confirm_stocktake(
        db, stocktake_id, confirmed_by=payload.confirmed_by
    )
    return success_response(_stocktake_response(take))


@router.post("/stocktakes/{stocktake_id}/cancel", summary="作废盘点单（确认前）")
async def cancel_stocktake(
    stocktake_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:stocktake:manage")),
) -> JSONResponse:
    take = await stocktake_service.cancel_stocktake(db, stocktake_id)
    return success_response(_stocktake_response(take))


# ── 退库（二期 M4：负责人签→仓管员验收→批次回加）──


def _return_response(r: Any) -> dict[str, Any]:
    return ReturnResponse.model_validate(r).model_dump(mode="json")


@router.get("/returns", summary="退库单分页列表")
async def list_returns(
    status: str | None = Query(default=None),
    dept_name: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:return:manage")),
) -> JSONResponse:
    items, total = await stocktake_service.list_returns(
        db, status=status, dept_name=dept_name, page=page, page_size=page_size
    )
    return paginated_response(
        [_return_response(r) for r in items], total=total, page=page, page_size=page_size
    )


@router.post("/returns", status_code=201, summary="登记退库单（草稿，仅 stocked）")
async def create_return(
    payload: ReturnCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:return:manage")),
) -> JSONResponse:
    ret = await stocktake_service.create_return(
        db,
        dept_name=payload.dept_name,
        returned_by=payload.returned_by,
        returned_by_open_id=payload.returned_by_open_id,
        items=[i.model_dump() for i in payload.items],
        remark=payload.remark,
    )
    return success_response(_return_response(ret))


@router.get("/returns/{return_id}", summary="退库单详情")
async def get_return(
    return_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:return:manage")),
) -> JSONResponse:
    ret = await stocktake_service.get_return(db, return_id)
    return success_response(_return_response(ret))


@router.post("/returns/{return_id}/sign", summary="部门负责人签收")
async def sign_return(
    return_id: UUID,
    payload: ReturnSign,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:return:manage")),
) -> JSONResponse:
    ret = await stocktake_service.sign_return(db, return_id, leader=payload.leader)
    return success_response(_return_response(ret))


@router.post(
    "/returns/{return_id}/accept",
    summary="仓管员验收（批次回加：原 lot 优先，无则新建 return 批次）",
)
async def accept_return(
    return_id: UUID,
    payload: ReturnAcceptBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:return:manage")),
) -> JSONResponse:
    ret = await stocktake_service.accept_return(
        db, return_id, accepted_by=payload.accepted_by
    )
    return success_response(_return_response(ret))


@router.post("/returns/{return_id}/reject", summary="不合格拒退（留证不动账）")
async def reject_return(
    return_id: UUID,
    payload: ReturnReject,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:hardware:return:manage")),
) -> JSONResponse:
    ret = await stocktake_service.reject_return(db, return_id, reason=payload.reason)
    return success_response(_return_response(ret))
