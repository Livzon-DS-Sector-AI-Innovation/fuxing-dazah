"""督办留痕（方向 B）—— 业务动作旁挂落底座：提交→Trigger / 催办发送→Outbox。

设计定位（2026-11-04 拍板）：交互零变化，把原来「只存在于日志」的动作变成
结构化可查数据——
- 表单提交：handle_progress_submit(_direct) 旁挂 agent_triggers
  （external_id=card_submit:<卡消息id>:<动作名> 天然幂等；thread=
  bitable:hazard:<record_id>，同隐患提交串成一线程=留痕时间线基础；
  disposition 记 applied/failed 结果）
- 催办 DM 发送：send_urge_cards 旁挂 agent_outbox **sent 留痕行**
  （直接落 sent 终态，永不进发送循环；channel 行内权威）

开关 SAFETY_HAZARD_AUDIT_TRAIL_ENABLED 默认关（旁挂惯例，冒烟后开）；
开关关=零 DB 写零行为变化。source 行（safety.hazard.audit）首见 ensure，
不参与 poll（enabled 恒 false，仅作归属载体）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.platform.superagent.models import AgentOutboxMessage, AgentSource
from app.platform.superagent.sources import TriggerDraft, make_disposition_step

logger = logging.getLogger(__name__)

AUDIT_SOURCE_NAME = "safety.hazard.audit"
AUDIT_SOURCE_KIND = "safety_card_action"
THREAD_PREFIX = "bitable:hazard"


def audit_enabled() -> bool:
    from app.modules.safety.app_config.store import store

    return store.get_bool("SAFETY_HAZARD_AUDIT_TRAIL_ENABLED", False)


async def _ensure_source_row(session: Any) -> AgentSource:
    """取/建留痕源行（幂等；enabled 恒 false 不参与 poll，仅归属载体）。"""
    row = (
        await session.execute(
            select(AgentSource).where(AgentSource.name == AUDIT_SOURCE_NAME)
        )
    ).scalar_one_or_none()
    if row is None:
        row = AgentSource(
            kind=AUDIT_SOURCE_KIND, name=AUDIT_SOURCE_NAME, config={}, enabled=False,
        )
        session.add(row)
        await session.flush()
    return row


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def record_card_submission(
    session: Any,
    *,
    record_id: str,
    text: str,
    operator: str,
    message_key: str,
    applied: bool,
    hazard_no: str = "",
    note: str = "",
) -> bool:
    """表单提交动作落 Trigger（幂等：同 message_key 重记=duplicate 不改写）。

    Returns:
        是否新落一行（duplicate/开关关=False）。
    """
    if not audit_enabled() or not message_key:
        return False
    try:
        from app.platform.superagent.ingest import ingest_draft

        source_row = await _ensure_source_row(session)
        draft = TriggerDraft(
            external_id=f"card_submit:{message_key}",
            thread_key=f"{THREAD_PREFIX}:{record_id or 'unknown'}",
            actor={"id": operator or "", "type": "feishu_user"},
            human=True,
            addressed=False,
            payload={
                "record_id": record_id,
                "hazard_no": hazard_no,
                "text": text[:2000],
                "operator": operator,
                "at": _now_iso(),
                "channel": {"kind": "bitable", "record_id": record_id},
            },
        )
        outcome, trigger = await ingest_draft(session, source_row, draft)
        if outcome != "stored":
            return False  # duplicate：动作已留痕，不重复
        trigger.disposition = [
            *list(trigger.disposition or []),
            make_disposition_step(
                "applied" if applied else "failed", reason=note[:200],
            ),
        ]
        return True
    except Exception:
        logger.exception("留痕(提交)失败（不影响业务链路）: key=%s", message_key)
        return False


async def record_dunning_card_sent(
    session: Any,
    *,
    record_id: str,
    hazard_no: str,
    receive_id: str,
    id_type: str,
    role: str,
    name: str,
) -> None:
    """催办 DM 发送成功旁挂 outbox **sent 留痕行**（终态直落，不进发送循环）。"""
    if not audit_enabled() or not record_id:
        return
    try:
        session.add(AgentOutboxMessage(
            conversation=f"hazard_dunning:{record_id}:{datetime.now(UTC).date().isoformat()}",
            channel={"type": "feishu_dm", "id_type": id_type, "receive_id": receive_id},
            purpose="progress_dunning_card",
            body={"record_id": record_id, "hazard_no": hazard_no, "role": role, "name": name},
            status="sent",  # 留痕行：发送已发生，永不 pending
            sent_at=datetime.now(UTC),
        ))
    except Exception:
        logger.exception("留痕(催办发送)失败（不影响业务链路）: record=%s", record_id)
