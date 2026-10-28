"""设施管理域只读工具：三台账 / 校验任务 / 灭火器点检查询。

数据源：三台账与点检表为飞书 bitable 直读（台账走 300s TTL 缓存
reader），校验任务为本地库。全部纯只读、按需挂载（facilities 域
命中时挂），不进常驻集。
"""

from __future__ import annotations

import logging
from datetime import date as _date
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from pydantic_ai import RunContext

from app.modules.safety.business_agent.schemas import SafetyDeps

if TYPE_CHECKING:
    from app.modules.safety.facilities.ledger import LedgerRowView
    from app.modules.safety.fire_inspection.models import InspectionRecord

logger = logging.getLogger(__name__)

_BJ_TZ = timezone(timedelta(hours=8))

# ledger 参数别名（code / 中文）→ biz_type
_BIZ_ALIASES: dict[str, str] = {
    "fire_equipment": "fire_equipment",
    "fire": "fire_equipment",
    "灭火器": "fire_equipment",
    "消防器材": "fire_equipment",
    "accessory": "accessory",
    "安全附件": "accessory",
    "附件": "accessory",
    "special_equipment": "special_equipment",
    "special": "special_equipment",
    "特种设备": "special_equipment",
    "特种": "special_equipment",
}

_BIZ_LABELS = {
    "fire_equipment": "消防器材（灭火器）",
    "accessory": "安全附件",
    "special_equipment": "特种设备",
}


def _bj_today() -> _date:
    return datetime.now(_BJ_TZ).date()


def _norm_ledger(raw: str) -> str | None:
    """ledger 参数（code/中文/all/空）→ biz_type；空与 all 返回 None（=全部）。"""
    key = raw.strip()
    if key in ("", "all"):
        return None
    return _BIZ_ALIASES.get(key) or _BIZ_ALIASES.get(key.lower())


def _paginate(rows: list[Any], page: int, page_size: int) -> list[Any]:
    page_size = min(max(page_size, 1), 100)
    start = max(page, 1) - 1
    return rows[start * page_size : start * page_size + page_size]


# ── 台账查询 ────────────────────────────────────────────────────


def _ledger_item(v: LedgerRowView, today: _date, url_prefix: str | None) -> dict[str, Any]:
    anchor = v.anchor
    return {
        "record_id": v.record_id,
        "ledger": v.biz_type,
        "equipment_no": v.equipment_no,
        "name": v.name,
        "category": v.category,
        "location": v.location,
        "department": v.department,
        "owner": v.owner,
        "status": v.status or "在用",
        "active": v.active,
        "last_date": v.last_date.isoformat() if v.last_date else None,
        "next_date": v.next_date.isoformat() if v.next_date else None,
        "anchor": anchor.isoformat() if anchor else None,
        "remaining_days": (anchor - today).days if anchor else None,
        "refill_due": v.refill_due.isoformat() if v.refill_due else None,
        "scrap_due": v.scrap_due.isoformat() if v.scrap_due else None,
        "register_code": v.register_code,
        "incomplete_reason": v.incomplete_reason,
        "record_url": f"{url_prefix}{v.record_id}" if url_prefix else None,
    }


def _due_predicate(due: str, today: _date):
    """due 参数 → (days, include_overdue)。soon[:N]=未来 N 天内（不含已到期），
    overdue=已到期。口径与台账页 summary 一致：只统计在用行。"""
    if due == "overdue":
        return lambda v: v.active and v.anchor is not None and v.anchor < today
    if due.startswith("soon"):
        days = 30
        if ":" in due:
            try:
                days = int(due.split(":", 1)[1])
            except ValueError:
                return None
        return lambda v: (
            v.active and v.anchor is not None and 0 <= (v.anchor - today).days <= days
        )
    return None


async def query_facility_ledgers(
    ctx: RunContext[SafetyDeps],
    ledger: str = "all",
    department: str = "",
    status: str = "",
    due: str = "",
    keyword: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """查询安全设备设施三台账（灭火器/消防器材、安全附件、特种设备）。

    支持按台账类型、部门、状态、到期窗口、关键词过滤；到期窗口口径与
    台账页一致（在用行的校验锚点）：due=overdue 已到期 / soon 未来 30 天内 /
    soon:7 未来 7 天内（不含已到期）。summary 为过滤前的全量统计。

    Args:
        ledger: 台账类型——fire_equipment/灭火器、accessory/安全附件、
            special_equipment/特种设备、all 全部（默认 all）
        department: 责任部门（模糊匹配）
        status: 设备状态（模糊匹配，如 在用/报废/停用；可选）
        due: 到期窗口——overdue=已到期、soon=未来30天内、soon:N=未来N天内（可选）
        keyword: 关键词（编号/名称/类别/位置模糊匹配，可选）
        page / page_size: 页码（默认 1）/每页条数（默认 20，最大 100）

    示例：灭火器有效期情况；有哪些安全附件快到期了；报废的特种设备还有几台。
    """
    from dataclasses import asdict

    from app.modules.safety.facilities import notify as fac_notify
    from app.modules.safety.facilities.ledger import (
        BIZ_ACCESSORY, BIZ_FIRE, BIZ_SPECIAL, LedgerSummary,
    )
    from app.modules.safety.facilities.reader import open_reader
    from app.modules.safety.service.bitable_direct.errors import BitableConfigError

    biz = _norm_ledger(ledger)
    if ledger.strip() not in ("", "all") and biz is None:
        return {
            "success": False,
            "error": (
                f"未知 ledger={ledger!r}，可选：fire_equipment/灭火器、"
                f"accessory/安全附件、special_equipment/特种设备、all"
            ),
        }
    pred = _due_predicate(due.strip(), _bj_today()) if due.strip() else None
    if due.strip() and pred is None:
        return {
            "success": False,
            "error": f"未知 due={due!r}，可选：overdue / soon / soon:N（N=天数）",
        }

    try:
        biz_types = [biz] if biz else [BIZ_FIRE, BIZ_ACCESSORY, BIZ_SPECIAL]
        reader = open_reader()
        today = _bj_today()
        items: list[dict[str, Any]] = []
        summary: dict[str, Any] = {}
        errors: list[str] = []
        for bt in biz_types:
            try:
                views = await reader.fetch_ledger(bt, strict=False)
            except BitableConfigError:
                errors.append(f"{_BIZ_LABELS[bt]}台账未接入")
                continue
            summary[bt] = {
                "label": _BIZ_LABELS[bt],
                **asdict(LedgerSummary.build(views, today)),
            }
            url_prefix = fac_notify.record_url_prefix(bt)
            rows = views
            if department:
                rows = [v for v in rows if department in (v.department or "")]
            if status:
                rows = [v for v in rows if status in (v.status or "")]
            if pred is not None:
                rows = [v for v in rows if pred(v)]
            if keyword:
                rows = [
                    v for v in rows
                    if keyword in (v.equipment_no or "")
                    or keyword in (v.name or "")
                    or keyword in (v.category or "")
                    or keyword in (v.location or "")
                ]
            rows.sort(key=lambda v: (v.anchor is None, v.anchor or today))
            items.extend(_ledger_item(v, today, url_prefix) for v in rows)
        if errors and not items and not summary:
            return {
                "success": True, "status": "not_connected",
                "items": [], "total": 0, "errors": errors, "source": "bitable",
            }
        return {
            "success": True,
            "status": "live",
            "items": _paginate(items, page, page_size),
            "total": len(items),
            "summary": summary,
            "errors": errors,
            "source": "bitable",
        }
    except Exception as e:
        logger.exception("query_facility_ledgers failed")
        return {"success": False, "error": f"查询失败: {e}"}


# ── 校验任务查询 ─────────────────────────────────────────────────


async def query_facility_tasks(
    ctx: RunContext[SafetyDeps],
    status: str = "",
    department: str = "",
    ledger: str = "",
    group_key: str = "",
    overdue: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """查询设施校验任务（三台账派发的检查/校验/定期检验任务闭环）。

    Args:
        status: 任务状态——issued=进行中 / closed=已闭环 / cancelled=已取消（可选）
        department: 部门（精确匹配，可选）
        ledger: 台账类型——fire_equipment/灭火器、accessory/安全附件、
            special_equipment/特种设备（可选）
        group_key: 批次组（同设备同性质任务分组，可选）
        overdue: 仅看已逾期任务（默认 false）
        page / page_size: 页码/每页条数（默认 20）

    Returns:
        {success, items, total, summary, source}——summary 为全局计数
        （total/open/closed/cancelled/overdue）。

    示例：校验任务还有哪些没完成；有哪些逾期的检查任务。
    """
    from app.modules.safety.facilities.query import list_tasks, task_summary

    try:
        biz = _norm_ledger(ledger)
        if ledger.strip() not in ("", "all") and biz is None:
            return {
                "success": False,
                "error": f"未知 ledger={ledger!r}，可选：fire_equipment/accessory/special_equipment/all",
            }
        items, total = await list_tasks(
            ctx.deps.db,
            status=status.strip().lower() or None,
            department=department or None,
            biz_type=biz,
            group_key=group_key or None,
            overdue=True if overdue else None,
            page=page,
            page_size=page_size,
        )
        summary_full = await task_summary(
            ctx.deps.db, biz_type=biz, department=department or None,
        )
        summary = {k: summary_full[k] for k in
                   ("total", "open", "closed", "cancelled", "overdue")}
        return {
            "success": True,
            "items": items,
            "total": total,
            "summary": summary,
            "source": "db",
        }
    except Exception as e:
        logger.exception("query_facility_tasks failed")
        return {"success": False, "error": f"查询失败: {e}"}


# ── 灭火器点检查询 ───────────────────────────────────────────────


def _inspection_item(r: InspectionRecord) -> dict[str, Any]:
    failed = [name for name, ok in r.checks if ok is not True]
    return {
        "record_id": r.record_id,
        "equipment_no": r.equipment_no,
        "inspector": r.inspector,
        "department": r.dept,
        "inspect_at": r.inspect_at.isoformat() if r.inspect_at else None,
        "result": r.result,
        "rectify_status": r.rectify_status,
        "abnormal_desc": r.abnormal_desc,
        "confirmed": r.confirmed,
        "check_failed": failed,
        "photo_count": len(r.overall_photos) + len(r.key_photos),
        "report_count": len(r.reports),
    }


async def query_facility_inspections(
    ctx: RunContext[SafetyDeps],
    equipment_no: str = "",
    department: str = "",
    result: str = "",
    rectify_status: str = "",
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """查询灭火器点检记录（飞书「灭火器点检」多维表格直读）。

    Args:
        equipment_no: 设备编号（模糊匹配，可选）
        department: 点检人部门（模糊匹配，可选）
        result: 点检结果（如 正常/异常，模糊匹配，可选）
        rectify_status: 整改状态（模糊匹配，可选）
        date_from / date_to: 起止日期（ISO，按点检时间，含当日，可选）
        page / page_size: 页码/每页条数（默认 20，最大 100）

    示例：MP-01 这台灭火器最近的点检记录；有哪些点检异常还没整改。
    """
    from app.modules.safety.fire_inspection.bitable import (
        fire_inspection_app_token,
        fire_inspection_table_id,
        load_tenant_token,
        search_records,
    )
    from app.modules.safety.fire_inspection.models import parse_record

    try:
        d_from = _date.fromisoformat(date_from) if date_from else None
        d_to = _date.fromisoformat(date_to) if date_to else None
        token = await load_tenant_token()
        raw = await search_records(
            token, fire_inspection_app_token(), fire_inspection_table_id()
        )
        records = [parse_record(r) for r in raw]
        if equipment_no:
            records = [r for r in records if equipment_no in (r.equipment_no or "")]
        if department:
            records = [r for r in records if department in (r.dept or "")]
        if result:
            records = [r for r in records if result in (r.result or "")]
        if rectify_status:
            records = [r for r in records
                       if rectify_status in (r.rectify_status or "")]
        if d_from or d_to:
            def _in_window(r: InspectionRecord) -> bool:
                if r.inspect_at is None:
                    return False
                day = r.inspect_at.astimezone(_BJ_TZ).date()
                if d_from and day < d_from:
                    return False
                if d_to and day > d_to:
                    return False
                return True
            records = [r for r in records if _in_window(r)]
        # 时间倒序（最新在前），无时间行垫底
        with_time = sorted(
            (r for r in records if r.inspect_at is not None),
            key=lambda r: r.inspect_at,
            reverse=True,
        )
        records = with_time + [r for r in records if r.inspect_at is None]
        return {
            "success": True,
            "items": [_inspection_item(r) for r in _paginate(records, page, page_size)],
            "total": len(records),
            "source": "bitable",
        }
    except Exception as e:
        logger.exception("query_facility_inspections failed")
        return {"success": False, "error": f"查询失败: {e}"}
