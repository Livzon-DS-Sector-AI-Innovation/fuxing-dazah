"""R3 event 失败直投 —— event_client 重试耗尽处直投 ingest_draft（二期③）。

范式同 rag_inject（源行仅归属载体 enabled 恒 false），但挂点在飞书事件
分发侧：handler 重试耗尽丢事件时投一条信号，与既有 1h 告警节流互不干扰
（告警链零改动红线）。全程 try/except——直投失败只记日志，绝不影响事件
分发自身。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.modules.safety.service.ops_selfheal_r3 import config, signals

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Shanghai")

#: 直投载体源行名
EVENT_SOURCE_NAME = "safety.ops.event_inject"


async def inject_event_failure_signal(
    *,
    event_type: str,
    handler_name: str,
    error_summary: str = "",
) -> bool:
    """事件处理重试耗尽直投一条 Trigger（每 handler 每日一单，聚 opsmisc 日常单）。

    Returns:
        是否新落一行（duplicate/开关关/源行缺失/异常=False；异常绝不上抛）。
    """
    try:
        if not config.ops_enabled():
            return False
        from sqlalchemy import select

        from app.platform.superagent.ingest import ingest_draft
        from app.platform.superagent.models import AgentSource
        from app.platform.superagent.sources import TriggerDraft

        now = datetime.now(_TZ)
        day = now.date().isoformat()
        payload: dict[str, Any] = {
            "signal": signals.SIGNAL_EVENT_FAILED,
            "event_type": str(event_type or "")[:120],
            "handler": str(handler_name or "")[:120],
            "error": str(error_summary or "")[:400] or None,
            "at": now.isoformat(),
            "channel": {"kind": "ops_event", "handler": str(handler_name or "")[:120]},
        }
        from app.core.database import async_session_factory

        async with async_session_factory() as session:
            source_row = (
                await session.execute(
                    select(AgentSource).where(AgentSource.name == EVENT_SOURCE_NAME)
                )
            ).scalar_one_or_none()
            if source_row is None:
                logger.debug("R3 event 直投源行未播种，跳过: %s", EVENT_SOURCE_NAME)
                return False
            draft = TriggerDraft(
                external_id=signals.event_eid(
                    str(handler_name or event_type or "unknown"), day,
                ),
                thread_key=signals.opsmisc_thread(day),
                actor={"id": str(handler_name or event_type or "unknown"),
                       "type": "feishu_event_handler"},
                payload=payload,
            )
            outcome, trigger = await ingest_draft(session, source_row, draft)
            if outcome != "stored":
                return False

            # ── 路由段（复刻 ingest_source_once：订阅直通优先 → evaluate 研判）──
            from app.platform.superagent.tasks import route_trigger_to_subscriptions

            routed = await route_trigger_to_subscriptions(session, trigger)
            if not routed and (source_row.config or {}).get("evaluate"):
                from app.platform.superagent.policy import (
                    evaluate_trigger,
                    get_current_policy,
                )

                policy = await get_current_policy(session)
                if policy is not None:
                    await evaluate_trigger(
                        session, trigger, policy=policy,
                        source_name=source_row.name,
                    )
            await session.commit()
            logger.info(
                "R3 event 直投: handler=%s %s", handler_name, trigger.external_id,
            )
            return True
    except Exception:  # noqa: BLE001 — 直投永不影响事件分发（红线）
        logger.exception(
            "R3 event 直投失败（忽略）: type=%s handler=%s", event_type, handler_name,
        )
        return False
