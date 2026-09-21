"""成品侧 Base 数据读取层（V3.0 分期D，设计 §4.5 成品③ / §4.8 ④⑥）。

成品数据无本地镜像（2B：Base 权威），全部经 WarehouseBitableAdapter 直读：
- 分页拉取上限防御（每页 500 × 10 页，同 A 期清单拉取先例）；
- Bitable 日期范围过滤不支持（B 期实测 1254018），一律全量拉取后本地
  窗口过滤（行级表量级 <千行，安全）；
- 单元格解析一律走 bitable_cells（规范解析，禁手写 str 拼接）；数量兼容
  公式「0.6kg」带单位文本（前导数字提取）；日期兼容毫秒时间戳与 ISO 文本。

四态判定（§4.8⑥，行级、按销售日期归月）：
- 已开票已发货 = 出库>0 且 开票>0；发货未开票 = 出库>0 且 开票空/0；
- 开票未发货 = 开票>0 且 出库空/0；未开票未发货不推（无行动价值）。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.modules.warehouse.bitable_cells import cell_number, cell_text, unwrap

logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")

_PAGE_LIMIT = 500
_MAX_PAGES = 10  # 分页上限防御（>5000 行截断，同 A 期清单拉取）

# 待处理回看窗口（成品入库质量状态分布/待处理行的采集窗口）
RECENT_WINDOW_DAYS = 90

# 四态判定结果（§4.8⑥）
STATE_INVOICED_SHIPPED = "invoiced_shipped"  # 已开票已发货
STATE_SHIPPED_UNINVOICED = "shipped_uninvoiced"  # 发货未开票
STATE_INVOICED_UNSHIPPED = "invoiced_unshipped"  # 开票未发货

# 拉取字段白名单（records/search field_names；公式列可读不可写）
DAILY_SALES_FIELDS = [
    "销售日期", "产品名称", "品规", "销售客户", "出库量",
    "出库量-开票工作流使用", "开票数量", "开票时间",
]
RECEIPT_FIELDS = [
    "入库日期", "产品名称", "产品批号", "品规", "入库数量", "单位", "质量状态",
]
OUTBOUND_FIELDS = [
    "出库日期", "产品名称", "产品批号", "出库量", "单位", "销售客户", "用途",
]
RETURN_FIELDS = [
    "退货日期", "产品名称", "产品批号", "品规", "退货客户", "退货原因",
    "退货量", "单位", "处理确认日期",
]
UNQUALIFIED_FIELDS = [
    "登记日期", "产品名称", "产品批号", "品规", "产生数量", "单位",
    "产生原因", "处理确认日期",
]

# 「0.6kg」/「1,234.5十亿」前导数字提取（cell_number 对带单位文本返回 None）
_QTY_PREFIX_RE = re.compile(r"^-?\d[\d,]*(?:\.\d+)?")


def cell_date(value: Any) -> date | None:
    """单元格值 → 北京时间 date（毫秒时间戳/秒级时间戳/ISO 文本；空值 None）。"""
    scalar = unwrap(value)
    if scalar is None or isinstance(scalar, bool):
        return None
    if isinstance(scalar, (int, float)):
        ms = float(scalar)
        if ms <= 0:
            return None
        if ms < 1e11:  # 秒级（10 位）→ 升毫秒
            ms *= 1000
        return datetime.fromtimestamp(ms / 1000, tz=CN_TZ).date()
    text = str(scalar).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10].replace("/", "-"))
    except ValueError:
        return None


def cell_qty(value: Any) -> float | None:
    """数量解析：cell_number 优先；带单位公式文本取前导数字（「0.6kg」→ 0.6）。"""
    number = cell_number(value)
    if number is not None:
        return number
    text = cell_text(value).strip().replace(",", "")
    match = _QTY_PREFIX_RE.match(text)
    return float(match.group(0)) if match else None


async def fetch_all_records(
    adapter: Any,
    table_key: str,
    field_names: list[str],
) -> list[dict[str, Any]]:
    """分页全量拉取（每页 500 × 10 页防御，超出截断并告警）。

    返回原始 records（{"record_id", "fields"}）；解析由各读取函数按需做。
    """
    records: list[dict[str, Any]] = []
    page_token: str | None = None
    for _ in range(_MAX_PAGES):
        page = await adapter.search_records_page(
            table_key,
            filter_json=None,
            field_names=field_names,
            limit=_PAGE_LIMIT,
            page_token=page_token,
        )
        records.extend(page.get("records") or [])
        page_token = page.get("page_token")
        if not page_token:
            return records
    logger.warning("Base 拉取超分页上限截断（table=%s，已有 %d 行）", table_key, len(records))
    return records


# ── 每日销售汇总（开票四态 §4.8⑥）──


@dataclass(frozen=True)
class DailySalesRow:
    """每日销售汇总行（出库+开票同一行，工作流维护开票数量）。"""

    record_id: str
    sales_date: date | None
    product_name: str
    spec: str
    customer: str
    shipped_qty: float | None
    invoiced_qty: float | None


def _parse_daily_sales_row(raw: dict[str, Any]) -> DailySalesRow:
    fields = raw.get("fields") or {}
    # 出库量：优先公式数值版（出库量-开票工作流使用），回落「0.6kg」前导数字
    shipped = cell_qty(fields.get("出库量-开票工作流使用"))
    if shipped is None:
        shipped = cell_qty(fields.get("出库量"))
    return DailySalesRow(
        record_id=str(raw.get("record_id") or ""),
        sales_date=cell_date(fields.get("销售日期")),
        product_name=cell_text(fields.get("产品名称")),
        spec=cell_text(fields.get("品规")),
        customer=cell_text(fields.get("销售客户")),
        shipped_qty=shipped,
        invoiced_qty=cell_qty(fields.get("开票数量")),
    )


async def fetch_daily_sales(adapter: Any) -> list[DailySalesRow]:
    """全量拉取每日销售汇总并解析（量级 <千行，本地窗口过滤由调用方做）。"""
    rows = await fetch_all_records(adapter, "daily_sales_summary", DAILY_SALES_FIELDS)
    return [_parse_daily_sales_row(r) for r in rows]


def classify_invoice_state(
    shipped_qty: float | None, invoiced_qty: float | None
) -> str | None:
    """四态判定（行级）：None = 未开票未发货（不推送）。"""
    shipped = shipped_qty or 0.0
    invoiced = invoiced_qty or 0.0
    if shipped > 0 and invoiced > 0:
        return STATE_INVOICED_SHIPPED
    if shipped > 0:
        return STATE_SHIPPED_UNINVOICED
    if invoiced > 0:
        return STATE_INVOICED_UNSHIPPED
    return None


@dataclass(frozen=True)
class InvoiceFourStateSummary:
    """当月四态合计 + 发货未开票明细（按数量降序，调用方截断展示）。"""

    invoiced_shipped_count: int = 0
    invoiced_shipped_qty: float = 0.0
    shipped_uninvoiced_count: int = 0
    shipped_uninvoiced_qty: float = 0.0
    invoiced_unshipped_count: int = 0
    invoiced_unshipped_qty: float = 0.0
    unbilled_detail: list[DailySalesRow] = field(default_factory=list)


def summarize_invoice_states(
    rows: list[DailySalesRow], *, month_start: date, month_end: date
) -> InvoiceFourStateSummary:
    """按销售日期窗口（含头不含尾）聚合四态。"""
    invoiced_shipped_count = 0
    invoiced_shipped_qty = 0.0
    shipped_uninvoiced_count = 0
    shipped_uninvoiced_qty = 0.0
    invoiced_unshipped_count = 0
    invoiced_unshipped_qty = 0.0
    unbilled: list[DailySalesRow] = []
    for row in rows:
        if row.sales_date is None or not (month_start <= row.sales_date < month_end):
            continue
        state = classify_invoice_state(row.shipped_qty, row.invoiced_qty)
        if state == STATE_INVOICED_SHIPPED:
            invoiced_shipped_count += 1
            invoiced_shipped_qty += row.shipped_qty or 0.0
        elif state == STATE_SHIPPED_UNINVOICED:
            shipped_uninvoiced_count += 1
            shipped_uninvoiced_qty += row.shipped_qty or 0.0
            unbilled.append(row)
        elif state == STATE_INVOICED_UNSHIPPED:
            invoiced_unshipped_count += 1
            invoiced_unshipped_qty += row.invoiced_qty or 0.0
    unbilled.sort(key=lambda r: (r.shipped_qty or 0.0), reverse=True)
    return InvoiceFourStateSummary(
        invoiced_shipped_count=invoiced_shipped_count,
        invoiced_shipped_qty=invoiced_shipped_qty,
        shipped_uninvoiced_count=shipped_uninvoiced_count,
        shipped_uninvoiced_qty=shipped_uninvoiced_qty,
        invoiced_unshipped_count=invoiced_unshipped_count,
        invoiced_unshipped_qty=invoiced_unshipped_qty,
        unbilled_detail=unbilled,
    )


# ── 成品日出入库（§4.5 成品③ 每日汇总）──


@dataclass(frozen=True)
class DayMovements:
    """某业务日的成品入库/出库聚合（数量按产品名称小计降序）。"""

    inbound_count: int = 0
    inbound_qty: float = 0.0
    outbound_count: int = 0
    outbound_qty: float = 0.0
    inbound_by_product: list[tuple[str, float]] = field(default_factory=list)
    outbound_by_product: list[tuple[str, float]] = field(default_factory=list)


def _product_totals(rows: list[tuple[str | None, float | None]]) -> list[tuple[str, float]]:
    totals: dict[str, float] = {}
    for name, qty in rows:
        if qty is None:
            continue
        key = (name or "").strip() or "未填产品"
        totals[key] = totals.get(key, 0.0) + qty
    return sorted(totals.items(), key=lambda kv: kv[1], reverse=True)


def _on_date(value: date | None, day: date) -> bool:
    return value is not None and value == day


async def fetch_day_movements(adapter: Any, *, day: date) -> DayMovements:
    """某业务日的成品入库（finished_receipt）与出库（finished_outbound）聚合。"""
    inbound_count = 0
    inbound_qty = 0.0
    inbound_pairs: list[tuple[str | None, float | None]] = []
    for raw in await fetch_all_records(adapter, "finished_receipt", RECEIPT_FIELDS):
        fields = raw.get("fields") or {}
        if not _on_date(cell_date(fields.get("入库日期")), day):
            continue
        inbound_count += 1
        qty = cell_qty(fields.get("入库数量"))
        inbound_qty += qty or 0.0
        inbound_pairs.append((cell_text(fields.get("产品名称")), qty))

    outbound_count = 0
    outbound_qty = 0.0
    outbound_pairs: list[tuple[str | None, float | None]] = []
    for raw in await fetch_all_records(adapter, "finished_outbound", OUTBOUND_FIELDS):
        fields = raw.get("fields") or {}
        if not _on_date(cell_date(fields.get("出库日期")), day):
            continue
        outbound_count += 1
        qty = cell_qty(fields.get("出库量"))
        outbound_qty += qty or 0.0
        outbound_pairs.append((cell_text(fields.get("产品名称")), qty))

    return DayMovements(
        inbound_count=inbound_count,
        inbound_qty=inbound_qty,
        outbound_count=outbound_count,
        outbound_qty=outbound_qty,
        inbound_by_product=_product_totals(inbound_pairs),
        outbound_by_product=_product_totals(outbound_pairs),
    )


@dataclass(frozen=True)
class QualityDistribution:
    """近窗口入库行的质量状态分布（合格/待检/待处理/退货 + 未填）。"""

    counts: dict[str, int] = field(default_factory=dict)

    def get(self, status: str, default: int = 0) -> int:
        return self.counts.get(status, default)


async def fetch_quality_distribution(
    adapter: Any, *, since: date
) -> QualityDistribution:
    """近窗口（入库日期 >= since）成品入库行按质量状态计数（待处理清单来源之一）。"""
    counts: dict[str, int] = {}
    for raw in await fetch_all_records(adapter, "finished_receipt", RECEIPT_FIELDS):
        fields = raw.get("fields") or {}
        inbound_date = cell_date(fields.get("入库日期"))
        if inbound_date is None or inbound_date < since:
            continue
        status = cell_text(fields.get("质量状态")).strip() or "未填"
        counts[status] = counts.get(status, 0) + 1
    return QualityDistribution(counts=counts)


def month_bounds(year: int, month: int) -> tuple[date, date]:
    """自然月边界（北京时间，含头不含尾）。"""
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return date(year, month, 1), date(next_year, next_month, 1)


def recent_window_start(now_cn: datetime, days: int = RECENT_WINDOW_DAYS) -> date:
    """近窗口起点（含当天往前 days 天）。"""
    return (now_cn - timedelta(days=days)).date()


# ── 成品出库行级（§4.5 年报成品部分 / §4.8⑤ 发货分析共用）──


@dataclass(frozen=True)
class FinishedOutboundRow:
    """成品出库台账行（出库量 type 2 可读；品规/质量状态为公式只读）。"""

    record_id: str
    outbound_date: date | None
    product_name: str
    spec: str
    batch_no: str
    qty: float | None
    unit: str
    customer: str
    purpose: str


def _parse_outbound_row(raw: dict[str, Any]) -> FinishedOutboundRow:
    fields = raw.get("fields") or {}
    return FinishedOutboundRow(
        record_id=str(raw.get("record_id") or ""),
        outbound_date=cell_date(fields.get("出库日期")),
        product_name=cell_text(fields.get("产品名称")),
        spec=cell_text(fields.get("品规")),
        batch_no=cell_text(fields.get("产品批号")),
        qty=cell_qty(fields.get("出库量")),
        unit=cell_text(fields.get("单位")),
        customer=cell_text(fields.get("销售客户")),
        purpose=cell_text(fields.get("用途")),
    )


async def fetch_finished_outbound_rows(adapter: Any) -> list[FinishedOutboundRow]:
    """全量拉取成品出库台账行（日期窗口过滤由调用方本地做）。"""
    rows = await fetch_all_records(adapter, "finished_outbound", OUTBOUND_FIELDS)
    return [_parse_outbound_row(r) for r in rows]


@dataclass(frozen=True)
class CustomerShipment:
    """某客户窗口期发货聚合（§4.8⑤ 发货去向分析）。"""

    customer: str
    total_qty: float = 0.0
    order_count: int = 0
    product_totals: list[tuple[str, float]] = field(default_factory=list)


def summarize_shipments(
    rows: list[FinishedOutboundRow], *, start: date, end: date, purpose: str = "销售"
) -> list[CustomerShipment]:
    """按客户聚合窗口期（含头不含尾）销售发货，数量降序、客户内品名 Top5。"""
    by_customer: dict[str, dict[str, float]] = {}
    counts: dict[str, int] = {}
    for row in rows:
        if row.purpose != purpose:
            continue
        if row.outbound_date is None or not (start <= row.outbound_date < end):
            continue
        customer = row.customer.strip() or "未填客户"
        product = row.product_name or "未填产品"
        qty = row.qty or 0.0
        products = by_customer.setdefault(customer, {})
        products[product] = products.get(product, 0.0) + qty
        counts[customer] = counts.get(customer, 0) + 1
    result = [
        CustomerShipment(
            customer=customer,
            total_qty=sum(by_product.values()),
            order_count=counts[customer],
            product_totals=sorted(
                by_product.items(), key=lambda kv: kv[1], reverse=True
            )[:5],
        )
        for customer, by_product in by_customer.items()
    ]
    result.sort(key=lambda c: c.total_qty, reverse=True)
    return result


# ── 成品退货/不合格待处理（§4.8④ 清单 + 处理方案确认门）──

SOURCE_RETURNS = "returns"
SOURCE_UNQUALIFIED = "unqualified"


@dataclass(frozen=True)
class FinishedPendingRow:
    """退货/不合格待处理行（处理确认日期为空 = 待跟进）。"""

    source: str  # SOURCE_RETURNS | SOURCE_UNQUALIFIED
    record_id: str
    occurred_date: date | None  # 退货日期 / 登记日期
    product_name: str
    spec: str
    batch_no: str
    qty: float | None  # 退货量 / 产生数量
    unit: str
    customer: str  # 退货客户 / 空
    reason: str  # 退货原因 / 产生原因


def _pending_disposition_row(
    source: str, raw: dict[str, Any], *, date_field: str, qty_field: str
) -> FinishedPendingRow:
    fields = raw.get("fields") or {}
    return FinishedPendingRow(
        source=source,
        record_id=str(raw.get("record_id") or ""),
        occurred_date=cell_date(fields.get(date_field)),
        product_name=cell_text(fields.get("产品名称")),
        spec=cell_text(fields.get("品规")),
        batch_no=cell_text(fields.get("产品批号")),
        qty=cell_qty(fields.get(qty_field)),
        unit=cell_text(fields.get("单位")),
        customer=cell_text(fields.get("退货客户")) if source == SOURCE_RETURNS else "",
        reason=cell_text(
            fields.get("退货原因" if source == SOURCE_RETURNS else "产生原因")
        ),
    )


async def fetch_pending_dispositions(adapter: Any) -> list[FinishedPendingRow]:
    """退货/不合格两张表的待处理行（处理确认日期为空），退货在前。

    待处理 = 「处理确认日期」（D 期 API 建列）为空——处理进度为公式列只读，
    确认门回写走新列（1C：确认动作=回写 Base 字段）。
    """
    pending: list[FinishedPendingRow] = []
    for raw in await fetch_all_records(adapter, "finished_returns", RETURN_FIELDS):
        fields = raw.get("fields") or {}
        if cell_text(fields.get("处理确认日期")).strip():
            continue
        pending.append(
            _pending_disposition_row(
                SOURCE_RETURNS, raw, date_field="退货日期", qty_field="退货量"
            )
        )
    for raw in await fetch_all_records(adapter, "finished_unqualified", UNQUALIFIED_FIELDS):
        fields = raw.get("fields") or {}
        if cell_text(fields.get("处理确认日期")).strip():
            continue
        pending.append(
            _pending_disposition_row(
                SOURCE_UNQUALIFIED, raw, date_field="登记日期", qty_field="产生数量"
            )
        )
    return pending
