"""R1 消防联动全链 —— 扫描→observe 只记→转正→执行器建隐患→links→outbox。

一条测试证明 §9.2 数据流端到端成立（C 层接缝）；observe 红线：
只记 Decision，零任务零 effect 零 outbox。
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.schema import CreateIndex, CreateTable

from app.modules.safety.models.alarm_hazard_link import AlarmHazardLink

_SRC_NAME = "safety.fire_alarm.r1"


class FakeBitableClient:
    def __init__(self) -> None:
        self.create_calls: list[dict] = []

    async def list_fields(self, table_id: str | None = None) -> list[dict[str, Any]]:
        return [{"field_name": "关联报警"}]  # 已有列：ensure 零建列

    async def create_field(self, *a, **kw) -> dict:  # noqa: ANN002, ANN003
        return {}

    async def create_record(self, fields: dict[str, Any], table_id: str | None = None):
        self.create_calls.append(fields)
        return {"record_id": "hzChain001", "shared_url": "u"}


def _alarm(rid: str, nature: str, cause: str, closure: str) -> dict:
    return {
        "record_id": rid,
        "fields": {
            "报警性质": nature, "报警原因分类": cause,
            "处理情况": [{"type": "text", "text": closure}],
            "报警时间": 1793630412844,
            "报警类型": "火灾报警",
            "报警部门负责人.部门": ["提炼工程一部"],
            "报警楼栋": "提三",
            "报警部位": [{"type": "text", "text": "1楼罐区"}],
            "具体报警原因": [{"type": "text", "text": "接浓氨挥发"}],
        },
        "last_modified_time": 1793630412844,
    }


@pytest_asyncio.fixture(autouse=True)
async def _purge_chain_rows():
    """执行器/端点内 commit 会穿透回滚语义——用例后清理 R1 全链行。"""
    yield
    from app.platform.superagent.models import (
        AgentDecision,
        AgentInput,
        AgentOutboxMessage,
        AgentSource,
        AgentTask,
        AgentTaskSubscription,
        AgentTrigger,
    )
    from tests.conftest import _test_session_factory

    async with _test_session_factory() as s:
        tids: list = []
        for src in (
            await s.execute(
                select(AgentSource).where(AgentSource.name == _SRC_NAME)
            )
        ).scalars().all():
            for t in (
                await s.execute(
                    select(AgentTrigger).where(AgentTrigger.source_id == src.id)
                )
            ).scalars().all():
                tids.append(t.id)
                await s.execute(
                    AgentDecision.__table__.delete().where(AgentDecision.trigger_id == t.id)
                )
                await s.execute(
                    AgentInput.__table__.delete().where(AgentInput.trigger_id == t.id)
                )
                await s.delete(t)
            await s.delete(src)
        for task in (
            await s.execute(
                select(AgentTask).where(AgentTask.origin_trigger_id.in_(tids or [uuid_zero()]))
            )
        ).scalars().all():
            await s.execute(
                AgentInput.__table__.delete().where(AgentInput.task_id == task.id)
            )
            await s.execute(
                AgentTaskSubscription.__table__.delete().where(
                    AgentTaskSubscription.task_id == task.id
                )
            )
            await s.execute(
                AgentOutboxMessage.__table__.delete().where(AgentOutboxMessage.task_id == task.id)
            )
            await s.delete(task)
        await s.execute(
            AgentOutboxMessage.__table__.delete().where(
                AgentOutboxMessage.conversation.like("r1_fire:%")
            )
        )
        await s.execute(
            AlarmHazardLink.__table__.delete().where(
                AlarmHazardLink.alarm_record_id.in_(["recHit1", "recHit2", "recNoise"])
            )
        )
        await s.commit()


def uuid_zero():
    import uuid

    return uuid.UUID("00000000-0000-0000-0000-000000000000")


@pytest_asyncio.fixture
async def chain_env(db_session):
    """links 表 + R1 Source 行（enabled）+ observe Policy，共享 session 给执行器。"""
    # 测试进程无 bootstrap：注册 cron_scan 源/执行器/outbox sender（幂等）
    from app.modules.safety.superagent_bridge import register_superagent_bridge

    register_superagent_bridge()

    from app.modules.safety.service.alarm_hazard_r1.rule import r1_fire_rule
    from app.platform.superagent.models import AgentSource
    from app.platform.superagent.policy import apply_new_policy

    await db_session.execute(CreateTable(AlarmHazardLink.__table__, if_not_exists=True))
    for idx in AlarmHazardLink.__table__.indexes:
        await db_session.execute(CreateIndex(idx, if_not_exists=True))
    src = AgentSource(
        kind="cron_scan", name=_SRC_NAME, enabled=True,
        config={
            "schedule": {"strategy": "cron", "expression": "15 17 * * *",
                          "timezone": "Asia/Shanghai"},
            "window_days": 7,
            "relevant_fields": ["报警性质", "报警原因分类", "处理情况"],
            "evaluate": True, "thread_prefix": "fire_alarm",
        },
    )
    db_session.add(src)
    await db_session.flush()
    policy, _ = await apply_new_policy(
        db_session, rules=[r1_fire_rule()], accept_mode="observe",
    )
    await db_session.flush()
    yield {"source": src, "policy": policy}


async def _scan_once(db_session, monkeypatch, records) -> dict:
    """跑一轮 ingest（patch 窗口拉取 + cursor 直推到已到期）。"""
    from datetime import UTC, datetime, timedelta

    from app.modules.safety.service.alarm_hazard_r1 import scan_source
    from app.platform.superagent.ingest import apply_cursor_updates, ingest_source_once

    async def _fetch(days: int):
        return list(records)

    monkeypatch.setattr(scan_source, "fetch_fire_alarm_window", _fetch)
    # 恒到期：脱离真实 17:15 时钟（每轮 poll 都视为跨过触发点）
    monkeypatch.setattr(
        scan_source, "due_fire_times",
        lambda schedule, last, now, **kw: [now],
    )
    src_row = (
        await db_session.execute(
            select(_model_source()).where(_model_source().name == _SRC_NAME)
        )
    ).scalar_one()
    # 读位置到过期（触发点网格内），保证 poll 到期拉窗
    await apply_cursor_updates(
        db_session, src_row.id,
        {"last_tick": (datetime.now(UTC) - timedelta(hours=2)).isoformat()},
    )
    return await ingest_source_once(db_session, src_row)


def _model_source():
    from app.platform.superagent.models import AgentSource

    return AgentSource


async def test_full_chain_observe_then_promote(
    db_session, chain_env, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.platform.superagent.models import (
        AgentDecision,
        AgentEffect,
        AgentOutboxMessage,
        AgentTask,
    )
    from app.platform.superagent.policy import resolve_decision

    records = [
        _alarm("recHit1", "泄漏报警", "氨水引发", "已恢复系统"),        # 白名单命中
        _alarm("recHit2", "误报", "蒸汽引发", "已通知仪表处理"),        # 闭环命中
        _alarm("recNoise", "误报", "蒸汽引发", "22:50恢复系统"),        # 纯噪音
    ]

    # ── 第一轮：扫描 → observe 只记 ──
    summary = await _scan_once(db_session, monkeypatch, records)
    assert summary["stored"] == 3
    decisions = (
        await db_session.execute(
            select(AgentDecision).where(AgentDecision.replay.is_(False))
        )
    ).scalars().all()
    assert len(decisions) == 3
    hits = [d for d in decisions if d.would_accept]
    assert len(hits) == 2  # 白名单 + 闭环；噪音不进
    # observe 红线：零任务零 effect 零 outbox（按 R1 范围过滤，防开发库既有行污染）
    assert (
        await db_session.execute(
            select(func.count()).select_from(AgentTask).where(
                AgentTask.executor == "alarm_hazard_create"
            )
        )
    ).scalar_one() == 0
    assert (
        await db_session.execute(
            select(func.count()).select_from(AgentEffect).where(
                AgentEffect.kind == "dm_admin"  # 任意入队皆不该发生，取已知 kind 抽查
            )
        )
    ).scalar_one() == 0
    assert (
        await db_session.execute(
            select(func.count()).select_from(AgentOutboxMessage).where(
                AgentOutboxMessage.conversation.like("r1_fire:%")
            )
        )
    ).scalar_one() == 0

    # ── 重扫同批：duplicate 幂等零新增 ──
    summary2 = await _scan_once(db_session, monkeypatch, records)
    assert summary2["stored"] == 0
    assert summary2["duplicate"] == 3
    decisions2 = (
        await db_session.execute(
            select(func.count()).select_from(AgentDecision).where(
                AgentDecision.replay.is_(False)  # 真机 replay 行不污染在线计数
            )
        )
    ).scalar_one()
    assert decisions2 == 3  # 不重复研判

    # ── 转正白名单命中 → 执行器建隐患 → links 回填 → outbox 卡 ──
    hit_decision = hits[0]
    await resolve_decision(
        db_session, hit_decision, resolution="promoted", resolved_by="admin-1",
    )
    await db_session.flush()
    task = (
        await db_session.execute(
            select(AgentTask).where(AgentTask.executor == "alarm_hazard_create")
        )
    ).scalar_one()
    assert task.executor == "alarm_hazard_create"
    assert task.mandate["strength"] == "promoted"

    fake = FakeBitableClient()
    monkeypatch.setattr(
        "app.modules.safety.feishu.bitable_client.SafetyBitableClient", lambda: fake,
    )
    monkeypatch.setenv("SAFETY_R1_FIRE_CARD_CHAT_ID", "oc_chain")
    # 执行器自开 session → 复用 db_session（patch factory）
    class _Ctx:
        def __init__(self, session):
            self._session = session

        async def __aenter__(self):
            return self._session

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(
        "app.core.database.async_session_factory", lambda: _Ctx(db_session),
    )

    from app.modules.safety.service.alarm_hazard_r1.executor import alarm_hazard_create
    from app.platform.superagent.executors import register_executor

    try:
        register_executor("alarm_hazard_create", alarm_hazard_create)
    except ValueError:
        pass
    from app.platform.superagent.executors import run_task_once

    outcome = await run_task_once(db_session, task.id)
    assert outcome == "ran"
    await db_session.flush()

    assert len(fake.create_calls) == 1
    sent = fake.create_calls[0]
    assert sent["整改状态"] == "未关闭"
    assert sent["关联报警"].startswith("fire_alarm:rec")
    links = (
        await db_session.execute(select(AlarmHazardLink))
    ).scalars().all()
    assert len(links) == 1
    assert links[0].hazard_record_id == "hzChain001"
    assert links[0].decided_by == "admin-1"

    outbox = (
        await db_session.execute(
            select(AgentOutboxMessage).where(
                AgentOutboxMessage.conversation.like("r1_fire:%")
            )
        )
    ).scalars().all()
    assert len(outbox) == 1
    assert outbox[0].channel["chat_id"] == "oc_chain"

    # 任务终态 ready
    await db_session.refresh(task)
    assert task.status == "ended" and task.outcome == "ready"

    # ── 忽略路径：另一条命中 dismissed → 终态不开任务 ──
    other = next(d for d in hits if d.id != hit_decision.id)
    await resolve_decision(db_session, other, resolution="dismissed", resolved_by="admin-1")
    tasks_final = (
        await db_session.execute(
            select(func.count()).select_from(AgentTask).where(
                AgentTask.executor == "alarm_hazard_create"
            )
        )
    ).scalar_one()
    assert tasks_final == 1  # 仍只有转正那一条
    await db_session.rollback()


async def test_ensure_r1_policy_upgrades_rules_keeps_mode(
    db_session, chain_env,
) -> None:
    """ensure_r1_policy：规则内容变化 → 升新版本；现行 accept_mode 保留不被覆盖。"""
    from app.modules.safety.superagent_bridge import ensure_r1_policy
    from app.platform.superagent.models import AgentPolicy
    from app.platform.superagent.policy import apply_new_policy

    # 现行 = chain_env 播的 observe 基线 → 人工切 auto 模拟
    await apply_new_policy(
        db_session,
        rules=[{"rule_id": "legacy", "enabled": True, "source": "x", "conditions": []}],
        accept_mode="auto",
    )
    await db_session.flush()

    await ensure_r1_policy(session=db_session)

    # 同事务多版本 created_at 同秒（server_default now()），current 取序不稳定——
    # 按存在性断言：R1 规则集 + 沿用 auto 的版本行已落（生产中版本间隔远大于时钟精度）
    rows = (
        await db_session.execute(
            select(AgentPolicy).order_by(AgentPolicy.created_at.desc())
        )
    ).scalars().all()
    r1_rows = [
        r for r in rows
        if any(x.get("rule_id") == "fire_alarm_candidate" for x in (r.rules or []))
    ]
    assert r1_rows, "R1 规则版本未落库"
    # chain_env 先播过 R1+observe 基线；legacy-auto 之上 ensure 升版须沿用 auto
    assert any(r.accept_mode == "auto" for r in r1_rows), "升版未沿用人工 auto"
    n = (
        await db_session.execute(select(func.count()).select_from(AgentPolicy))
    ).scalar_one()
    assert n >= 3  # 基线/legacy/R1 升版 版本追加不删除历史
    await db_session.rollback()
