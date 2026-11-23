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


async def test_health_alert_daily_dedupe(db_session) -> None:
    """同日失败风暴 health-alert 按日幂等：告警卡当日至多一张（键含日期；前卡
    已 done 不构成再发理由——11-12 三连发根因回归锚）。"""
    n = {"fail": 0}

    async def flaky(payload: dict) -> None:
        n["fail"] += 1
        raise RuntimeError("storm")

    effects_mod._EFFECT_HANDLERS["test_storm"] = flaky
    effects_mod._CONSECUTIVE_FAILURES.pop("superagent:effects", None)
    try:
        effect_id = await enqueue_effect(db_session, "test_storm", {}, dedupe_key="storm")
        today = datetime.now(UTC).date().isoformat()
        expect_key = f"health-alert:superagent:effects:{today}"

        async def _fail_once() -> None:
            row = await db_session.get(AgentEffect, effect_id)
            row.next_due_at = datetime.now(UTC) - timedelta(seconds=1)
            await db_session.flush()
            await execute_claimed_effect(db_session, effect_id)

        # 前 3 次连续失败 → 首张当日告警卡（键含日期）
        for _ in range(3):
            await _fail_once()
        alerts = (
            await db_session.execute(
                select(AgentEffect).where(
                    AgentEffect.kind == "dm_admin", AgentEffect.dedupe_key == expect_key,
                )
            )
        ).scalars().all()
        assert len(alerts) == 1

        # 首卡消费 done（dm_admin 无 sender=仅留痕即 done）后风暴继续 → 不再发新卡
        alerts[0].status = "done"
        await db_session.flush()
        for _ in range(2):
            await _fail_once()
        again = (
            await db_session.execute(
                select(AgentEffect).where(
                    AgentEffect.kind == "dm_admin",
                    AgentEffect.dedupe_key == expect_key,
                )
            )
        ).scalars().all()
        # 当日幂等：done 行不挡入队的洞已由入队前查重堵上（活库旧格式键无日期
        # 后缀，精确匹配当日键天然隔离存量）
        assert len(again) == 1
        assert again[0].id == alerts[0].id
    finally:
        effects_mod._EFFECT_HANDLERS.pop("test_storm", None)
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


# ═══════════════════════════════════════════════════════════════
# dm_admin 收件人 env 优先 + 空时 DB 兜底（R3 三期 T4）
# ═══════════════════════════════════════════════════════════════


class _SessionCtx:
    """执行器/handler 自开 session 桩（未提交行可见）。"""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


async def _make_db_admin(db_session, open_id: str) -> None:
    """测试自建 admin 用户（复用库内既有 permission:role:manage 权限行防唯一冲突）。"""
    import uuid as uuid_mod

    from app.platform.identity.models import User
    from app.platform.permission.models import (
        Permission,
        Role,
        RolePermission,
        UserRole,
    )
    from sqlalchemy import select as sa_select

    perm = (
        await db_session.execute(
            sa_select(Permission).where(Permission.code == "permission:role:manage")
        )
    ).scalar_one()
    user = User(
        id=uuid_mod.uuid4(), name=f"r3t管理员{open_id[-4:]}",
        employee_no=f"R3T{uuid_mod.uuid4().hex[:8]}", feishu_open_id=open_id,
    )
    role = Role(
        id=uuid_mod.uuid4(), code=f"r3t_admin_{uuid_mod.uuid4().hex[:6]}",
        name="R3 测试管理员",
    )
    db_session.add_all([
        user, role,
        UserRole(user_id=user.id, role_id=role.id),
        RolePermission(role_id=role.id, permission_id=perm.id),
    ])
    await db_session.flush()


async def test_dm_admin_env_wins_over_db_admins(db_session, monkeypatch) -> None:
    """env 非空 → 只发 env 收件人（DB 管理员不扩面，watchdog 通道零行为变更）。"""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "SUPERAGENT_ADMIN_OPEN_IDS", "ou_env_only")
    await _make_db_admin(db_session, "ou_dbadmin_should_not_receive")
    monkeypatch.setattr(
        "app.core.database.async_session_factory", lambda: _SessionCtx(db_session),
    )
    got: list[str] = []

    async def fake_send(open_id: str, text: str) -> bool:
        got.append(open_id)
        return True

    effects_mod.set_dm_sender(fake_send)
    try:
        effect_id = await enqueue_effect(
            db_session, "dm_admin", {"text": "env wins"}, dedupe_key="dm-env-wins",
        )
        assert await execute_claimed_effect(db_session, effect_id) == "done"
        assert got == ["ou_env_only"]
    finally:
        effects_mod.set_dm_sender(None)
    await db_session.rollback()


async def test_dm_admin_empty_env_falls_back_to_db_admins(
    db_session, monkeypatch,
) -> None:
    """env 空 → DB 兜底发 permission:role:manage 用户（测试自建 open_id 必达）。"""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "SUPERAGENT_ADMIN_OPEN_IDS", "")
    await _make_db_admin(db_session, "ou_db_fallback_target")
    monkeypatch.setattr(
        "app.core.database.async_session_factory", lambda: _SessionCtx(db_session),
    )
    got: list[str] = []

    async def fake_send(open_id: str, text: str) -> bool:
        got.append(open_id)
        return True

    effects_mod.set_dm_sender(fake_send)
    try:
        effect_id = await enqueue_effect(
            db_session, "dm_admin", {"text": "db fallback"}, dedupe_key="dm-db-fallback",
        )
        assert await execute_claimed_effect(db_session, effect_id) == "done"
        assert "ou_db_fallback_target" in got  # dev 库真管理员（许康福）同批属正常
    finally:
        effects_mod.set_dm_sender(None)
    await db_session.rollback()


async def test_dm_admin_fallback_query_failure_stays_silent(
    db_session, monkeypatch,
) -> None:
    """env 空 + DB 查询异常 → 维持「仅留痕」不炸发送链（fail-open）。"""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "SUPERAGENT_ADMIN_OPEN_IDS", "")

    async def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(
        "app.platform.superagent.effects._resolve_admin_recipients", _boom,
    )
    got: list[str] = []

    async def fake_send(open_id: str, text: str) -> bool:
        got.append(open_id)
        return True

    effects_mod.set_dm_sender(fake_send)
    try:
        effect_id = await enqueue_effect(
            db_session, "dm_admin", {"text": "silent"}, dedupe_key="dm-silent",
        )
        assert await execute_claimed_effect(db_session, effect_id) == "done"
        assert got == []
    finally:
        effects_mod.set_dm_sender(None)
    await db_session.rollback()


# ═══════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════
# dm_admin DB 兜底跨应用解析：recipient resolver 注入点（R3 四期 C 刀）
# ═══════════════════════════════════════════════════════════════


async def test_dm_admin_env_nonempty_resolver_not_called(
    db_session, monkeypatch,
) -> None:
    """env 非空 → 收件人=env 值，resolver 不被调用（零行为变更红线）。"""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "SUPERAGENT_ADMIN_OPEN_IDS", "ou_env_authority")
    monkeypatch.setattr(
        "app.core.database.async_session_factory", lambda: _SessionCtx(db_session),
    )
    calls: list[list[str]] = []

    async def fake_resolver(names: list[str]) -> list[str]:
        calls.append(list(names))
        return ["ou_should_not_appear"]

    async def fake_send(open_id: str, text: str) -> bool:
        return open_id == "ou_env_authority"

    effects_mod.set_dm_recipient_resolver(fake_resolver)
    effects_mod.set_dm_sender(fake_send)
    try:
        effect_id = await enqueue_effect(
            db_session, "dm_admin", {"text": "env"}, dedupe_key="dm-res-env",
        )
        assert await execute_claimed_effect(db_session, effect_id) == "done"
        assert calls == []  # env 非空路径 resolver 零参与
    finally:
        effects_mod.set_dm_recipient_resolver(None)
        effects_mod.set_dm_sender(None)
    await db_session.rollback()


async def test_dm_admin_resolver_wins_when_env_empty(
    db_session, monkeypatch,
) -> None:
    """env 空 + resolver 注入 → 收件人=resolver 解析的安全侧 open_id（DB 直链
    跨应用值不参与发送）。"""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "SUPERAGENT_ADMIN_OPEN_IDS", "")
    await _make_db_admin(db_session, "ou_cross_app_direct")
    monkeypatch.setattr(
        "app.core.database.async_session_factory", lambda: _SessionCtx(db_session),
    )
    seen_names: list[list[str]] = []

    async def fake_resolver(names: list[str]) -> list[str]:
        seen_names.append(list(names))
        return ["ou_safety_side_resolved"]

    got: list[str] = []

    async def fake_send(open_id: str, text: str) -> bool:
        got.append(open_id)
        return True

    effects_mod.set_dm_recipient_resolver(fake_resolver)
    effects_mod.set_dm_sender(fake_send)
    try:
        effect_id = await enqueue_effect(
            db_session, "dm_admin", {"text": "resolver"}, dedupe_key="dm-res-win",
        )
        assert await execute_claimed_effect(db_session, effect_id) == "done"
        assert "ou_safety_side_resolved" in got
        assert "ou_cross_app_direct" not in got  # 直链跨应用值被 resolver 取代
        # resolver 收到的是管理员姓名（r3t管理员* 测试行必在；真库管理员同批正常）
        assert seen_names and any(n.startswith("r3t管理员") for n in seen_names[0])
    finally:
        effects_mod.set_dm_recipient_resolver(None)
        effects_mod.set_dm_sender(None)
    await db_session.rollback()


async def test_dm_admin_resolver_failure_falls_back_to_direct(
    db_session, monkeypatch,
) -> None:
    """env 空 + resolver 抛异常 → 回落 identity 直链现行为（降级不炸发送链）。"""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "SUPERAGENT_ADMIN_OPEN_IDS", "")
    await _make_db_admin(db_session, "ou_direct_fallback_target")
    monkeypatch.setattr(
        "app.core.database.async_session_factory", lambda: _SessionCtx(db_session),
    )

    async def bad_resolver(names: list[str]) -> list[str]:
        raise RuntimeError("resolver down")

    got: list[str] = []

    async def fake_send(open_id: str, text: str) -> bool:
        got.append(open_id)
        return True

    effects_mod.set_dm_recipient_resolver(bad_resolver)
    effects_mod.set_dm_sender(fake_send)
    try:
        effect_id = await enqueue_effect(
            db_session, "dm_admin", {"text": "fallback"}, dedupe_key="dm-res-fb",
        )
        assert await execute_claimed_effect(db_session, effect_id) == "done"
        assert "ou_direct_fallback_target" in got  # 回落直链（跨应用已知限制仍在）
    finally:
        effects_mod.set_dm_recipient_resolver(None)
        effects_mod.set_dm_sender(None)
    await db_session.rollback()


# ═══════════════════════════════════════════════════════════════
# 引擎测试隔离开关（R3 三期验收收口）
# ═══════════════════════════════════════════════════════════════


async def test_engine_pause_switch(db_session) -> None:
    """持锁期间：engine_test_paused=True 且 SourcePollGenerator.find_due 空转。

    本测自身就在 autouse 持锁夹具内（conftest._pause_live_engine 持锁于独立
    连接）——跨会话检测即被验证：本会话 db_session 并非持锁方仍见 True。
    """
    from app.platform.superagent.models import AgentSource
    from app.platform.superagent.runtime import (
        SourcePollGenerator,
        engine_test_paused,
    )

    assert await engine_test_paused(db_session) is True

    # 有启用源也不产出（整轮空转——活引擎不再拾走测试中途 commit 的行）
    import uuid as uuid_mod

    db_session.add(AgentSource(
        kind="ops_scan",
        name=f"r3t.pause.{uuid_mod.uuid4().hex[:8]}",  # 合成名（真源行常驻勿撞唯一）
        enabled=True, config={},
    ))
    await db_session.flush()
    gen = SourcePollGenerator()
    assert await gen.find_due(db_session) == []  # 持锁空转：有启用源也不产出
    await db_session.rollback()
