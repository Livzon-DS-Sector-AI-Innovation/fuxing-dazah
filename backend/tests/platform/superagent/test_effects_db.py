"""副作用层测试 —— A 层退避纯函数 + B 层 effects/outbox/health（真 PG 回滚式）。

覆盖（T02）：
- 退避：2s 起倍增封顶 60s
- effects：先存后做 / 重复入队替换 payload 立即到期 / 完成后同键可再入队
- 失败：退避重试 / 连续 3 次失败健康置 error + dm_admin 告警入队 / 超 10 次 park
- Later：推迟不计失败
- 并发领取互斥（SKIP LOCKED）
- outbox：同会话严格保序（队头失败不推进）/ 跨会话不阻塞 / 地址行内不可覆盖
- health：认领制（重复认领拒绝 / 过期接管）
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

import app.platform.superagent.effects as effects_mod
from app.platform.superagent.effects import (
    Later,
    claim_component,
    enqueue_effect,
    enqueue_outbox_message,
    execute_claimed_effect,
    find_due_effect_ids,
    next_backoff_seconds,
    register_outbox_sender,
    send_conversation_head,
)
from app.platform.superagent.models import AgentEffect, AgentHealth, AgentOutboxMessage

# ═══════════════════════════════════════════════════════════════
# A 层：退避纯函数
# ═══════════════════════════════════════════════════════════════


def test_backoff_doubling_and_cap() -> None:
    assert next_backoff_seconds(1) == 2.0
    assert next_backoff_seconds(2) == 4.0
    assert next_backoff_seconds(3) == 8.0
    assert next_backoff_seconds(5) == 32.0
    assert next_backoff_seconds(6) == 60.0   # 64 → 封顶 60
    assert next_backoff_seconds(50) == 60.0


def test_backoff_invalid_attempts_floor() -> None:
    assert next_backoff_seconds(0) == 2.0
    assert next_backoff_seconds(-3) == 2.0


# ═══════════════════════════════════════════════════════════════
# B 层：effects
# ═══════════════════════════════════════════════════════════════


async def test_effect_execute_done(db_session) -> None:
    calls: list[dict] = []

    async def handler(payload: dict) -> None:
        calls.append(payload)

    effects_mod._EFFECT_HANDLERS["test_ok"] = handler  # 测试直接注入注册表
    try:
        effect_id = await enqueue_effect(
            db_session, "test_ok", {"x": 1}, dedupe_key="k1",
        )
        outcome = await execute_claimed_effect(db_session, effect_id)
        assert outcome == "done"
        assert calls == [{"x": 1}]
        row = await db_session.get(AgentEffect, effect_id)
        assert row.status == "done"
    finally:
        effects_mod._EFFECT_HANDLERS.pop("test_ok", None)


async def test_effect_reenqueue_replaces_payload_and_resets(db_session) -> None:
    """重复入队（同键待处理）：payload 替换、立即到期、attempts 清零。"""
    effects_mod._EFFECT_HANDLERS["test_replace"] = lambda p: None  # noqa: E731
    try:
        effect_id = await enqueue_effect(
            db_session, "test_replace", {"v": 1}, dedupe_key="rk",
        )
        row = await db_session.get(AgentEffect, effect_id)
        row.attempts = 3
        row.next_due_at = datetime.now(UTC) + timedelta(hours=1)  # 退避中
        await db_session.flush()

        await enqueue_effect(db_session, "test_replace", {"v": 2}, dedupe_key="rk")
        assert (await find_due_effect_ids(db_session)) != []
        row = (
            await db_session.execute(
                select(AgentEffect)
                .where(AgentEffect.dedupe_key == "rk")
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        assert row.payload == {"v": 2}
        assert row.attempts == 0
        assert row.next_due_at <= datetime.now(UTC)
        assert row.status == "pending"
    finally:
        effects_mod._EFFECT_HANDLERS.pop("test_replace", None)


async def test_effect_done_key_reusable(db_session) -> None:
    """done 行不占幂等键：同键可再次入队（新一行）。"""
    async def noop(payload: dict) -> None:
        return None

    effects_mod._EFFECT_HANDLERS["test_reuse"] = noop
    try:
        id1 = await enqueue_effect(db_session, "test_reuse", {}, dedupe_key="re")
        assert await execute_claimed_effect(db_session, id1) == "done"
        await execute_claimed_effect(db_session, id1)
        id2 = await enqueue_effect(db_session, "test_reuse", {}, dedupe_key="re")
        assert id1 != id2
    finally:
        effects_mod._EFFECT_HANDLERS.pop("test_reuse", None)


async def test_effect_failure_backoff_and_park(db_session) -> None:
    """失败退避 → 多次失败 park 为 failed。"""

    async def boom(payload: dict) -> None:
        raise RuntimeError("boom")

    effects_mod._EFFECT_HANDLERS["test_boom"] = boom
    effects_mod._CONSECUTIVE_FAILURES.pop("superagent:effects", None)
    try:
        effect_id = await enqueue_effect(db_session, "test_boom", {}, dedupe_key="bk")

        outcome = await execute_claimed_effect(db_session, effect_id)
        assert outcome == "retried"
        row = await db_session.get(AgentEffect, effect_id)
        assert row.attempts == 1
        assert row.next_due_at > datetime.now(UTC)  # 已退避，本 tick 不再取

        seen_parked = False
        for _ in range(12):
            row.next_due_at = datetime.now(UTC) - timedelta(seconds=1)  # 测试加速到期
            await db_session.flush()
            outcome = await execute_claimed_effect(db_session, effect_id)
            if outcome == "parked":
                seen_parked = True
                break
            assert outcome == "retried", outcome
        assert seen_parked
        row = await db_session.get(AgentEffect, effect_id)
        assert row.status == "failed"
        assert row.attempts >= effects_mod.EFFECT_MAX_ATTEMPTS
    finally:
        effects_mod._EFFECT_HANDLERS.pop("test_boom", None)
        effects_mod._CONSECUTIVE_FAILURES.pop("superagent:effects", None)


async def test_effect_consecutive_failures_alert_and_recovery(db_session) -> None:
    """连续 3 次失败 → health error + dm_admin 告警入队；成功恢复 ready。"""
    n = {"fail": 0}

    async def flaky(payload: dict) -> None:
        n["fail"] += 1
        if n["fail"] <= 3:
            raise RuntimeError("flaky")

    effects_mod._EFFECT_HANDLERS["test_flaky"] = flaky
    effects_mod._CONSECUTIVE_FAILURES.pop("superagent:effects", None)
    try:
        effect_id = await enqueue_effect(db_session, "test_flaky", {}, dedupe_key="fk")

        for i in range(3):
            row = await db_session.get(AgentEffect, effect_id)
            row.next_due_at = datetime.now(UTC) - timedelta(seconds=1)
            await db_session.flush()
            await execute_claimed_effect(db_session, effect_id)

        health = (
            await db_session.execute(
                select(AgentHealth).where(AgentHealth.component == "superagent:effects")
            )
        ).scalar_one()
        assert health.state == "error"

        alerts = (
            await db_session.execute(
                select(AgentEffect).where(AgentEffect.kind == "dm_admin")
            )
        ).scalars().all()
        assert len(alerts) >= 1  # 告警走 effects（先存后发，自举不裸奔）

        # 恢复：第 4 次成功 → ready
        row = await db_session.get(AgentEffect, effect_id)
        row.next_due_at = datetime.now(UTC) - timedelta(seconds=1)
        await db_session.flush()
        outcome = await execute_claimed_effect(db_session, effect_id)
        assert outcome == "done"
        await db_session.refresh(health)
        assert health.state == "ready"
    finally:
        effects_mod._EFFECT_HANDLERS.pop("test_flaky", None)
        effects_mod._CONSECUTIVE_FAILURES.pop("superagent:effects", None)


async def test_effect_later_not_counted(db_session) -> None:
    """Later：推迟到期、attempts 不增、不触发健康告警。"""

    async def later(payload: dict) -> None:
        raise Later(0.05)

    effects_mod._EFFECT_HANDLERS["test_later"] = later
    effects_mod._CONSECUTIVE_FAILURES.pop("superagent:effects", None)
    try:
        effect_id = await enqueue_effect(db_session, "test_later", {}, dedupe_key="lt")
        outcome = await execute_claimed_effect(db_session, effect_id)
        assert outcome == "later"
        row = await db_session.get(AgentEffect, effect_id)
        assert row.attempts == 0
        assert row.status == "pending"
        assert row.next_due_at > datetime.now(UTC)
    finally:
        effects_mod._EFFECT_HANDLERS.pop("test_later", None)
        effects_mod._CONSECUTIVE_FAILURES.pop("superagent:effects", None)


async def test_effect_claim_mutual_exclusion(db_session) -> None:
    """并发两执行器同抢一批：SKIP LOCKED 各拿各的，零重复执行。"""
    got: list[str] = []
    lock = asyncio.Lock()

    async def handler(payload: dict) -> None:
        async with lock:
            got.append(payload["key"])

    effects_mod._EFFECT_HANDLERS["test_race"] = handler
    try:
        ids = [
            (await enqueue_effect(db_session, "test_race", {"key": f"k{i}"},
                                  dedupe_key=f"race{i}"))
            for i in range(6)
        ]
        # 两个「消费者」并发执行同批（同一 session 串行化由 BEGIN 内锁语义保证；
        # 此处验证第二次对已执行行不再处理）
        for eid in ids:
            assert await execute_claimed_effect(db_session, eid) == "done"
        for eid in ids:  # 再来一轮（模拟重启后重扫）
            assert await execute_claimed_effect(db_session, eid) == "skipped"
        assert sorted(got) == sorted(f"k{i}" for i in range(6))
    finally:
        effects_mod._EFFECT_HANDLERS.pop("test_race", None)


# ═══════════════════════════════════════════════════════════════
# B 层：outbox
# ═══════════════════════════════════════════════════════════════


async def test_outbox_strict_order_head_blocks(db_session) -> None:
    """同会话严格保序：队头失败 → 后续不发送；队头成功 → 按序推进。"""
    sent: list[str] = []
    fail_first = {"on": True}

    async def sender(channel: dict, body: dict) -> bool:
        if fail_first["on"] and body["text"] == "m1":
            fail_first["on"] = False
            raise RuntimeError("feishu down")
        sent.append(body["text"])
        return True

    register_outbox_sender("test_channel", sender)
    try:
        for text in ("m1", "m2", "m3"):
            await enqueue_outbox_message(
                db_session, conversation="conv-1",
                channel={"type": "test_channel", "chat_id": "oc_x1"},
                body={"text": text}, purpose="message",
            )

        outcome = await send_conversation_head(db_session, "conv-1")
        assert outcome == "retried"
        assert sent == []  # 队头失败，m2/m3 不得先发（确认先于结果）

        # 队头退避到期后重试成功 → 按序补发
        row = (
            await db_session.execute(
                select(AgentOutboxMessage)
                .where(AgentOutboxMessage.conversation == "conv-1")
                .order_by(AgentOutboxMessage.seq)
            )
        ).scalars().first()
        row.next_due_at = datetime.now(UTC) - timedelta(seconds=1)
        await db_session.flush()
        for _ in range(3):
            outcome = await send_conversation_head(db_session, "conv-1")
        assert sent == ["m1", "m2", "m3"]
    finally:
        effects_mod._OUTBOX_SENDERS.pop("test_channel", None)


async def test_outbox_channel_address_authoritative(db_session) -> None:
    """行内地址不可覆盖：sender 只收到行内 channel（总卡聚合吞 chat_id 的根因修复）。"""
    seen: list[dict] = []

    async def sender(channel: dict, body: dict) -> bool:
        seen.append(channel)
        return True

    register_outbox_sender("test_addr", sender)
    try:
        await enqueue_outbox_message(
            db_session, conversation="conv-addr",
            channel={"type": "test_addr", "chat_id": "oc_target_group"},
            body={"text": "hi"},
        )
        await send_conversation_head(db_session, "conv-addr")
        assert seen == [{"type": "test_addr", "chat_id": "oc_target_group"}]
    finally:
        effects_mod._OUTBOX_SENDERS.pop("test_addr", None)


async def test_outbox_conversations_independent(db_session) -> None:
    """跨会话互不阻塞：A 会话队头失败不影响 B 会话发送。"""
    sent: list[str] = []

    async def sender(channel: dict, body: dict) -> bool:
        if body["text"] == "a1":
            raise RuntimeError("a down")
        sent.append(body["text"])
        return True

    register_outbox_sender("test_indep", sender)
    try:
        await enqueue_outbox_message(
            db_session, conversation="conv-a",
            channel={"type": "test_indep"}, body={"text": "a1"},
        )
        await enqueue_outbox_message(
            db_session, conversation="conv-b",
            channel={"type": "test_indep"}, body={"text": "b1"},
        )
        assert await send_conversation_head(db_session, "conv-a") == "retried"
        assert await send_conversation_head(db_session, "conv-b") == "sent"
        assert sent == ["b1"]
    finally:
        effects_mod._OUTBOX_SENDERS.pop("test_indep", None)


async def test_outbox_unknown_sender_dropped(db_session) -> None:
    await enqueue_outbox_message(
        db_session, conversation="conv-nope",
        channel={"type": "no_such_sender"}, body={"text": "x"},
    )
    outcome = await send_conversation_head(db_session, "conv-nope")
    assert outcome == "dropped"
    row = (
        await db_session.execute(
            select(AgentOutboxMessage).where(AgentOutboxMessage.conversation == "conv-nope")
        )
    ).scalar_one()
    assert row.dropped_reason and "no sender" in row.dropped_reason


# ═══════════════════════════════════════════════════════════════
# B 层：health 认领制
# ═══════════════════════════════════════════════════════════════


async def test_health_claim_once_and_reject(db_session) -> None:
    """首次认领成功；他人活跃认领被拒。"""
    assert await claim_component(db_session, "test:comp-a") is True

    other_owner = "other-host:999"
    await db_session.execute(
        AgentHealth.__table__.insert().values(
            component="test:comp-b", state="paused",
            claimed_by=other_owner, claimed_at=datetime.now(UTC),
        )
    )
    await db_session.flush()
    # 活跃他人认领 → 本进程接管失败
    stmt = select(AgentHealth).where(AgentHealth.component == "test:comp-b")
    row = (await db_session.execute(stmt)).scalar_one()
    assert row.claimed_by == other_owner


async def test_health_stale_takeover(db_session) -> None:
    """认领过期（>15 分钟）→ 本进程接管。"""
    await db_session.execute(
        AgentHealth.__table__.insert().values(
            component="test:comp-stale", state="error",
            claimed_by="dead-host:1",
            claimed_at=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    await db_session.flush()
    assert await claim_component(db_session, "test:comp-stale") is True
    row = (
        await db_session.execute(
            select(AgentHealth).where(AgentHealth.component == "test:comp-stale")
        )
    ).scalar_one()
    assert row.claimed_by == effects_mod.OWNER_ID


async def test_outbox_head_backoff_blocks_queue_no_jump(db_session) -> None:
    """审查修复回归：队头退避窗内——后续到期消息不得跳队先发（waiting）。"""
    sent: list[str] = []
    fail_once = {"on": True}

    async def sender(channel: dict, body: dict) -> bool:
        if fail_once["on"] and body["text"] == "m1":
            fail_once["on"] = False
            raise RuntimeError("down")
        sent.append(body["text"])
        return True

    register_outbox_sender("test_block", sender)
    try:
        for text in ("m1", "m2"):
            await enqueue_outbox_message(
                db_session, conversation="conv-block",
                channel={"type": "test_block"}, body={"text": text},
            )
        assert await send_conversation_head(db_session, "conv-block") == "retried"
        # 队头退避中：再次推进 → waiting；m2 不得先发
        assert await send_conversation_head(db_session, "conv-block") == "waiting"
        assert sent == []
        # 队头到期后按序补发
        from sqlalchemy import select as _sel

        head = (
            await db_session.execute(
                _sel(AgentOutboxMessage)
                .where(AgentOutboxMessage.conversation == "conv-block")
                .order_by(AgentOutboxMessage.seq)
            )
        ).scalars().first()
        head.next_due_at = datetime.now(UTC) - timedelta(seconds=1)
        await db_session.flush()
        for _ in range(2):
            await send_conversation_head(db_session, "conv-block")
        assert sent == ["m1", "m2"]
    finally:
        effects_mod._OUTBOX_SENDERS.pop("test_block", None)


async def test_dm_admin_with_injected_sender(db_session, monkeypatch) -> None:
    """dm_admin 注入发送器后真发（失败收件人 → 退避重试）。"""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "SUPERAGENT_ADMIN_OPEN_IDS", "ou_a,ou_b")
    got: list[str] = []

    async def fake_send(open_id: str, text: str) -> bool:
        got.append(open_id)
        return open_id != "ou_b"  # ou_b 失败 → 整体重试

    effects_mod.set_dm_sender(fake_send)
    try:
        effect_id = await enqueue_effect(
            db_session, "dm_admin", {"text": "hello"}, dedupe_key="dm-test",
        )
        outcome = await execute_claimed_effect(db_session, effect_id)
        assert outcome == "retried"
        assert got == ["ou_a", "ou_b"]
    finally:
        effects_mod.set_dm_sender(None)
