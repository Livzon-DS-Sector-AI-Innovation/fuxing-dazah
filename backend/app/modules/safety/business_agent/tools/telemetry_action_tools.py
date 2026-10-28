"""遥测域执行面（agent-action-p3）：特种设备报警处置闭环两件。

- ack_telemetry_alarm：值班确认（firing → acked，可批量；equipment_no 自动圈
  该设备全部 firing——与 telemetry/card.py ack_all 卡片按钮同源语义）
- resolve_telemetry_alarm：处置关闭（acked → resolved，处置说明必填）

工具体不重写业务逻辑：状态机复用 telemetry/lifecycle（ack_alarm/resolve_alarm/
get_alarm），批量圈定复用 telemetry/query.list_alarms。链路未启用（采集开关
SAFETY_TELEMETRY_POLL_ENABLED 关或源群 SAFETY_TELEMETRY_SOURCE_CHAT_ID 空，
agent-action-p3 拍板②）时优雅降级返回说明，不抛错、不触库。
写工具走既有确认流（TOOL_KIND=True → 挂起 → 确认卡 → executor.resume）。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from pydantic_ai import RunContext

from app.modules.safety.business_agent.schemas import SafetyDeps
from app.modules.safety.business_agent.tools.telemetry_tools import _alarm_item

logger = logging.getLogger(__name__)

__all__ = ["ack_telemetry_alarm", "resolve_telemetry_alarm"]

# equipment_no 圈定模式单次上限（与卡片 ack_all 一致量级；超出提示分批）
_ACK_BATCH_LIMIT = 100


def _link_disabled_reason() -> str | None:
    """锅炉遥测链路未启用判定：采集开关关或源群未配（拍板②：即降级）。"""
    from app.modules.safety.telemetry import collector, source

    if not collector.poll_enabled():
        return "锅炉遥测链路未启用（采集开关 SAFETY_TELEMETRY_POLL_ENABLED 未开启）"
    if not (source.source_chat_id() or "").strip():
        return "锅炉遥测链路未启用（源群 SAFETY_TELEMETRY_SOURCE_CHAT_ID 未配置）"
    return None


def _operator(ctx: RunContext[SafetyDeps]) -> str:
    person = ctx.deps.person
    if person is None:
        return "admin"
    return person.name or person.user_id or "admin"


def _ack_row(alarm: Any, result: str) -> dict[str, Any]:
    return {
        "id": str(alarm.id),
        "equipment_no": alarm.equipment_no,
        "metric": alarm.metric,
        "level": alarm.level,
        "status": alarm.status,
        "result": result,
    }


async def ack_telemetry_alarm(
    ctx: RunContext[SafetyDeps],
    alarm_ids: list[str] | None = None,
    equipment_no: str = "",
) -> dict[str, Any]:
    """值班确认特种设备遥测报警（firing → acked 留痕，可批量；写操作）。

    Args:
        alarm_ids: 报警记录 ID 列表（query_telemetry_alarms 返回的 id）
        equipment_no: 设备号（如 GL-01）——提供时自动确认该设备全部 firing 报警

    示例：锅炉 GL-01 的报警帮我确认一下；这几条报警确认掉。

    注意：此操作会变更报警状态（firing → acked）并留痕，需要用户确认后才执行；
    确认卡应先复述设备号、报警条数与每条概要（指标/级别），再等用户确认。
    """
    from app.modules.safety.telemetry import lifecycle
    from app.modules.safety.telemetry.query import list_alarms

    reason = _link_disabled_reason()
    if reason:
        return {"success": False, "action": "telemetry_alarm_ack", "message": reason}

    db = ctx.deps.db
    ids = [str(x).strip() for x in (alarm_ids or []) if str(x).strip()]
    equipment = (equipment_no or "").strip()
    if not ids and not equipment:
        return {
            "success": False,
            "action": "telemetry_alarm_ack",
            "message": "请提供 alarm_ids（query_telemetry_alarms 返回的记录 ID）或 equipment_no（设备号）至少一项",
        }

    operator = _operator(ctx)
    acked: list[dict] = []
    skipped: list[dict] = []
    missing: list[dict] = []
    truncated = 0

    if equipment:
        rows, total = await list_alarms(
            db, status="firing", equipment_no=equipment,
            page=1, page_size=_ACK_BATCH_LIMIT,
        )
        truncated = max(total - len(rows), 0)
        targets: list[tuple[str, Any]] = [(str(r.id), r) for r in rows]
        if not targets:
            return {
                "success": True,
                "action": "telemetry_alarm_ack",
                "acked": 0, "skipped": 0, "missing": 0, "truncated": 0,
                "items": [],
                "message": f"设备 {equipment} 当前没有 firing 报警，无需确认",
            }
    else:
        targets = [(x, None) for x in ids]

    for raw_id, alarm in targets:
        try:
            if alarm is None:
                alarm_id = uuid.UUID(raw_id)
            else:
                alarm_id = alarm.id
        except (ValueError, AttributeError, TypeError):
            missing.append({"id": raw_id, "result": "invalid_id"})
            continue
        if alarm is None:
            alarm = await lifecycle.get_alarm(db, alarm_id)
            if alarm is None:
                missing.append({"id": raw_id, "result": "not_found"})
                continue
        try:
            await lifecycle.ack_alarm(db, alarm, operator=operator)
        except lifecycle.AlarmStateError:
            skipped.append(_ack_row(alarm, "not_firing_skipped"))
            continue
        acked.append(_ack_row(alarm, "acked"))

    await db.commit()
    parts = [f"已确认 {len(acked)} 条"]
    if skipped:
        parts.append(f"跳过 {len(skipped)} 条（非 firing 状态）")
    if missing:
        parts.append(f"未找到 {len(missing)} 条")
    if truncated:
        parts.append(f"另有 {truncated} 条超出单次上限 {_ACK_BATCH_LIMIT}，可再次执行")
    return {
        "success": True,
        "action": "telemetry_alarm_ack",
        "operator": operator,
        "acked": len(acked),
        "skipped": len(skipped),
        "missing": len(missing),
        "truncated": truncated,
        "items": acked + skipped + missing,
        "message": "；".join(parts),
    }


async def resolve_telemetry_alarm(
    ctx: RunContext[SafetyDeps],
    alarm_id: str,
    note: str = "",
) -> dict[str, Any]:
    """处置关闭特种设备遥测报警（acked → resolved，处置说明必填；写操作）。

    状态机要求先值班确认（ack）再处置关闭；firing 报警会被拒绝并提示。

    Args:
        alarm_id: 报警记录 ID（query_telemetry_alarms 返回的 id）
        note: 处置说明（必填，如"已停炉检修，压力恢复正常"）

    示例：这条已确认的报警处置关闭，说明是更换了安全阀。

    注意：此操作会关闭报警并留处置结论，需要用户确认后才执行；确认卡应复述
    报警（设备/指标/级别/发生时间）与处置说明全文。
    """
    from app.modules.safety.telemetry import lifecycle

    reason = _link_disabled_reason()
    if reason:
        return {"success": False, "action": "telemetry_alarm_resolve", "message": reason}

    note = (note or "").strip()
    if not note:
        return {
            "success": False,
            "action": "telemetry_alarm_resolve",
            "message": "处置说明必填：请说明处置措施与结果（将留痕到报警记录）",
        }
    try:
        alarm_uuid = uuid.UUID(str(alarm_id).strip())
    except (ValueError, TypeError):
        return {
            "success": False,
            "action": "telemetry_alarm_resolve",
            "message": f"报警 ID 无效：{alarm_id!r}（应为 query_telemetry_alarms 返回的 UUID）",
        }

    db = ctx.deps.db
    alarm = await lifecycle.get_alarm(db, alarm_uuid)
    if alarm is None:
        return {
            "success": False,
            "action": "telemetry_alarm_resolve",
            "message": "报警不存在（可能已被删除）",
        }
    operator = _operator(ctx)
    try:
        await lifecycle.resolve_alarm(db, alarm, note=note, operator=operator)
    except lifecycle.AlarmStateError as e:
        return {
            "success": False,
            "action": "telemetry_alarm_resolve",
            "message": str(e),
        }
    await db.commit()
    return {
        "success": True,
        "action": "telemetry_alarm_resolve",
        "item": _alarm_item(alarm),
        "message": "报警已处置关闭，处置说明已留痕",
    }
