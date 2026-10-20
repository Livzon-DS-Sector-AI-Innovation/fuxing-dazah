"""三台账页面数据（三态信封，照 domain_pages 口径）。

- not_connected：该台账连接未登记（BitableConfigError）——一期常态；
- live：直读出数（summary + 标准字段分页行，锚点升序 NULLS LAST）；
- degraded：连接有效但读取异常（errors 标注，整页仍 200）。
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.modules.safety.facilities.ledger import (
    BIZ_LABELS,
    URL_TO_BIZ,
    LedgerRowView,
    LedgerSummary,
)
from app.modules.safety.facilities.reader import (
    CachedLedgerReader,
    FacilitiesLedgerReader,
    open_reader,
)
from app.modules.safety.service.bitable_direct.errors import BitableConfigError

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def _bj_today() -> date:
    """北京时间今天（与 domain_pages/daily_digest 同口径）。"""
    return (datetime.now(UTC) + timedelta(hours=8)).date()


def row_dict(v: LedgerRowView, today: date) -> dict[str, Any]:
    """视图 → API 行（日期 ISO 化 + 剩余天数派生）。"""
    anchor_days = (v.anchor - today).days if v.anchor else None
    return {
        "record_id": v.record_id,
        "biz_type": v.biz_type,
        "equipment_no": v.equipment_no,
        "name": v.name,
        "category": v.category,
        "location": v.location,
        "department": v.department,
        "owner": v.owner,
        "last_date": v.last_date.isoformat() if v.last_date else None,
        "cycle_months": v.cycle_months,
        "next_date": v.next_date.isoformat() if v.next_date else None,
        "anchor": v.anchor.isoformat() if v.anchor else None,
        "anchor_source": v.anchor_source,
        "status": v.status or None,
        "refill_due": v.refill_due.isoformat() if v.refill_due else None,
        "scrap_due": v.scrap_due.isoformat() if v.scrap_due else None,
        "register_code": v.register_code,
        "inspection_category": v.inspection_category,
        "agency": v.agency,
        "monitor_flag": v.monitor_flag,
        "active": v.active,
        "remaining_days": anchor_days,
        "incomplete_reason": v.incomplete_reason,
    }


async def build_ledger_page(
    url_key: str,
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    reader: CachedLedgerReader | FacilitiesLedgerReader | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """单台账页面数据（三态信封）。url_key=accessories/fire-equipment/special-equipment。"""
    biz_type = URL_TO_BIZ.get(url_key)
    if biz_type is None:
        raise ValueError(f"未知台账: {url_key}")
    reader = reader if reader is not None else open_reader()
    today = today or _bj_today()

    page = max(1, int(page))
    page_size = min(max(1, int(page_size)), MAX_PAGE_SIZE)

    def envelope(
        status: str,
        summary: dict[str, Any] | None,
        rows: list[dict[str, Any]],
        total: int,
        errors: list[str],
    ) -> dict[str, Any]:
        return {
            "status": status,
            "summary": summary,
            "ledger": {
                "data": rows,
                "meta": {"total": total, "page": page, "page_size": page_size},
            },
            "errors": errors,
        }

    try:
        views = await reader.fetch_ledger(biz_type, strict=False)
    except BitableConfigError:
        return envelope("not_connected", None, [], 0, [])
    except Exception as exc:  # noqa: BLE001 —— 读取失败=降级，不炸端点
        logger.warning(
            "facilities 台账读取降级 %s: %r", url_key, exc,
        )
        return envelope("degraded", None, [], 0, [f"{biz_type}: {type(exc).__name__}"])

    summary = LedgerSummary.build(views, today)
    ordered = sorted(views, key=lambda v: (v.anchor is None, v.anchor or date.max))
    rows = [row_dict(v, today) for v in ordered]
    start = (page - 1) * page_size
    return envelope(
        "live",
        {
            "biz_type": biz_type,
            "biz_label": BIZ_LABELS[biz_type],
            **{
                k: getattr(summary, k)
                for k in ("total", "active", "overdue", "due_30d", "incomplete")
            },
        },
        rows[start : start + page_size],
        len(rows),
        [],
    )
