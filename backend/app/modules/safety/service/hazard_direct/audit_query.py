"""督办留痕查询（方向 C 后端）—— 聚合底座留痕数据为按隐患的时间线。

数据源（均由 audit_trail.py 旁挂产生，开关关时无数据、本模块照常返回空）：
- 表单提交：agent_triggers（source=safety.hazard.audit，external_id 前缀
  card_submit:，thread=bitable:hazard:<record_id>，payload 带 hazard_no/text/
  operator，disposition 记 applied/failed）
- 催办发送：agent_outbox（conversation 前缀 hazard_dunning:，purpose=
  progress_dunning_card，sent 终态留痕行）

量级=周催办几十张卡+日常提交数十条，窗口内全取内存聚合（不过万行不进 SQL 聚合）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.modules.safety.service.hazard_direct.audit_trail import (
    AUDIT_SOURCE_NAME,
    THREAD_PREFIX,
)
from app.platform.superagent.models import AgentOutboxMessage, AgentSource, AgentTrigger

logger = logging.getLogger(__name__)

DUNNING_CONV_PREFIX = "hazard_dunning:"
SUBMISSION_PREFIX = "card_submit:"
_DEFAULT_DAYS = 30
_MAX_DAYS = 366


def _bj(value: datetime | None) -> str | None:
    """UTC → 北京时间 ISO（展示层免再换算）。"""
    from zoneinfo import ZoneInfo

    if value is None:
        return None
    return value.astimezone(ZoneInfo("Asia/Shanghai")).isoformat()


async def _fetch_window(
    db: Any, *, days: int,
) -> tuple[list[AgentTrigger], list[AgentOutboxMessage]]:
    since = datetime.now(UTC) - timedelta(days=min(max(days, 1), _MAX_DAYS))
    source = (
        await db.execute(
            select(AgentSource).where(AgentSource.name == AUDIT_SOURCE_NAME)
        )
    ).scalar_one_or_none()
    triggers: list[AgentTrigger] = []
    if source is not None:
        triggers = list((
            await db.execute(
                select(AgentTrigger)
                .where(
                    AgentTrigger.source_id == source.id,
                    AgentTrigger.external_id.like(f"{SUBMISSION_PREFIX}%"),
                    AgentTrigger.received_at >= since,
                )
                .order_by(AgentTrigger.received_at.desc())
            )
        ).scalars().all())
    sends = list((
        await db.execute(
            select(AgentOutboxMessage)
            .where(
                AgentOutboxMessage.conversation.like(f"{DUNNING_CONV_PREFIX}%"),
                AgentOutboxMessage.purpose == "progress_dunning_card",
                AgentOutboxMessage.sent_at >= since,
            )
            .order_by(AgentOutboxMessage.sent_at.desc())
        )
    ).scalars().all())
    return triggers, sends


def _record_id_from_thread(thread_key: str) -> str:
    return thread_key.removeprefix(f"{THREAD_PREFIX}:") if thread_key else ""


def _record_id_from_conversation(conversation: str) -> str:
    # hazard_dunning:<record_id>:<date>
    parts = (conversation or "").split(":")
    return parts[1] if len(parts) >= 3 else ""


async def list_hazard_audit(
    db: Any, *, days: int = _DEFAULT_DAYS, keyword: str | None = None,
) -> list[dict[str, Any]]:
    """窗口内按隐患聚合：催办次数/收件人数/提交次数（含失败）/最近活动。"""
    triggers, sends = await _fetch_window(db, days=days)

    items: dict[str, dict[str, Any]] = {}
    # 「最近」判定显式比较时间戳（同秒多条时 DB 排序不定，不能靠迭代序）
    latest: dict[str, dict[str, datetime | None]] = {}

    def _touch(rid: str, what: str, at: datetime | None) -> bool:
        cur = latest.setdefault(rid, {"submission": None, "dunning": None, "activity": None})
        if at is not None and (cur[what] is None or at >= cur[what]):  # type: ignore[operator]
            cur[what] = at  # type: ignore[assignment]
            return what != "activity"
        return False

    for t in triggers:
        rid = _record_id_from_thread(t.thread_key)
        if not rid:
            continue
        entry = items.setdefault(rid, {
            "record_id": rid,
            "hazard_no": (t.payload or {}).get("hazard_no") or "",
            "dunning_count": 0, "dunning_recipients": [],
            "submission_count": 0, "submission_failed": 0,
            "last_submission": None, "last_submission_at": None,
            "last_dunning_at": None, "last_activity_at": None,
        })
        entry["submission_count"] += 1
        if any(s.get("step") == "failed" for s in (t.disposition or [])):
            entry["submission_failed"] += 1
        if _touch(rid, "submission", t.received_at):
            entry["last_submission"] = {
                "text": (t.payload or {}).get("text") or "",
                "operator": (t.payload or {}).get("operator") or "",
                "at": _bj(t.received_at),
            }
            entry["last_submission_at"] = _bj(t.received_at)
        _touch(rid, "activity", t.received_at)
        entry["last_activity_at"] = _bj(latest[rid]["activity"])
        if not entry["hazard_no"]:
            entry["hazard_no"] = (t.payload or {}).get("hazard_no") or ""

    for s in sends:
        rid = _record_id_from_conversation(s.conversation or "")
        if not rid:
            continue
        entry = items.setdefault(rid, {
            "record_id": rid,
            "hazard_no": (s.body or {}).get("hazard_no") or "",
            "dunning_count": 0, "dunning_recipients": [],
            "submission_count": 0, "submission_failed": 0,
            "last_submission": None, "last_submission_at": None,
            "last_dunning_at": None, "last_activity_at": None,
        })
        entry["dunning_count"] += 1
        recv = (s.channel or {}).get("receive_id") or ""
        if recv and recv not in entry["dunning_recipients"]:
            entry["dunning_recipients"].append(recv)
        if _touch(rid, "dunning", s.sent_at):
            entry["last_dunning_at"] = _bj(s.sent_at)
        _touch(rid, "activity", s.sent_at)
        entry["last_activity_at"] = _bj(latest[rid]["activity"])
        if not entry["hazard_no"]:
            entry["hazard_no"] = (s.body or {}).get("hazard_no") or ""

    out = sorted(
        items.values(),
        key=lambda e: e["last_activity_at"] or "", reverse=True,
    )
    if keyword:
        kw = keyword.strip()
        out = [e for e in out if kw in e["hazard_no"] or kw in e["record_id"]]
    for e in out:
        e["dunning_recipient_count"] = len(e["dunning_recipients"])
    return out


async def hazard_audit_timeline(
    db: Any, record_id: str, *, days: int = 90,
) -> list[dict[str, Any]]:
    """单条隐患的合并时间线（催办发送 + 表单提交，按时间倒序）。"""
    triggers, sends = await _fetch_window(db, days=days)
    events: list[dict[str, Any]] = []
    for t in triggers:
        if _record_id_from_thread(t.thread_key) != record_id:
            continue
        applied = any(s.get("step") == "applied" for s in (t.disposition or []))
        failed = any(s.get("step") == "failed" for s in (t.disposition or []))
        events.append({
            "kind": "submission",
            "at": _bj(t.received_at),
            "operator": (t.payload or {}).get("operator") or "",
            "text": (t.payload or {}).get("text") or "",
            "hazard_no": (t.payload or {}).get("hazard_no") or "",
            "outcome": "failed" if failed else ("applied" if applied else ""),
        })
    for s in sends:
        if _record_id_from_conversation(s.conversation or "") != record_id:
            continue
        events.append({
            "kind": "dunning",
            "at": _bj(s.sent_at),
            "role": (s.body or {}).get("role") or "",
            "name": (s.body or {}).get("name") or "",
            "receive_id": (s.channel or {}).get("receive_id") or "",
            "hazard_no": (s.body or {}).get("hazard_no") or "",
            "outcome": "sent",
        })
    events.sort(key=lambda e: e["at"] or "", reverse=True)
    return events
