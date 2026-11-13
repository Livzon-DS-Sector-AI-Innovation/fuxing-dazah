"""副作用层 —— effects 先存后做 + outbox 会话保序 + HealthBoard 认领制。

工程铁律：
- 一切外部副作用先入库后执行（重启不丢、可对账——推广 scheduler_job_runs 范式）
- effects 领取 ``FOR UPDATE SKIP LOCKED``（单进程正确，多进程安全）
- 行内地址（chat_id 等）是唯一权威，handler 与任何下游不可覆盖
- 执行链内禁止裸 ``asyncio.create_task``（红线④——副作用必须可对账）
- Later 异常=依赖未就绪，推移到期不计失败
- 连续 3 次失败才健康告警（一次网络抖动不打扰人）

互斥设计：handler 在持有行锁的事务内执行（锁即认领），crash → 锁释放、
行仍 pending → 下轮重试（at-least-once；handler 须幂等——digest 投格/
Bitable 回写天然幂等）。无 running 中间态，无 stale 回收复杂度。
"""

from __future__ import annotations

import logging
import os
import socket
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.platform.superagent.models import AgentEffect, AgentHealth, AgentOutboxMessage

logger = logging.getLogger(__name__)

# ── 常量（一期固定，需要时再提升为 settings）──
BACKOFF_BASE_SECONDS = 2.0
BACKOFF_CAP_SECONDS = 60.0
EFFECT_MAX_ATTEMPTS = 10          # 超过即 park 为 failed（可见可查，不再空转）
LATER_DELAY_SECONDS = 30.0        # Later 默认推迟
HEALTH_ALERT_AFTER_FAILURES = 3   # 连续失败达到该值才置 error + DM
CLAIM_STALE_MINUTES = 15          # 健康认领过期接管窗口

EffectHandler = Callable[[dict[str, Any]], Awaitable[None]]
OutboxSender = Callable[[dict[str, Any], dict[str, Any]], Awaitable[bool]]

#: 本进程认领者标识（host:pid）
OWNER_ID = f"{socket.gethostname()}:{os.getpid()}"

# 连续失败进程内计数（认领制保证单写者，进程内计数足够）
_CONSECUTIVE_FAILURES: dict[str, int] = {}


# ═══════════════════════════════════════════════════════════════
# 纯函数
# ═══════════════════════════════════════════════════════════════


def next_backoff_seconds(attempts: int, *, base: float = BACKOFF_BASE_SECONDS,
                         cap: float = BACKOFF_CAP_SECONDS) -> float:
    """失败退避：2s 起倍增，封顶 60s（attempts=首败后次数 1,2,3…→2,4,8…60）。"""
    if attempts <= 1:
        return base
    return min(cap, base * (2 ** (attempts - 1)))


class Later(Exception):  # noqa: N818 — 设计文档 §4.4 钦定领域名「Later 语义」
    """依赖/槽位未就绪：推迟重试，不计失败。"""


# ═══════════════════════════════════════════════════════════════
# Effect handler 注册制
# ═══════════════════════════════════════════════════════════════

_EFFECT_HANDLERS: dict[str, EffectHandler] = {}


def register_effect_handler(kind: str, handler: EffectHandler) -> None:
    if kind in _EFFECT_HANDLERS:
        raise ValueError(f"Duplicate effect handler: {kind}")
    _EFFECT_HANDLERS[kind] = handler


def get_effect_handler(kind: str) -> EffectHandler | None:
    return _EFFECT_HANDLERS.get(kind)


# ═══════════════════════════════════════════════════════════════
# 入队 / 领取 / 执行
# ═══════════════════════════════════════════════════════════════


async def enqueue_effect(
    session: Any,
    kind: str,
    payload: dict[str, Any],
    *,
    dedupe_key: str | None = None,
) -> uuid.UUID:
    """副作用入队（先存后做）。待处理同 (kind, dedupe_key) 重复入队=替换
    payload 并立即到期、重置失败计数（新载荷=新一轮；不改排队语义）。"""
    key = dedupe_key or str(uuid.uuid4())
    now = datetime.now(UTC)
    stmt = (
        pg_insert(AgentEffect)
        .values(kind=kind, dedupe_key=key, payload=payload, status="pending",
                attempts=0, next_due_at=now)
        .on_conflict_do_update(
            index_elements=["kind", "dedupe_key"],
            # 字面量谓词：ON CONFLICT 推断须与部分索引谓词字面一致（绑定参数会报
            # "no unique or exclusion constraint matching the ON CONFLICT specification"）
            index_where=text("status = 'pending'"),
            set_={"payload": payload, "attempts": 0, "next_due_at": now,
                  "last_error": None},
        )
        .returning(AgentEffect.id)
    )
    res = await session.execute(stmt)
    effect_id = res.scalar_one()
    logger.info("effect 入队: kind=%s dedupe=%s id=%s", kind, key, effect_id)
    return effect_id


async def find_due_effect_ids(session: Any, *, limit: int = 20) -> list[uuid.UUID]:
    rows = (
        await session.execute(
            select(AgentEffect.id)
            .where(AgentEffect.status == "pending", AgentEffect.next_due_at <= datetime.now(UTC))
            .order_by(AgentEffect.next_due_at)
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


async def execute_claimed_effect(session: Any, effect_id: uuid.UUID) -> str:
    """领取并执行单个 effect（行锁即认领；调用方负责事务提交）。

    Returns:
        done / retried / later / parked / skipped（他方已处理或不再到期）
    """
    row = (
        await session.execute(
            select(AgentEffect)
            .where(
                AgentEffect.id == effect_id,
                AgentEffect.status == "pending",
                AgentEffect.next_due_at <= datetime.now(UTC),
            )
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if row is None:
        return "skipped"

    handler = get_effect_handler(row.kind)
    if handler is None:
        # 未注册类型：park 而非无限重试（注册表缺失是部署错误，需人工介入）
        row.status = "failed"
        row.last_error = f"no handler registered for kind={row.kind}"
        await report_state(session, f"effects:{row.kind}", "error", row.last_error)
        return "parked"

    component = "superagent:effects"  # 与 bootstrap 认领集一致（红线②一组件一行）
    try:
        await handler(row.payload or {})
    except Later as exc:
        row.next_due_at = datetime.now(UTC) + timedelta(
            seconds=float(exc.args[0]) if exc.args else LATER_DELAY_SECONDS
        )
        return "later"
    except Exception as exc:
        row.attempts += 1
        row.last_error = f"{type(exc).__name__}: {exc}"[:2000]
        if row.attempts >= EFFECT_MAX_ATTEMPTS:
            row.status = "failed"
            await report_state(session, component, "error",
                               f"effect {row.id} 连续 {row.attempts} 次失败已 parked")
            return "parked"
        row.next_due_at = datetime.now(UTC) + timedelta(
            seconds=next_backoff_seconds(row.attempts)
        )
        outcome = await note_effect_failure(session, component, row)
        return outcome
    else:
        row.status = "done"
        await note_effect_success(session, component)
        return "done"


async def note_effect_failure(session: Any, component: str, effect: AgentEffect) -> str:
    """连续失败计数：达到 HEALTH_ALERT_AFTER_FAILURES 才置 error + DM 告警。"""
    n = _CONSECUTIVE_FAILURES.get(component, 0) + 1
    _CONSECUTIVE_FAILURES[component] = n
    if n >= HEALTH_ALERT_AFTER_FAILURES:
        await report_state(session, component, "error",
                           f"连续 {n} 次失败（最近: {effect.last_error or '-'}）")
        await enqueue_effect(
            session, "dm_admin",
            {
                "text": (f"[Super-agent] 组件 {component} 连续 {n} 次失败\n"
                         f"effect={effect.id} kind={effect.kind}\n"
                         f"最近错误: {(effect.last_error or '')[:300]}"),
            },
            dedupe_key=f"health-alert:{component}",
        )
    return "retried"


async def note_effect_success(session: Any, component: str) -> None:
    _CONSECUTIVE_FAILURES.pop(component, None)
    await report_state(session, component, "ready")


# ═══════════════════════════════════════════════════════════════
# Outbox —— 同会话严格保序
# ═══════════════════════════════════════════════════════════════

_OUTBOX_SENDERS: dict[str, OutboxSender] = {}


def register_outbox_sender(channel_type: str, sender: OutboxSender) -> None:
    if channel_type in _OUTBOX_SENDERS:
        raise ValueError(f"Duplicate outbox sender: {channel_type}")
    _OUTBOX_SENDERS[channel_type] = sender


async def enqueue_outbox_message(
    session: Any,
    *,
    conversation: str,
    channel: dict[str, Any],
    body: dict[str, Any],
    purpose: str = "message",
    task_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """消息入 outbox（同 conversation 按 seq 严格保序发送）。"""
    stmt = (
        pg_insert(AgentOutboxMessage)
        .values(
            conversation=conversation, channel=channel, body=body,
            purpose=purpose, task_id=task_id, status="pending",
        )
        .returning(AgentOutboxMessage.id)
    )
    res = await session.execute(stmt)
    msg_id = res.scalar_one()
    logger.info("outbox 入队: conv=%s purpose=%s id=%s", conversation, purpose, msg_id)
    return msg_id


async def find_active_conversations(session: Any, *, limit: int = 20) -> list[str]:
    """有待发消息的会话键（每会话至多推进一条——队头阻塞保序）。"""
    rows = (
        await session.execute(
            select(AgentOutboxMessage.conversation)
            .where(AgentOutboxMessage.status == "pending")
            .distinct()
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


async def send_conversation_head(session: Any, conversation: str) -> str:
    """发送某会话的队头消息：队头未成功前不推进后续（确认先于结果）。

    Returns:
        sent / retried / later / dropped / skipped
    """
    # 保序关键：取队头**不看 next_due_at**——队头退避中则整会话等待，
    # 绝不让后续消息跳队先发（确认先于结果；审查修复：原先按到期过滤
    # 会让队头退避窗内的后续消息越过队头）
    row = (
        await session.execute(
            select(AgentOutboxMessage)
            .where(
                AgentOutboxMessage.conversation == conversation,
                AgentOutboxMessage.status == "pending",
            )
            .order_by(AgentOutboxMessage.seq)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if row is None:
        return "skipped"
    if row.next_due_at and row.next_due_at > datetime.now(UTC):
        return "waiting"  # 队头退避中：不发送也不跳队

    sender = _OUTBOX_SENDERS.get((row.channel or {}).get("type", ""))
    if sender is None:
        row.status = "dropped"
        row.dropped_reason = f"no sender for channel.type={(row.channel or {}).get('type')}"
        return "dropped"
    try:
        ok = await sender(row.channel or {}, row.body or {})
    except Later as exc:
        row.next_due_at = datetime.now(UTC) + timedelta(
            seconds=float(exc.args[0]) if exc.args else LATER_DELAY_SECONDS
        )
        return "later"
    except Exception as exc:
        row.attempts += 1
        row.last_error = f"{type(exc).__name__}: {exc}"[:2000]
        if row.attempts >= EFFECT_MAX_ATTEMPTS:
            row.status = "dropped"
            row.dropped_reason = f"max attempts: {(row.last_error or '')[:200]}"
            return "dropped"
        row.next_due_at = datetime.now(UTC) + timedelta(
            seconds=next_backoff_seconds(row.attempts)
        )
        return "retried"
    if ok:
        row.status = "sent"
        row.sent_at = datetime.now(UTC)
        return "sent"
    # sender 返回 False（可重试软失败）
    row.attempts += 1
    row.last_error = "sender returned False"
    row.next_due_at = datetime.now(UTC) + timedelta(
        seconds=next_backoff_seconds(row.attempts)
    )
    return "retried"


# ═══════════════════════════════════════════════════════════════
# HealthBoard —— 一组件一行认领制
# ═══════════════════════════════════════════════════════════════


async def claim_component(
    session: Any, component: str, *, stale_minutes: int = CLAIM_STALE_MINUTES,
) -> bool:
    """认领健康条目：无人认领或认领过期 → 归我；他人活跃认领 → False。"""
    now = datetime.now(UTC)
    stmt = (
        pg_insert(AgentHealth)
        .values(component=component, state="paused", claimed_by=OWNER_ID, claimed_at=now)
        .on_conflict_do_update(
            index_elements=["component"],
            set_={"claimed_by": OWNER_ID, "claimed_at": now},
            where=(AgentHealth.claimed_by.is_(None))
            | (AgentHealth.claimed_at < now - timedelta(minutes=stale_minutes)),
        )
        .returning(AgentHealth.claimed_by)
    )
    res = await session.execute(stmt)
    claimed_by = res.scalar_one_or_none()
    if claimed_by is None:
        logger.warning("健康条目 %s 被他人活跃认领，本进程不写该条目", component)
        return False
    return claimed_by == OWNER_ID


async def report_state(
    session: Any, component: str, state: str, detail: str | None = None,
) -> None:
    """上报组件状态（认领制下仅认领者应调用；未认领时顺带接管过期行）。"""
    now = datetime.now(UTC)
    stmt = (
        pg_insert(AgentHealth)
        .values(component=component, state=state, detail=detail,
                claimed_by=OWNER_ID, claimed_at=now)
        .on_conflict_do_update(
            index_elements=["component"],
            set_={"state": state, "detail": detail, "updated_at": now},
        )
    )
    await session.execute(stmt)


# ═══════════════════════════════════════════════════════════════
# 内置 handler：dm_admin（Watchdog/健康告警通道）
# ═══════════════════════════════════════════════════════════════

#: DM 发送器注入点：host 应用启动时 set_dm_sender(fn)（fn(open_id, text) -> bool）。
#: 平台不 import 任何业务通知模块（依赖方向）；未注入=仅留痕。
_DM_SENDER: Callable[[str, str], Awaitable[bool]] | None = None

#: DM 交互卡发送器注入点（payload.card → fn(open_id, card_dict) -> bool；
#: 未注入或失败由 handler 回退纯文本 payload.text——降级红线）。
_DM_CARD_SENDER: Callable[[str, dict[str, Any]], Awaitable[bool]] | None = None


def set_dm_sender(fn: Callable[[str, str], Awaitable[bool]]) -> None:
    global _DM_SENDER
    _DM_SENDER = fn


def set_dm_card_sender(fn: Callable[[str, dict[str, Any]], Awaitable[bool]]) -> None:
    global _DM_CARD_SENDER
    _DM_CARD_SENDER = fn


async def _dm_admin_handler(payload: dict[str, Any]) -> None:
    from app.core.config import get_settings

    recipients = [
        x.strip()
        for x in (get_settings().SUPERAGENT_ADMIN_OPEN_IDS or "").split(",")
        if x.strip()
    ]
    text = (payload or {}).get("text") or ""
    if not recipients:
        logger.warning("dm_admin 无收件人（SUPERAGENT_ADMIN_OPEN_IDS 空），告警仅留痕: %s",
                       text[:120])
        return
    if _DM_SENDER is None:
        logger.warning("dm_admin 发送器未注入（host 应用未 set_dm_sender），仅留痕: %s",
                       text[:120])
        return
    card = payload.get("card") if isinstance(payload, dict) else None
    if card and _DM_CARD_SENDER is not None:
        # 交互卡优先（降级红线：任一收件人卡片发送失败 → 该收件人回退纯文本）
        failed_text: list[str] = []
        for r in recipients:
            try:
                sent = await _DM_CARD_SENDER(r, card)
            except Exception:
                logger.exception("dm_admin 交互卡发送异常（回退纯文本）: %s", r)
                sent = False
            if not sent:
                if not await _DM_SENDER(r, text):
                    failed_text.append(r)
        if failed_text:
            raise RuntimeError(f"dm_admin 部分收件人发送失败: {failed_text}")
        return
    failed = [r for r in recipients if not await _DM_SENDER(r, text)]
    if failed:
        raise RuntimeError(f"dm_admin 部分收件人发送失败: {failed}")  # → 退避重试


register_effect_handler("dm_admin", _dm_admin_handler)
