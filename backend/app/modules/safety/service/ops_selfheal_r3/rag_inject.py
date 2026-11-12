"""R3 rag 直投 —— rag_health 状态翻转处直投 ingest_draft（§4.1 B）。

直投范式对齐 hazard_direct/audit_trail（源行仅归属载体 enabled 恒 false），
但 R3 信号需走研判开单：入库后复刻 ingest_source_once 的路由段（订阅直通
优先 → 源声明 evaluate 则研判）。全程 try/except——直投失败只记日志，
绝不影响探活自身（探活是既有告警链，R3 零改动红线）。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.modules.safety.service.ops_selfheal_r3 import config, signals

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Shanghai")

#: 直投载体源行名（rule.r3_ops_rag_signal 的 source 匹配依据）
RAG_SOURCE_NAME = "safety.ops.rag_inject"


def _duration_text(seconds: float) -> str:
    """持续时长展示（对齐 rag_health._duration_text 口径）。"""
    secs = int(seconds)
    if secs >= 3600:
        return f"{secs // 3600}小时{(secs % 3600) // 60}分"
    return f"{secs // 60}分{secs % 60}秒"


async def inject_rag_signal(
    kind: str,
    *,
    detail: str,
    duration_seconds: float | None = None,
) -> bool:
    """RAG 状态翻转直投一条 Trigger（degraded/recovered 各投各，同日聚同 thread）。

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
        signal = (
            signals.SIGNAL_RAG_DEGRADED if kind == "degraded"
            else signals.SIGNAL_RAG_RECOVERED
        )
        payload: dict[str, Any] = {
            "signal": signal,
            "detail": detail[:600],
            "at": now.isoformat(),
            "channel": {"kind": "ops_rag"},
        }
        if duration_seconds is not None:
            payload["duration"] = _duration_text(duration_seconds)

        from app.core.database import async_session_factory

        async with async_session_factory() as session:
            source_row = (
                await session.execute(
                    select(AgentSource).where(AgentSource.name == RAG_SOURCE_NAME)
                )
            ).scalar_one_or_none()
            if source_row is None:
                logger.debug("R3 rag 直投源行未播种，跳过: %s", RAG_SOURCE_NAME)
                return False
            draft = TriggerDraft(
                external_id=signals.rag_eid(day, kind, now.strftime("%H%M%S%f")),
                thread_key=signals.rag_thread(day),
                actor={"id": "rag_health", "type": "probe"},
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
            logger.info("R3 rag 直投: %s %s", kind, trigger.external_id)
            return True
    except Exception:  # noqa: BLE001 — 直投永不影响探活（红线）
        logger.exception("R3 rag 直投失败（忽略）: kind=%s", kind)
        return False
