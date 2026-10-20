"""报警卡片按钮回调（facilities-p2 票 04，scope=telemetry_alarm）。

路由接点：business_agent_bot_handler.handle_card_action 按 payload.scope
分发到本模块 handle_telemetry_card_action（照 progress_card / urs_card 模式）。

按钮语义：「值班确认（本轮全部）」→ ack 本轮全部 firing（幂等：已确认的
跳过不报错——at-least-once 重推容忍）；处置说明（resolve）须填文本，
卡片不收表单，指引到 Web 监控子区操作（拍板口径：卡片按钮只做确认）。
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def handle_telemetry_card_action(
    payload: dict[str, Any], event_data: dict[str, Any]
) -> dict[str, None] | None:
    """遥测报警卡按钮回调。返回飞书 ACK（toast）。"""
    action = payload.get("action")
    operator = (event_data.get("operator") or {}).get("open_id") or "card_user"

    if action == "ack_all":
        alarm_ids = payload.get("alarm_ids") or []
        if not isinstance(alarm_ids, list) or not alarm_ids:
            return {"toast": {"type": "error", "content": "回调缺少报警 ID"}}
        acked, skipped, missing = await _ack_many(alarm_ids, operator=operator)
        logger.info(
            "遥测报警卡值班确认: operator=%s acked=%d skipped=%d missing=%d",
            operator, acked, skipped, missing,
        )
        if acked == 0 and skipped == 0:
            return {"toast": {"type": "error", "content": "报警不存在或已处理"}}
        # 回贴卡片：按钮区原地替换为「已确认」状态（快路径返回 raw card，
        # 飞书在 ACK 帧中直接渲染，不走后台 PATCH）
        total = acked + skipped
        confirmed_md = (
            f"✅ 本轮 {total} 条报警已由值班人员确认接手"
            f"（其中此前已确认 {skipped} 条）。\n"
            "处置说明请到「安全管理 → 设备设施管理 → 特种设备 → 监控」填写闭环。"
        )
        confirmed_card = {
            "schema": "2.0",
            "header": {
                "title": {"tag": "plain_text", "content": "特种设备监控报警（已确认）"},
                "template": "orange",
            },
            "body": {
                "elements": [{
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": confirmed_md},
                }],
            },
        }
        return {
            "toast": {
                "type": "success",
                "content": f"已确认 {total} 条；处置说明请到 Web 监控页填写闭环",
            },
            "card": {"type": "raw", "data": json.dumps(confirmed_card, ensure_ascii=False)},
        }

    logger.warning("遥测报警卡未知动作: %s", action)
    return None


async def _ack_many(alarm_ids: list[str], *, operator: str) -> tuple[int, int, int]:
    """批量 ack（独立事务；返回 (本次确认, 已确认跳过, 不存在)。"""
    import uuid as _uuid

    from app.core.database import async_session_factory
    from app.modules.safety.models import ALARM_STATUS_FIRING, TelemetryAlarmRecord
    from app.modules.safety.telemetry.lifecycle import ack_alarm, AlarmStateError

    acked = skipped = missing = 0
    async with async_session_factory() as session:
        for raw_id in alarm_ids:
            try:
                alarm_id = _uuid.UUID(str(raw_id))
            except (ValueError, TypeError):
                missing += 1
                continue
            alarm = await session.get(TelemetryAlarmRecord, alarm_id)
            if alarm is None or alarm.is_deleted:
                missing += 1
                continue
            if alarm.status != ALARM_STATUS_FIRING:
                skipped += 1
                continue
            try:
                await ack_alarm(session, alarm, operator=operator)
                acked += 1
            except AlarmStateError:
                skipped += 1
        await session.commit()
    return acked, skipped, missing
