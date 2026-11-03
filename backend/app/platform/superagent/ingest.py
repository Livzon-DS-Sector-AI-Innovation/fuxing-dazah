"""事件入库服务 —— Trigger 幂等落库 / disposition 追加 / Thread upsert / cursor 事务推进。

核心不变量（冒烟②验收口径）：**cursor 推进仅在所覆盖 Trigger 全部落库后、
同一事务内发生**。crash 于任意点 → 重启重拉同批 → 全部 duplicate → cursor
再推进——不重放不漏单。

事务控制：本模块不 commit；事务边界归调用方（引擎 generator 的嵌套事务
或测试的回滚式 session）。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.platform.superagent.models import (
    AgentSource,
    AgentSourceCursor,
    AgentThread,
    AgentTrigger,
)
from app.platform.superagent.sources import (
    SourceRegistry,
    TriggerDraft,
    fastpath_reason,
    make_disposition_step,
    source_registry,
)

logger = logging.getLogger(__name__)

#: 单 Trigger 处置轨迹上限（防 JSONB 无界增长：水位边界重扫会长期重投同键）
MAX_DISPOSITION_STEPS = 50


# ═══════════════════════════════════════════════════════════════
# 单条草稿入库（幂等）
# ═══════════════════════════════════════════════════════════════


async def ingest_draft(
    session: Any,
    source_row: AgentSource,
    draft: TriggerDraft,
    *,
    now: datetime | None = None,
) -> tuple[str, AgentTrigger]:
    """幂等入库一条草稿。

    Returns:
        ("stored", 新行) 或 ("duplicate", 既有行[已追加 duplicate 步骤])。
        Fast Path 拦截的草稿同样落库（disposition 含 filtered+原因），审计可查。
    """
    now = now or datetime.now(UTC)
    reason = fastpath_reason(source_row.config, draft)

    stmt = (
        pg_insert(AgentTrigger)
        .values(
            source_id=source_row.id,
            external_id=draft.external_id,
            thread_key=draft.thread_key,
            actor=draft.actor,
            human=draft.human,
            addressed=draft.addressed,
            payload=draft.payload,
            received_at=now,
        )
        .on_conflict_do_nothing(index_elements=["source_id", "external_id"])
        .returning(AgentTrigger.id)
    )
    res = await session.execute(stmt)
    trigger_id = res.scalar_one_or_none()

    if trigger_id is not None:
        steps = [make_disposition_step("stored")]
        if reason:
            steps.append(make_disposition_step("filtered", reason=reason))
        trigger = await session.get(AgentTrigger, trigger_id)
        assert trigger is not None  # 刚插入必有
        trigger.disposition = steps
        await _upsert_thread(session, draft.thread_key, now)
        if reason:
            logger.debug(
                "Trigger filtered: source=%s external_id=%s reason=%s",
                source_row.name, draft.external_id, reason,
            )
        return "stored", trigger

    # 冲突 → 重复投递：不建新行，向既有行追加 duplicate 轨迹（上限防无界增长：
    # 水位 >= 边界重扫会让同一 external_id 长期被重投，超限后不再追加）
    existing = (
        await session.execute(
            select(AgentTrigger).where(
                AgentTrigger.source_id == source_row.id,
                AgentTrigger.external_id == draft.external_id,
            )
        )
    ).scalar_one()
    steps = list(existing.disposition or [])
    if len(steps) < MAX_DISPOSITION_STEPS:
        steps.append(make_disposition_step("duplicate"))
        existing.disposition = steps
    return "duplicate", existing


async def _upsert_thread(
    session: Any, thread_key: str, trigger_at: datetime,
) -> None:
    """Thread upsert：last_trigger_at 滚动推进；label/url 首见写入不覆盖。"""
    stmt = (
        pg_insert(AgentThread)
        .values(
            thread_key=thread_key,
            last_trigger_at=trigger_at,
        )
        .on_conflict_do_update(
            index_elements=["thread_key"],
            set_={"last_trigger_at": trigger_at},
        )
    )
    await session.execute(stmt)


# ═══════════════════════════════════════════════════════════════
# 读位
# ═══════════════════════════════════════════════════════════════


async def load_cursors(session: Any, source_id: uuid.UUID) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(AgentSourceCursor.name, AgentSourceCursor.value).where(
                AgentSourceCursor.source_id == source_id
            )
        )
    ).all()
    return {name: value for name, value in rows}


async def apply_cursor_updates(
    session: Any, source_id: uuid.UUID, cursor_updates: dict[str, Any]
) -> None:
    """读位推进（调用方保证此时所覆盖 Trigger 已全部落库、且在同一事务）。"""
    for name, value in (cursor_updates or {}).items():
        stmt = (
            pg_insert(AgentSourceCursor)
            .values(source_id=source_id, name=name, value=value)
            .on_conflict_do_update(
                index_elements=["source_id", "name"],
                set_={"value": value, "updated_at": datetime.now(UTC)},
            )
        )
        await session.execute(stmt)


# ═══════════════════════════════════════════════════════════════
# 整轮摄取
# ═══════════════════════════════════════════════════════════════


async def ingest_source_once(
    session: Any,
    source_row: AgentSource,
    *,
    registry: SourceRegistry | None = None,
) -> dict[str, Any]:
    """对单个源跑一轮 poll→落库→（直派生）→推读位（一个事务单元）。"""
    plugin = (registry or source_registry).get(source_row.kind)
    if plugin is None:
        return {"error": f"unknown_kind:{source_row.kind}"}

    cursors = await load_cursors(session, source_row.id)
    result = await plugin.poll(session, source_row, cursors)

    # 源→effect 直派生（config.effect_kind）：无授权语义的自动回写类走此直链，
    # 不建任务；研判/任务链路随 1b/1c 落位。仅对**新落库**的 Trigger 派生——
    # 重放批全 duplicate → 零新增 effect（crash 窗口天然不重复入队）。
    effect_kind = (source_row.config or {}).get("effect_kind") or ""

    counts = {"stored": 0, "duplicate": 0, "filtered": 0}
    for draft in result.drafts:
        outcome, trigger = await ingest_draft(session, source_row, draft)
        counts[outcome] += 1
        if any(s.get("step") == "filtered" for s in (trigger.disposition or [])):
            counts["filtered"] += 1
            continue
        if outcome != "stored":
            continue
        # 订阅直通优先（1b）：同 Thread 有任务订阅 → Input 送达，不经研判/直派生
        from app.platform.superagent.tasks import route_trigger_to_subscriptions

        routed = await route_trigger_to_subscriptions(session, trigger)
        if routed:
            counts["reached_tasks"] = counts.get("reached_tasks", 0) + routed
            continue
        # Slow Path 研判（1c）：源声明 evaluate=true → Gate+规则引擎+observe/auto
        if (source_row.config or {}).get("evaluate"):
            from app.platform.superagent.policy import (
                evaluate_trigger,
                get_current_policy,
            )

            policy = await get_current_policy(session)
            if policy is not None:
                adm = (source_row.config or {}).get("admission") or {}
                allowlist = set(adm.get("sender_allowlist") or [])
                await evaluate_trigger(
                    session, trigger, policy=policy, source_name=source_row.name,
                    sender_in_list=bool((trigger.actor or {}).get("id")) and
                    (trigger.actor or {}).get("id") in allowlist,
                    scope_key=adm.get("scope_key") or "",
                )
                counts["evaluated"] = counts.get("evaluated", 0) + 1
            continue
        if effect_kind:
            from app.platform.superagent.effects import enqueue_effect

            await enqueue_effect(
                session,
                effect_kind,
                {"trigger_id": str(trigger.id), **dict(trigger.payload or {})},
                dedupe_key=f"{effect_kind}:{trigger.external_id}",
            )
            counts["derived_effects"] = counts.get("derived_effects", 0) + 1

    await apply_cursor_updates(session, source_row.id, result.cursor_updates)
    counts["polled"] = len(result.drafts)
    if result.rebase:
        counts["rebased"] = True
    return counts


async def ingest_round(
    session: Any,
    *,
    registry: SourceRegistry | None = None,
) -> dict[str, dict[str, Any]]:
    """全部启用源各跑一轮（引擎 generator 每 tick 调用；逐源独立容错）。"""
    reg = registry or source_registry
    source_rows = (
        await session.execute(select(AgentSource).where(AgentSource.enabled.is_(True)))
    ).scalars().all()

    summary: dict[str, dict[str, Any]] = {}
    for source_row in source_rows:
        try:
            summary[source_row.name] = await ingest_source_once(
                session, source_row, registry=reg
            )
        except Exception:
            logger.exception("superagent 源摄取失败: %s", source_row.name)
            summary[source_row.name] = {"error": "poll_failed"}
    return summary
