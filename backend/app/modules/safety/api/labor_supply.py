"""Safety API — labor_supply endpoints（劳保用品目录直读 + 附件代理下载）。"""

from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.core.response import ApiResponse
from app.core.deps import CurrentUser, get_current_user
from app.modules.safety.schemas.labor_supply import (
    LaborProductAttachment,
    LaborProductItem,
    LaborSupplyProductsData,
    LaborSupplyStats,
)
from app.modules.safety.service.bitable_direct import build_attachment_extra
from app.modules.safety.service.labor_supply import ledger as ls_ledger
from app.modules.safety.service.labor_supply.reader import (
    F_MANUAL,
    F_REPORT,
    LaborProductView,
    coverage_stats,
    filter_products,
)

logger = logging.getLogger(__name__)

labor_supply_router = APIRouter()

_ATTACHMENT_FIELDS = (F_REPORT, F_MANUAL)


def _to_item(view: LaborProductView) -> LaborProductItem:
    def _atts(items: list[dict]) -> list[LaborProductAttachment]:
        return [
            LaborProductAttachment(file_token=a.get("file_token", ""), name=a.get("name", ""))
            for a in items
            if a.get("file_token")
        ]

    return LaborProductItem(
        record_id=view.record_id,
        name=view.name,
        model=view.model,
        category=view.category,
        protection_type=view.protection_type,
        unit=view.unit,
        vendor=view.vendor,
        lifespan_years=view.lifespan_years,
        report_attachments=_atts(view.report_attachments),
        manual_attachments=_atts(view.manual_attachments),
    )


@labor_supply_router.get(
    "/labor-supply/products", response_model=ApiResponse, summary="劳保用品目录列表"
)
async def list_labor_products(
    protection_type: str | None = Query(None, description="防护类型（精确）"),
    category: str | None = Query(None, description="类别（精确）"),
    keyword: str | None = Query(None, description="关键词（名称/型号/厂家/防护类型包含）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """劳保用品目录（直读 Bitable，102 行量级内存过滤；source 三态信封）。"""
    if not ls_ledger.enabled():
        return ApiResponse(data=LaborSupplyProductsData(source="not_enabled"))
    try:
        views = await ls_ledger.fetch_products()
    except Exception:
        logger.warning("劳保用品目录直读失败（降级展示）", exc_info=True)
        return ApiResponse(data=LaborSupplyProductsData(source="degraded"))

    filtered = filter_products(
        views, keyword=keyword, category=category, protection_type=protection_type
    )
    total = len(filtered)
    skip = (page - 1) * page_size
    page_items = [_to_item(v) for v in filtered[skip : skip + page_size]]
    data = LaborSupplyProductsData(
        items=page_items,
        total=total,
        stats=LaborSupplyStats(**coverage_stats(views)),
        source="bitable",
        meta={"page": page, "page_size": page_size, "total": total},
    )
    return ApiResponse(data=data)


@labor_supply_router.get(
    "/labor-supply/attachments/{record_id}",
    summary="劳保用品附件代理下载（检测报告/说明书）",
)
async def download_labor_attachment(
    record_id: str,
    field_name: str = Query(..., description=f"附件字段名：{' 或 '.join(_ATTACHMENT_FIELDS)}"),
    file_token: str = Query(..., description="附件 file_token（须属于该记录该字段）"),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """附件代理下载：校验 token 归属（防任意 token 探测）→ bitablePerm extra 鉴权下载。"""
    if field_name not in _ATTACHMENT_FIELDS:
        return ApiResponse(code=400, message=f"仅支持附件字段：{' / '.join(_ATTACHMENT_FIELDS)}")
    if not ls_ledger.enabled():
        return ApiResponse(code=503, message="劳保直读已停用")
    try:
        views = await ls_ledger.fetch_products()
    except Exception:
        logger.warning("劳保附件定位失败（直读不可达）", exc_info=True)
        return ApiResponse(code=502, message="劳保目录暂时不可达，请稍后重试")

    view = next((v for v in views if v.record_id == record_id), None)
    if view is None:
        return ApiResponse(code=404, message="记录不存在")
    atts = view.report_attachments if field_name == F_REPORT else view.manual_attachments
    meta = next((a for a in atts if a.get("file_token") == file_token), None)
    if meta is None:
        return ApiResponse(code=404, message="附件不存在或不属于该字段")

    from app.modules.safety.bitable_config.store import store as bitable_store
    from app.modules.safety.feishu.bitable_client import SafetyBitableClient

    conn = bitable_store.get_connection(ls_ledger.DOMAIN, ls_ledger.KIND_PRODUCT)
    if conn is None or not conn.enabled:
        return ApiResponse(code=503, message="劳保用品表连接未启用")
    client = SafetyBitableClient(app_token=conn.app_token, table_id=conn.table_id)

    extra: str | None = None
    field_id = await client.get_field_id_by_name(field_name)
    if field_id:
        extra = build_attachment_extra(conn.table_id, record_id, field_id, file_token)
    content = await client.download_attachment(file_token, extra)
    if content is None:
        return ApiResponse(code=502, message="附件下载失败，请稍后重试")

    filename = meta.get("name") or f"{file_token}.bin"
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        },
    )
