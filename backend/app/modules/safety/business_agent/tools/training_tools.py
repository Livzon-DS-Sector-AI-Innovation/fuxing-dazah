"""培训与行为管控域只读工具（entity 合一，与 query_oh 同构）。

四个查询面共用一个工具：violations=违章档案 / plans=培训计划与实施 /
demand_drafts=培训需求草案（本地库）/ retraining_due=复训到期窗口。
违章与培训主表为飞书 bitable 直读（复用 domain_pages 的读取与字段映射）。
纯只读、按需挂载（training 域命中时挂），不进常驻集。
"""

from __future__ import annotations

import logging
from datetime import date as _date
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic_ai import RunContext

from app.modules.safety.business_agent.schemas import SafetyDeps

logger = logging.getLogger(__name__)

_BJ_TZ = timezone(timedelta(hours=8))

_TRAINING_URL_KEY = "training-behavior"


def _bj_today() -> _date:
    return datetime.now(_BJ_TZ).date()


def _row_date(value: Any) -> _date | None:
    """映射行里的 isoformat 字符串（或 None）→ 北京日期。"""
    if not value:
        return None
    try:
        return _date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _multi_contains(row: dict[str, Any], key: str, needle: str) -> bool:
    """multi 字段（list[str]）转顿号串做 contains 匹配。"""
    value = row.get(key)
    if isinstance(value, list):
        return needle in "、".join(str(v) for v in value)
    return needle in str(value or "")


def _paginate(rows: list[dict[str, Any]], page: int, page_size: int) -> list[dict[str, Any]]:
    page_size = min(max(page_size, 1), 100)
    start = max(page, 1) - 1
    return rows[start * page_size : start * page_size + page_size]


async def query_training_behavior(
    ctx: RunContext[SafetyDeps],
    entity: str,
    department: str = "",
    keyword: str = "",
    status: str = "",
    level: str = "",
    year: str = "",
    days: int = 30,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """查询培训与行为管控数据（entity 指定查什么）。

    Args:
        entity: violations=违章档案 / plans=培训计划与实施 /
            demand_drafts=培训需求草案 / retraining_due=复训到期
        department: 部门（violations/plans，模糊匹配）
        keyword: 关键词（violations 匹配违章描述/人员/备注；plans 匹配培训名称/备注）
        status: 状态（violations 如 纠正中/已纠正；plans 如 计划/已实施；
            demand_drafts 为 draft/adopted/rejected；模糊匹配）
        level: 违章等级（violations，如 一般/严重，可选）
        year: 年份（violations 按违章日期、demand_drafts 按草案年度；缺省全部）
        days: 复训到期窗口天数（retraining_due，默认 30，含已逾期）
        page / page_size: 页码/每页条数（默认 20）

    示例：谁有违章记录；生产部今年有哪些严重违章；培训计划完成情况；
    哪些人快到复训期了；2026 年有哪些培训需求草案待采纳。
    """
    try:
        if entity == "violations":
            return await _violations_impl(
                department=department, keyword=keyword, status=status,
                level=level, year=year, page=page, page_size=page_size,
            )
        if entity == "plans":
            return await _plans_impl(
                department=department, keyword=keyword, status=status,
                page=page, page_size=page_size,
            )
        if entity == "demand_drafts":
            return await _demand_drafts_impl(
                ctx, year=year, status=status, page=page, page_size=page_size,
            )
        if entity == "retraining_due":
            return await _retraining_due_impl(
                days=days, department=department, page=page, page_size=page_size,
            )
        return {
            "success": False,
            "error": (
                f"未知 entity={entity!r}，可选：violations / plans / "
                f"demand_drafts / retraining_due"
            ),
        }
    except Exception as e:
        logger.exception("query_training_behavior failed")
        return {"success": False, "error": f"查询失败: {e}"}


async def _violations_impl(
    *, department: str, keyword: str, status: str, level: str,
    year: str, page: int, page_size: int,
) -> dict[str, Any]:
    from app.modules.safety.service.domain_pages import fetch_kind_rows

    rows = await fetch_kind_rows(_TRAINING_URL_KEY, "violation")
    if rows is None:
        return {
            "success": True, "status": "not_connected",
            "items": [], "total": 0, "source": "bitable",
        }
    if department:
        rows = [r for r in rows if _multi_contains(r, "department", department)]
    if status:
        rows = [r for r in rows if status in (r.get("status") or "")]
    if level:
        rows = [r for r in rows if level in (r.get("level") or "")]
    if year:
        rows = [
            r for r in rows
            if (r.get("occurred_at") or "").startswith(year)
        ]
    if keyword:
        rows = [
            r for r in rows
            if keyword in (r.get("description") or "")
            or keyword in (r.get("person_name") or "")
            or keyword in (r.get("note") or "")
        ]
    rows.sort(key=lambda r: r.get("occurred_at") or "", reverse=True)
    return {
        "success": True, "status": "live",
        "items": _paginate(rows, page, page_size),
        "total": len(rows), "source": "bitable",
    }


async def _plans_impl(
    *, department: str, keyword: str, status: str,
    page: int, page_size: int,
) -> dict[str, Any]:
    from app.modules.safety.service.domain_pages import fetch_kind_rows

    rows = await fetch_kind_rows(_TRAINING_URL_KEY, "training")
    if rows is None:
        return {
            "success": True, "status": "not_connected",
            "items": [], "total": 0, "source": "bitable",
        }
    if department:
        rows = [r for r in rows if _multi_contains(r, "department", department)]
    if status:
        rows = [r for r in rows if status in (r.get("status") or "")]
    if keyword:
        rows = [
            r for r in rows
            if keyword in (r.get("name") or "") or keyword in (r.get("note") or "")
        ]
    rows.sort(key=lambda r: r.get("planned_at") or "", reverse=True)
    return {
        "success": True, "status": "live",
        "items": _paginate(rows, page, page_size),
        "total": len(rows), "source": "bitable",
    }


async def _demand_drafts_impl(
    ctx: RunContext[SafetyDeps], *, year: str, status: str,
    page: int, page_size: int,
) -> dict[str, Any]:
    from app.modules.safety.service.training_behavior.demand import list_drafts

    try:
        rows = await list_drafts(
            ctx.deps.db,
            year=int(year) if year else None,
            status=status.strip().lower() or None,
        )
    except ValueError as e:  # list_drafts 对非法 status 抛 DemandStateError(ValueError 子类)
        return {"success": False, "error": f"status 非法: {e}"}
    return {
        "success": True,
        "items": _paginate(rows, page, page_size),
        "total": len(rows), "source": "db",
    }


async def _retraining_due_impl(
    *, days: int, department: str, page: int, page_size: int,
) -> dict[str, Any]:
    """复训到期窗口（口径同 retraining_due 调度轮：已取消排除、无日期跳过、
    窗口含已逾期、按到期升序=最急在前；天数参数化默认 30）。"""
    from app.modules.safety.service.domain_pages import fetch_kind_rows

    rows = await fetch_kind_rows(_TRAINING_URL_KEY, "training")
    if rows is None:
        return {
            "success": True, "status": "not_connected",
            "items": [], "total": 0, "overdue_count": 0, "source": "bitable",
        }
    today = _bj_today()
    hits: list[dict[str, Any]] = []
    for r in rows:
        if (r.get("status") or "") == "已取消":
            continue
        due = _row_date(r.get("next_retraining_at"))
        if due is None:
            continue
        remaining = (due - today).days
        if remaining > days:
            continue  # 窗口外；逾期为负数天然命中
        if department and not _multi_contains(r, "department", department):
            continue
        hits.append({
            "name": r.get("name") or "（未命名培训）",
            "due": due.isoformat(),
            "remaining_days": remaining,
            "overdue": remaining < 0,
            "department": r.get("department"),
            "status": r.get("status"),
        })
    hits.sort(key=lambda h: h["remaining_days"])
    return {
        "success": True, "status": "live",
        "items": _paginate(hits, page, page_size),
        "total": len(hits),
        "overdue_count": sum(1 for h in hits if h["overdue"]),
        "days": days, "source": "bitable",
    }
