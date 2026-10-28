"""遥测域只读工具：特种设备（锅炉等）最新读数与报警记录查询。

数据源为本地库遥测快照/报警表（telemetry/query.py），纯只读。
按需挂载（telemetry 域命中时挂），不进常驻集。
"""

from __future__ import annotations

import logging
from datetime import date as _date
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic_ai import RunContext

from app.modules.safety.business_agent.schemas import SafetyDeps

if TYPE_CHECKING:
    from app.modules.safety.models import TelemetryAlarmRecord

logger = logging.getLogger(__name__)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


async def query_telemetry_latest(
    ctx: RunContext[SafetyDeps],
    equipment_no: str = "",
) -> dict[str, Any]:
    """查询特种设备遥测最新读数（锅炉等设备，每设备每指标最新一条）。

    返回设备号/指标/数值/单位/采集时间/越界状态（normal 正常、warning 预警、
    alarm 报警，按当前生效阈值规则对最新单点着色）。

    Args:
        equipment_no: 设备号（如 GL-01；不传返回全部设备）

    示例：锅炉现在压力多少；锅炉最新读数报一下；所有设备最新遥测。
    """
    from app.modules.safety.telemetry.query import latest_values

    try:
        items = await latest_values(ctx.deps.db, equipment_no=equipment_no or None)
        return {
            "success": True,
            "items": [
                {
                    "equipment_no": it["equipment_no"],
                    "metric": it["metric"],
                    "value": float(it["value"]),
                    "unit": it["unit"],
                    "recorded_at": _iso(it["recorded_at"]),
                    "parse_method": it["parse_method"],
                    "status": it["status"],
                }
                for it in items
            ],
            "total": len(items),
            "source": "db",
        }
    except Exception as e:
        logger.exception("query_telemetry_latest failed")
        return {"success": False, "error": f"查询失败: {e}"}


def _alarm_item(r: TelemetryAlarmRecord) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "equipment_no": r.equipment_no,
        "metric": r.metric,
        "value": float(r.value) if r.value is not None else None,
        "recorded_at": _iso(r.recorded_at),
        "rule_desc": r.rule_desc,
        "level": r.level,
        "status": r.status,
        "acked_at": _iso(r.acked_at),
        "acked_by": r.acked_by,
        "resolved_at": _iso(r.resolved_at),
        "resolution_note": r.resolution_note,
        "created_at": _iso(r.created_at),
    }


async def query_telemetry_alarms(
    ctx: RunContext[SafetyDeps],
    equipment_no: str = "",
    status: str = "",
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """查询特种设备遥测报警记录（锅炉等设备阈值报警，含处置状态）。

    Args:
        equipment_no: 设备号（可选）
        status: 报警状态——firing=报警中 / acked=已确认 / resolved=已解决（可选）
        date_from / date_to: 起止日期（ISO，按报警发生时间，含当日，可选）
        page / page_size: 页码（默认 1）/每页条数（默认 20，最大 100）

    示例：锅炉昨天有没有报警；有哪些未处理的报警（status=firing）。
    """
    from app.modules.safety.telemetry.query import list_alarms

    try:
        page_size = min(max(page_size, 1), 100)
        rows, total = await list_alarms(
            ctx.deps.db,
            status=status or None,
            equipment_no=equipment_no or None,
            date_from=_date.fromisoformat(date_from) if date_from else None,
            date_to=_date.fromisoformat(date_to) if date_to else None,
            page=page,
            page_size=page_size,
        )
        return {
            "success": True,
            "items": [_alarm_item(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "source": "db",
        }
    except Exception as e:
        logger.exception("query_telemetry_alarms failed")
        return {"success": False, "error": f"查询失败: {e}"}
