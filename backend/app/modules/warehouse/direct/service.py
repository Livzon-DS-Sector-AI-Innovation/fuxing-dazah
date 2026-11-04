"""直读端点编排层：缓存取数 → 过滤分页 → 序列化（键与镜像序列化逐键对齐）。

直读行 id/material_id = 飞书记录 ID（rec…）；location_* 为空串（库位是
本地概念，Base 无对应源）——/stocks 在直读模式下忽略 location_id 并在
meta 提示。
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any
from uuid import UUID

from app.modules.warehouse.direct import config, query, reader
from app.modules.warehouse.direct.cache import DirectCache
from app.modules.warehouse.direct.views import StockView

stock_cache: DirectCache[StockView] = DirectCache(config.cache_ttl_seconds)


def serialize_stock(view: StockView) -> dict[str, Any]:
    """键对齐 schemas.StockResponse（+QC 三列）；直读 QC 取 Base 真实列。"""
    return {
        "id": view.record_id,
        "material_id": view.record_id,
        "material_code": view.code,
        "material_name": view.name,
        "category": view.category,
        "unit": view.unit or None,
        "safety_stock": None,
        "batch_no": view.batch_no,
        "location_id": "",
        "location_code": "",
        "location_name": "",
        "expiry_date": view.expiry_date.isoformat() if view.expiry_date else None,
        "quantity": view.quantity,
        "status": view.status,
        "qc_sample_status": view.qc_sample_status,
        "qc_report_status": view.qc_report_status,
        "qc_release_status": view.qc_release_status,
    }


async def stocks_page(
    *,
    page: int,
    page_size: int,
    category: str | None = None,
    keyword: str | None = None,
    location_id: UUID | None = None,
    batch_no: str | None = None,
    expiry_from: date | None = None,
    expiry_to: date | None = None,
    status: str | None = None,
) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    """直读库存分页；返回 (rows, total, meta_extra)。"""
    started = time.monotonic()
    views = await stock_cache.get(lambda: reader.fetch_stocks())
    filtered = query.filter_stocks(
        views,
        category=category, keyword=keyword, batch_no=batch_no,
        expiry_from=expiry_from, expiry_to=expiry_to, status=status,
    )
    page_rows, total = query.paginate(filtered, page, page_size)
    data = [serialize_stock(v) for v in page_rows]
    meta: dict[str, Any] = {
        "mode": "direct",
        "elapsed_ms": round((time.monotonic() - started) * 1000),
    }
    if location_id is not None:
        meta["location_filter_ignored"] = "直读模式无库位概念，已忽略 location_id"
    return data, total, meta


# ── 物料 / 流水（T2）────────────────────────────────────────────

from app.modules.warehouse.direct.query import movement_no_of  # noqa: E402
from app.modules.warehouse.direct.views import MaterialView, MovementView  # noqa: E402

material_cache: DirectCache[MaterialView] = DirectCache(config.cache_ttl_seconds)
movement_cache: DirectCache[MovementView] = DirectCache(config.cache_ttl_seconds)


def serialize_material(view: MaterialView, *, unit: str = "", now_iso: str) -> dict[str, Any]:
    """键对齐 schemas.MaterialResponse。"""
    return {
        "id": view.record_id,
        "code": view.code,
        "name": view.name,
        "category": view.category,
        "spec": view.spec or None,
        "unit": unit or "",
        "safety_stock": 0.0,
        "remark": None,
        "created_at": now_iso,
        "updated_at": now_iso,
    }


def serialize_movement(view: MovementView) -> dict[str, Any]:
    """键对齐 schemas.MovementResponse；location_* 空（本地概念）。"""
    return {
        "id": view.record_id,
        "movement_no": movement_no_of(view),
        "direction": view.direction,
        "source_type": view.source_type,
        "material_id": view.record_id,
        "material_code": view.code,
        "material_name": view.name,
        "batch_no": view.batch_no,
        "quantity": view.quantity,
        "unit": view.unit,
        "location_id": "",
        "location_code": "",
        "location_name": "",
        "occurred_at": view.occurred_at.isoformat(),
        "remark": None,
        "created_at": view.occurred_at.isoformat(),
    }


async def materials_page(
    *, page: int, page_size: int,
    category: str | None = None, keyword: str | None = None,
) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    started = time.monotonic()
    views = await material_cache.get(lambda: reader.fetch_materials())
    out = views
    if category:
        out = [v for v in out if v.category == category]
    if keyword:
        kw = keyword.strip()
        out = [v for v in out if kw in v.code or kw in v.name]
    page_rows, total = query.paginate(out, page, page_size)
    from datetime import UTC, datetime as _dt

    now_iso = _dt.now(UTC).isoformat()
    # 单位列：master 无「单位」列——从库存域首见单位回填（展示口径）
    stocks = await stock_cache.get(lambda: reader.fetch_stocks())
    unit_by_code: dict[str, str] = {}
    for s in stocks:
        if s.unit and s.code and s.code not in unit_by_code:
            unit_by_code[s.code] = s.unit
    data = [
        serialize_material(v, unit=unit_by_code.get(v.code, ""), now_iso=now_iso)
        for v in page_rows
    ]
    return data, total, {
        "mode": "direct",
        "elapsed_ms": round((time.monotonic() - started) * 1000),
    }


async def movements_page(
    *, page: int, page_size: int,
    direction: str | None = None, source_type: str | None = None,
    keyword: str | None = None, location_id: UUID | None = None,
    material_id: str | None = None,   # 直读行 = 飞书记录 ID（rec…）
    occurred_from=None, occurred_to=None,
) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    started = time.monotonic()
    views = await movement_cache.get(lambda: reader.fetch_movements())
    code_filter: str | None = None
    if material_id is not None:
        # 直读行 material_id = master 记录 ID → 解析为代码过滤
        masters = await material_cache.get(lambda: reader.fetch_materials())
        code_filter = next(
            (m.code for m in masters if m.record_id == str(material_id)), None
        )
    filtered = query.filter_movements(
        views,
        direction=direction, source_type=source_type, keyword=keyword,
        code=code_filter, occurred_from=occurred_from, occurred_to=occurred_to,
    )
    page_rows, total = query.paginate(filtered, page, page_size)
    data = [serialize_movement(v) for v in page_rows]
    meta: dict[str, Any] = {
        "mode": "direct",
        "elapsed_ms": round((time.monotonic() - started) * 1000),
    }
    if location_id is not None:
        meta["location_filter_ignored"] = "直读模式无库位概念，已忽略 location_id"
    return data, total, meta


# ── 概览 / 驾驶舱（T3）──────────────────────────────────────────

from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.modules.warehouse.direct import analytics  # noqa: E402


async def _load_views() -> tuple[list, list, int]:
    """三域缓存取数 + 物料数（驾驶舱族共用）。"""
    stocks = await stock_cache.get(lambda: reader.fetch_stocks())
    movements = await movement_cache.get(lambda: reader.fetch_movements())
    materials = await material_cache.get(lambda: reader.fetch_materials())
    return stocks, movements, len(materials)


def _meta(started: float) -> dict[str, Any]:
    return {"mode": "direct", "elapsed_ms": round((time.monotonic() - started) * 1000)}


async def overview_data(db: AsyncSession) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.monotonic()
    stocks, movements, material_count = await _load_views()
    data = await analytics.overview(stocks, movements, material_count, db)
    return data, _meta(started)


async def summary_data(db: AsyncSession) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.monotonic()
    stocks, movements, material_count = await _load_views()
    data = await analytics.summary(stocks, movements, material_count, db)
    return data, _meta(started)


async def trend_data(days: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = time.monotonic()
    _, movements, _ = await _load_views()
    return analytics.movement_trend(movements, days), _meta(started)


async def distribution_data() -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.monotonic()
    stocks, _, _ = await _load_views()
    return analytics.stock_distribution(stocks), _meta(started)


async def low_stock_top_data(limit: int) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.monotonic()
    stocks, movements, _ = await _load_views()
    return analytics.low_stock_top(stocks, movements, limit), _meta(started)


async def todos_data(db: AsyncSession) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.monotonic()
    stocks, movements, _ = await _load_views()
    return await analytics.todos(stocks, movements, db), _meta(started)


# ── 报表族（T4）────────────────────────────────────────────────

async def monthly_report_data(year: int, month: int) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.monotonic()
    _, movements, _ = await _load_views()
    return analytics.monthly_report(movements, year, month), _meta(started)


async def annual_report_data(year: int) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.monotonic()
    _, movements, _ = await _load_views()
    return analytics.annual_report(movements, year), _meta(started)


async def turnover_data(days: int, limit: int, order: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = time.monotonic()
    stocks, movements, _ = await _load_views()
    return analytics.turnover_ranking(stocks, movements, days, limit, order), _meta(started)


async def consumption_data(days: int, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = time.monotonic()
    _, movements, _ = await _load_views()
    return analytics.consumption_ranking(movements, days, limit), _meta(started)


async def stock_report_data(page: int, page_size: int) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    started = time.monotonic()
    stocks, _, _ = await _load_views()
    rows, total = analytics.stock_report_rows(stocks, page, page_size)
    return rows, total, _meta(started)


async def batch_trace_data(material_code: str, batch_no: str) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.monotonic()
    _, movements, _ = await _load_views()
    return analytics.batch_trace(movements, material_code, batch_no), _meta(started)
