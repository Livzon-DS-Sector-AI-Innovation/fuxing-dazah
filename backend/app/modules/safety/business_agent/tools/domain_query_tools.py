"""三小域只读工具：外来人员保险预警 / 驾驶舱总览 / 危化品库存趋势。

三个低频聚合面合一文件（每域单工具）；数据源分别为 bitable 直读
预警链（report.build_warning_result 只读段）、总览聚合引擎
（overview.build_overview）、危化品快照趋势（chemical_inventory.trend）。
纯只读、按需挂载，不进常驻集。
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import RunContext

from app.modules.safety.business_agent.schemas import SafetyDeps

logger = logging.getLogger(__name__)


# ── 外来人员保险预警 ─────────────────────────────────────────────


def _expiring_item(g: Any) -> dict[str, Any]:
    return {
        "company": g.company,
        "names": g.names,
        "people": g.people,
        "work_content": g.work_content,
        "work_scope": g.work_scope,
        "entry_end": g.entry_end.isoformat() if g.entry_end else None,
        "insurance_end": g.insurance_end.isoformat() if g.insurance_end else None,
        "days_left": g.days_left,
    }


def _missing_item(g: Any) -> dict[str, Any]:
    return {
        "company": g.company,
        "notices": g.notices,
        "people": g.people,
        "latest_entry_end": (
            g.latest_entry_end.isoformat() if g.latest_entry_end else None
        ),
        "work_contents": g.work_contents,
    }


async def query_visitor_insurance(
    ctx: RunContext[SafetyDeps],
    category: str = "all",
) -> dict[str, Any]:
    """查询外来人员保险到期预警（预报备审批表直读，三类口径）。

    三类分组：expired=保险已过期（在厂）、soon=3 天内到期、
    missing=在厂但未填保险有效期；summary 含报备/在厂计数与最近到期。

    Args:
        category: expired=已过期 / soon=3天内到期 / missing=未填保险有效期 /
            all=全部（默认 all）

    示例：外来人员保险到期的有哪些；访客保险过期了没；哪些外包单位没填保险。
    """
    from app.modules.safety.service.visitor_insurance import report as vi_report
    from app.modules.safety.service.bitable_direct.errors import BitableConfigError

    cat = category.strip().lower() or "all"
    if cat not in ("all", "expired", "soon", "missing"):
        return {
            "success": False,
            "error": f"未知 category={category!r}，可选：expired / soon / missing / all",
        }
    try:
        result = await vi_report.build_warning_result()
        return {
            "success": True,
            "today": result.today.isoformat(),
            "summary": {
                "total_notices": result.total_notices,
                "active_notices": result.active_notices,
                "next_expiry": (
                    result.next_expiry.isoformat() if result.next_expiry else None
                ),
                "next_expiry_company": result.next_expiry_company or None,
            },
            "expired": [_expiring_item(g) for g in result.expired]
            if cat in ("all", "expired") else [],
            "soon": [_expiring_item(g) for g in result.soon]
            if cat in ("all", "soon") else [],
            "missing": [_missing_item(g) for g in result.missing]
            if cat in ("all", "missing") else [],
            "source": "bitable",
        }
    except BitableConfigError:
        return {
            "success": True, "status": "not_connected",
            "summary": None, "source": "bitable",
        }
    except Exception as e:
        logger.exception("query_visitor_insurance failed")
        return {"success": False, "error": f"查询失败: {e}"}


# ── 驾驶舱总览聚合 ───────────────────────────────────────────────


def _trim_overview(payload: dict[str, Any]) -> dict[str, Any]:
    """build_overview 输出 → agent 工具返回（digest 降为计数+标题，
    generated_at 转 isoformat；KPI 域原样保留）。"""
    digest = payload.get("digest") or {}
    cells = digest.get("cells") or []
    titles = [
        f"{getattr(c, 'tag_text', '')}·{getattr(c, 'title', '')}".strip("·")
        for c in cells
    ]
    generated_at = payload.get("generated_at")
    return {
        "date": payload.get("date"),
        "generated_at": (
            generated_at.isoformat() if hasattr(generated_at, "isoformat")
            else generated_at
        ),
        "hazards": payload.get("hazards"),
        "special_ops": payload.get("special_ops"),
        "alarms": payload.get("alarms"),
        "certs": payload.get("certs"),
        "chemicals": payload.get("chemicals"),
        "key_risk_ops": payload.get("key_risk_ops"),
        "ehs": payload.get("ehs"),
        "facility_tasks": payload.get("facility_tasks"),
        "digest": {"count": digest.get("count", len(cells)), "titles": titles},
        "module_health": payload.get("module_health"),
        "errors": payload.get("errors"),
    }


async def query_overview(ctx: RunContext[SafetyDeps]) -> dict[str, Any]:
    """查询今日安全总览（驾驶舱聚合：隐患/特殊作业/消防与中控报警/持证/
    危化品/关键作业/EHS变更/设施校验任务等 KPI 与模块健康度）。

    适合「今天整体安全状况怎么样」这类全局问题；单域细节请用对应域的
    查询工具。各域采集失败会降级为 None 并在 errors 标注。

    示例：今天安全状况怎么样；给我一个整体情况概况。
    """
    from app.modules.safety.service.overview import build_overview

    try:
        payload = await build_overview()
        return {"success": True, **_trim_overview(payload)}
    except Exception as e:
        logger.exception("query_overview failed")
        return {"success": False, "error": f"查询失败: {e}"}


# ── 危化品库存趋势 ───────────────────────────────────────────────


async def query_chemical_trend(
    ctx: RunContext[SafetyDeps],
    view: str = "trend_points",
    days: int = 30,
    target_date: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    """查询危化品库存趋势（每日快照：总量趋势点/物料异动/异动趋势）。

    Args:
        view: trend_points=每日总量与预警物料趋势点（默认）/
            material_changes=指定日期环比异动物料 / change_trend=每日异动统计
        days: 趋势窗口天数（trend_points/change_trend，默认 30）
        target_date: 异动基准日（ISO，material_changes；缺省=最近快照日）
        limit: 异动物料条数上限（material_changes，默认 50，最大 500）

    示例：危化品库存趋势怎么样；昨天有哪些物料异动；本月化学品环比变化。
    """
    from datetime import date as _date

    from app.modules.safety.chemical_inventory import trend as ci_trend

    try:
        if view == "trend_points":
            points = await ci_trend.daily_trend_points(ctx.deps.db, days=days)
            return {"success": True, "view": view, "days": days,
                    "points": points, "source": "db"}
        if view == "material_changes":
            changes = await ci_trend.material_changes(
                ctx.deps.db,
                target_date=_date.fromisoformat(target_date) if target_date else None,
                limit=max(1, min(limit, 500)),
            )
            return {"success": True, "view": view, **changes, "source": "db"}
        if view == "change_trend":
            trend = await ci_trend.change_trend(ctx.deps.db, days=days)
            return {"success": True, "view": view, "days": days,
                    "trend": trend, "source": "db"}
        return {
            "success": False,
            "error": (
                f"未知 view={view!r}，可选：trend_points / material_changes / "
                f"change_trend"
            ),
        }
    except Exception as e:
        logger.exception("query_chemical_trend failed")
        return {"success": False, "error": f"查询失败: {e}"}
