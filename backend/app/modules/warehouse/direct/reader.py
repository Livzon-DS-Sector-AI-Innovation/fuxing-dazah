"""直读 reader——经 WarehouseBitableAdapter 无上限分页全量拉 + 中文列解析。

沿用安全模块直读八坑经验：只走批量 search（禁逐条 get）、分页 page_token
放 query、MAX_PAGES 防御（超限抛错绝不静默截断——5000 行截断是
finished_data.fetch_all_records 的已知坑，这里不用它）。

日期兼容三形态（回灌实测）：数值毫秒 / 毫秒字符串（出库表 领用日期）/
ISO 文本。出库表无「代码」列——名称解析链在 movements 域（T2）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.modules.warehouse.bitable_adapter import (
    WarehouseBitableAdapter,
    WarehouseBitableError,
)
from app.modules.warehouse.bitable_cells import cell_number, cell_text
from app.modules.warehouse.direct.query import strip_spec_suffix
from app.modules.warehouse.direct.views import MaterialView, MovementView, StockView

logger = logging.getLogger(__name__)

MAX_PAGES = 100  # 500/页 × 100 = 5 万行防御上限，超限抛错
PAGE_SIZE = 500


async def fetch_all_pages(
    adapter: WarehouseBitableAdapter,
    table_key: str,
    field_names: list[str],
) -> list[dict[str, Any]]:
    """无上限分页全量拉（MAX_PAGES 防御；只请求所需列）。"""
    rows: list[dict[str, Any]] = []
    page_token: str | None = None
    for _ in range(MAX_PAGES):
        page = await adapter.search_records_page(
            table_key, field_names=field_names,
            limit=PAGE_SIZE, page_token=page_token,
        )
        rows.extend(page.get("records") or [])
        page_token = page.get("page_token")
        if not page_token:
            return rows
    raise WarehouseBitableError(
        f"Base 拉取超过 {MAX_PAGES} 页防御上限（table={table_key}，已有 {len(rows)} 行）",
        code="too_many_pages",
    )


def parse_datetime(value: Any) -> datetime | None:
    """Base 日期值 → UTC datetime（数值毫秒/毫秒字符串/ISO 文本兼容）。"""
    if value is None:
        return None
    n = cell_number(value)
    text = cell_text(value).strip()
    if not n and text.isdigit() and len(text) >= 10:
        n = int(text)
    if n:
        if n > 1e12:
            return datetime.fromtimestamp(n / 1000, tz=UTC)
        if n > 1e9:
            return datetime.fromtimestamp(n, tz=UTC)
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _status_of(qc_report: str, qa_release: str) -> str:
    """三态映射（base_mirror 语义：normal=合格/quarantine=待检/frozen=不合格）。

    「未放行/暂不放行」等否定词不得判为放行（in "放行" 会误命中）。
    """
    if "不合格" in qc_report:
        return "frozen"
    if qa_release and "放行" in qa_release and not any(
        neg in qa_release for neg in ("未", "不")
    ):
        return "normal"
    return "quarantine"


def _text_or_none(value: Any) -> str | None:
    """单选/文本 → 展示文本；空为 None（QC 三列直读口径）。"""
    text = cell_text(value).strip()
    return text or None


async def fetch_materials(
    adapter: WarehouseBitableAdapter | None = None,
) -> list[MaterialView]:
    """material_master 全量 → MaterialView（无代码或无名称的脏行跳过并计数）。"""
    adapter = adapter or WarehouseBitableAdapter()
    rows = await fetch_all_pages(
        adapter, "material_master",
        ["代码", "物料名称", "物料大类", "飞书规格"],
    )
    views: list[MaterialView] = []
    skipped = 0
    for raw in rows:
        f = raw.get("fields") or {}
        code = cell_text(f.get("代码")).strip()
        name = cell_text(f.get("物料名称")).strip()
        if not code or not name:
            skipped += 1
            continue
        views.append(MaterialView(
            record_id=str(raw.get("record_id") or ""),
            code=code, name=name,
            category_cn=cell_text(f.get("物料大类")).strip(),
            spec=cell_text(f.get("飞书规格")).strip(),
        ))
    if skipped:
        logger.info("material_master 直读跳过脏行 %d 行（无代码/无名称）", skipped)
    return views


async def fetch_stocks(
    adapter: WarehouseBitableAdapter | None = None,
) -> list[StockView]:
    """material_stock 全量 → StockView（QC 三列取 Base 真实列）。"""
    adapter = adapter or WarehouseBitableAdapter()
    rows = await fetch_all_pages(
        adapter, "material_stock",
        ["代码", "物料名称", "物料批号", "剩余数量", "单位",
         "有效期至/复验期至", "QC出报", "QC取样情况", "QA放行", "物料大类"],
    )
    views: list[StockView] = []
    skipped = 0
    for raw in rows:
        f = raw.get("fields") or {}
        code = cell_text(f.get("代码")).strip()
        name = cell_text(f.get("物料名称")).strip()
        if not code and not name:
            skipped += 1
            continue
        expiry = parse_datetime(f.get("有效期至/复验期至"))
        qc_report = _text_or_none(f.get("QC出报")) or ""
        qa_release = _text_or_none(f.get("QA放行")) or ""
        views.append(StockView(
            record_id=str(raw.get("record_id") or ""),
            code=code, name=name or code,
            batch_no=cell_text(f.get("物料批号")).strip(),
            quantity=round(cell_number(f.get("剩余数量")), 4),
            unit=cell_text(f.get("单位")).strip(),
            expiry_date=expiry.date() if expiry else None,
            status=_status_of(qc_report, qa_release),
            qc_sample_status=_text_or_none(f.get("QC取样情况")),
            qc_report_status=_text_or_none(f.get("QC出报")),
            qc_release_status=_text_or_none(f.get("QA放行")),
            category_cn=cell_text(f.get("物料大类")).strip(),
        ))
    if skipped:
        logger.info("material_stock 直读跳过全空脏行 %d 行", skipped)
    return views


async def fetch_movements(
    adapter: WarehouseBitableAdapter | None = None,
) -> list[MovementView]:
    """material_receipt + material_outbound 合流 → MovementView（按时间倒序）。

    出库表无「代码」列——名称链解析（精确 → 去尾部括号后缀 → 名称字段；
    解析不到 code 留空，展示用名称即可）。脏行（无名称/无数量/无日期）跳过。
    """
    adapter = adapter or WarehouseBitableAdapter()

    receipt_rows = await fetch_all_pages(
        adapter, "material_receipt",
        ["代码", "物料名称", "物料批号", "入库数量", "单位", "入库日期", "物料大类"],
    )
    outbound_rows = await fetch_all_pages(
        adapter, "material_outbound",
        ["物料名称", "名称", "物料批号", "出库数量", "单位", "领用日期", "物料大类"],
    )

    views: list[MovementView] = []
    skipped = 0
    for raw in receipt_rows:
        f = raw.get("fields") or {}
        name = cell_text(f.get("物料名称")).strip()
        qty = cell_number(f.get("入库数量"))
        when = parse_datetime(f.get("入库日期"))
        if not name or not qty or when is None:
            skipped += 1
            continue
        views.append(MovementView(
            record_id=str(raw.get("record_id") or ""),
            direction="inbound", source_type="purchase",
            code=cell_text(f.get("代码")).strip(),
            name=name,
            batch_no=cell_text(f.get("物料批号")).strip()[:100],
            quantity=round(qty, 4),
            unit=cell_text(f.get("单位")).strip()[:20],
            occurred_at=when,
            category_cn=cell_text(f.get("物料大类")).strip(),
        ))
    # 出库名称 → 代码 回填索引（精确 → 去后缀；不含 master，避免多拉一张表）
    name_index: dict[str, str] = {}
    for raw in receipt_rows:
        f = raw.get("fields") or {}
        code = cell_text(f.get("代码")).strip()
        name = cell_text(f.get("物料名称")).strip()
        if code and name:
            name_index.setdefault(name, code)
    for raw in outbound_rows:
        f = raw.get("fields") or {}
        name = cell_text(f.get("物料名称")).strip()
        qty = cell_number(f.get("出库数量"))
        when = parse_datetime(f.get("领用日期"))
        if not name or not qty or when is None:
            skipped += 1
            continue
        alt = cell_text(f.get("名称")).strip()
        code = (
            name_index.get(name)
            or name_index.get(strip_spec_suffix(name))
            or name_index.get(alt)
            or ""
        )
        views.append(MovementView(
            record_id=str(raw.get("record_id") or ""),
            direction="outbound", source_type="production",
            code=code, name=name,
            batch_no=cell_text(f.get("物料批号")).strip()[:100],
            quantity=round(qty, 4),
            unit=cell_text(f.get("单位")).strip()[:20],
            occurred_at=when,
            category_cn=cell_text(f.get("物料大类")).strip(),
        ))
    if skipped:
        logger.info("movements 直读跳过脏行 %d 行（无名称/数量/日期）", skipped)
    views.sort(key=lambda v: v.occurred_at, reverse=True)
    return views
