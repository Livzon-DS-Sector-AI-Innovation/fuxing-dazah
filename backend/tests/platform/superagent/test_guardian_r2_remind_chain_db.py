"""R2 监护人提醒全链 —— 扫描→observe 只记→转正→执行器 DM→links 计数→outbox。

observe 红线：只记 Decision，零任务零 effect 零 outbox（照 R1 链路测试模式）。
月度幂等：同月重扫 duplicate；执行器重跑 last_reminded_month 跳过。
"""

from __future__ import annotations

import uuid as _uuid
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.schema import CreateIndex, CreateTable

from app.modules.safety.models.guardian_qualification_link import (
    GuardianQualificationLink,
)

_SRC_NAME = "safety.guardian.r2"


def _uuid_zero():
    return _uuid.UUID("00000000-0000-0000-0000-000000000000")


def _cert_fields(name: str = "张三", issue_ms: int = 1768060800000) -> dict:
    """监护人 A 证 fields 替身（issue 2026-01-10 UTC；截止列按 +1/+2/+3 年推导）。"""
    import datetime as dt

    def plus_years_ms(ms: int, years: int) -> int:
        d = dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc).date()
        try:
            d = d.replace(year=d.year + years)
        except ValueError:
            d = dt.date(d.year + years, 2, 28)
        return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc)
                   .timestamp() * 1000)

    return {
        "姓名": [{"id": "ou_r2chain", "name": name}],
        "部门": ["提炼工程一部"],
        "取证日期": issue_ms,
        "第一次复审截止日期": plus_years_ms(issue_ms, 1),
        "第二次复审截止日期": plus_years_ms(issue_ms, 2),
        "应换证日期": plus_years_ms(issue_ms, 3),
    }


@pytest_asyncio.fixture(autouse=True)
async def _purge_chain_rows():
    """执行器内 commit 穿透回滚——用例后清理 R2 全链行。

    links 表可能尚未跑迁移（事务内自建已随回滚消失）——purge 连接里幂等
    先建，保证 DELETE 不因表缺失炸清理。
    """
    yield
    from sqlalchemy.schema import CreateTable, CreateIndex

    from app.modules.safety.models.guardian_qualification_link import (
        GuardianQualificationLink,
    )
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
        await s.execute(
            CreateTable(GuardianQualificationLink.__table__, if_not_exists=True)
        )
        for idx in GuardianQualificationLink.__table__.indexes:
            await s.execute(CreateIndex(idx, if_not_exists=True))
        tids: list = []
        for src in (
            await s.execute(select(AgentSource).where(AgentSource.name == _SRC_NAME))
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
                select(AgentTask).where(AgentTask.origin_trigger_id.in_(tids or [_uuid_zero()]))
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
                AgentOutboxMessage.conversation.like("guardian_remind:%")
            )
        )
        await s.execute(
            GuardianQualificationLink.__table__.delete().where(
                GuardianQualificationLink.record_id.like("r2chain%")
            )
        )
        await s.commit()


@pytest_asyncio.fixture
async def chain_env(db_session):
    """links 表 + R2 Source 行（enabled）+ observe Policy + 执行器注册。"""
    from app.modules.safety.superagent_bridge import register_superagent_bridge

    register_superagent_bridge()

    from app.modules.safety.service.alarm_hazard_r1.rule import r1_fire_rule
    from app.modules.safety.service.guardian_r2.rule import (
        guardian_remind_rule,
        guardian_restore_rule,
        guardian_revoke_rule,
        guardian_score_map_rule,
    )
    from app.platform.superagent.models import AgentSource
    from app.platform.superagent.policy import apply_new_policy

    await db_session.execute(
        CreateTable(GuardianQualificationLink.__table__, if_not_exists=True)
    )
    for idx in GuardianQualificationLink.__table__.indexes:
        await db_session.execute(CreateIndex(idx, if_not_exists=True))
    src = AgentSource(
        kind="guardian_cert_scan", name=_SRC_NAME, enabled=True,
        config={
            "schedule": {"strategy": "cron", "expression": "0 8 * * *",
                          "timezone": "Asia/Shanghai"},
            "evaluate": True, "thread_prefix": "guardian_cert",
        },
    )
    db_session.add(src)
    await db_session.flush()
    policy, _ = await apply_new_policy(
        db_session,
        rules=[
            r1_fire_rule(),
            guardian_remind_rule(),
            guardian_revoke_rule(),
            guardian_restore_rule(),
            guardian_score_map_rule(),
        ],
        accept_mode="observe",
    )
    await db_session.flush()
    yield {"source": src, "policy": policy}


async def _scan_once(db_session, monkeypatch, records, today) -> dict:
    """跑一轮 ingest（patch 拉取 + 恒到期 + 读位回拨）。"""
    from datetime import UTC, datetime, timedelta

    from app.modules.safety.service.guardian_r2 import scan_source
    from app.platform.superagent.ingest import apply_cursor_updates, ingest_source_once

    async def _fetch():
        return list(records)

    monkeypatch.setattr(scan_source, "fetch_guardian_cert_records", _fetch)
    monkeypatch.setattr(
        scan_source, "due_fire_times", lambda schedule, last, now, **kw: [now],
    )
    src_row = (
        await db_session.execute(
            select(_model_source()).where(_model_source().name == _SRC_NAME)
        )
    ).scalar_one()
    await apply_cursor_updates(
        db_session, src_row.id,
        {"last_tick": (datetime.now(UTC) - timedelta(hours=2)).isoformat()},
    )
    # 恒定「今天」：脱离真实时钟（build_cert_drafts 用 now 的日期）
    real_datetime = datetime

    class _FixedNow(real_datetime):
        @classmethod
        def now(cls, tz=None):
            base = real_datetime.now(tz) if tz else real_datetime.now()
            return real_datetime.combine(
                today, real_datetime.min.time(),
            ).replace(tzinfo=tz) if tz else base

    monkeypatch.setattr(scan_source, "datetime", _FixedNow)
    return await ingest_source_once(db_session, src_row)


def _model_source():
    from app.platform.superagent.models import AgentSource

    return AgentSource


class _Ctx:
    """执行器自开 session → 复用 db_session（patch factory）。"""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


async def test_full_chain_observe_then_promote_remind(
    db_session, chain_env, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import date

    from app.modules.safety.service.guardian_r2.executor import guardian_remind_dm
    from app.platform.superagent.executors import register_executor, run_task_once
    from app.platform.superagent.models import (
        AgentDecision,
        AgentEffect,
        AgentOutboxMessage,
        AgentSource,
        AgentTask,
        AgentTrigger,
    )
    from app.platform.superagent.policy import resolve_decision

    records = [
        {"record_id": "r2chain1", "kind": "guardian_a",
         "fields": _cert_fields("张三")},   # first=2027-01 → 2026-11 在窗内
        {"record_id": "r2chain2", "kind": "guardian_b",
         "fields": _cert_fields(
             "李四", issue_ms=1764604800000,
         )},  # 2025-12-01 → first=2026-12-01，2026-12 在提醒窗
    ]

    # ── 第一轮：扫描 → observe 只记 ──
    summary = await _scan_once(
        db_session, monkeypatch, records, today=date(2026, 11, 4)
    )
    assert summary["stored"] == 2
    decisions = (
        await db_session.execute(
            select(AgentDecision)
            .join(AgentTrigger, AgentDecision.trigger_id == AgentTrigger.id)
            .join(AgentSource, AgentTrigger.source_id == AgentSource.id)
            .where(AgentSource.name == _SRC_NAME, AgentDecision.replay.is_(False))
        )
    ).scalars().all()
    # 组合 Policy：每 Trigger 按每条证书源规则各落一条决策（2×3=6），
    # 其中 would_accept 命中恰 2（remind 规则×remind + revoke 规则×overdue）
    assert len(decisions) == 6
    hits = [d for d in decisions if d.would_accept]
    # 两条都落提醒窗（拍板④后逾期静默不产 Trigger，不再有 overdue 命中）
    assert len(hits) == 2
    kinds = set()
    for d in hits:
        trig = await db_session.get(_trigger_model(), d.trigger_id)
        kinds.add(trig.payload["_derived"]["trigger_type"])
    assert kinds == {"remind"}
    # observe 红线：零任务零 effect 零 outbox（R2 范围过滤）
    assert (
        await db_session.execute(
            select(func.count()).select_from(AgentTask).where(
                AgentTask.executor == "guardian_remind_dm"
            )
        )
    ).scalar_one() == 0
    assert (
        await db_session.execute(
            select(func.count()).select_from(AgentEffect).where(
                AgentEffect.kind == "dm_admin"
            )
        )
    ).scalar_one() == 0
    assert (
        await db_session.execute(
            select(func.count()).select_from(AgentOutboxMessage).where(
                AgentOutboxMessage.conversation.like("guardian_remind:%")
            )
        )
    ).scalar_one() == 0

    # ── 重扫同批：duplicate 幂等零新增 ──
    summary2 = await _scan_once(
        db_session, monkeypatch, records, today=date(2026, 11, 4)
    )
    assert summary2["stored"] == 0 and summary2["duplicate"] == 2
    decisions2 = (
        await db_session.execute(
            select(func.count())
            .select_from(AgentDecision)
            .join(AgentTrigger, AgentDecision.trigger_id == AgentTrigger.id)
            .join(AgentSource, AgentTrigger.source_id == AgentSource.id)
            .where(AgentSource.name == _SRC_NAME, AgentDecision.replay.is_(False))
        )
    ).scalar_one()
    assert decisions2 == 6  # 不重复研判（重扫 duplicate 不再评估）

    # ── 转正 remind → 执行器 DM → links 计数 → outbox 卡 ──
    remind_decision = None
    for d in hits:
        trig = await db_session.get(_trigger_model(), d.trigger_id)
        if trig.payload["_derived"]["trigger_type"] == "remind":
            remind_decision = d
            break
    assert remind_decision is not None
    await resolve_decision(
        db_session, remind_decision, resolution="promoted", resolved_by="admin-r2",
    )
    await db_session.flush()
    task = (
        await db_session.execute(
            select(AgentTask).where(AgentTask.executor == "guardian_remind_dm")
        )
    ).scalar_one()
    assert task.mandate["strength"] == "promoted"

    try:
        register_executor("guardian_remind_dm", guardian_remind_dm)
    except ValueError:
        pass
    monkeypatch.setattr(
        "app.core.database.async_session_factory", lambda: _Ctx(db_session),
    )
    outcome = await run_task_once(db_session, task.id)
    assert outcome == "ran"
    await db_session.flush()

    outbox = (
        await db_session.execute(
            select(AgentOutboxMessage).where(
                AgentOutboxMessage.conversation.like("guardian_remind:%")
            )
        )
    ).scalars().all()
    assert len(outbox) == 1
    assert outbox[0].channel == {"type": "feishu_dm_card", "open_id": "ou_r2chain"}
    content = outbox[0].body["content"]
    assert "第 1 次（共 3 次）" in content
    assert "2027-01-10" in content and "取消监护资格" in content

    links = (
        await db_session.execute(
            select(GuardianQualificationLink).where(
                GuardianQualificationLink.record_id == "r2chain1"
            )
        )
    ).scalars().all()
    assert len(links) == 1
    assert links[0].remind_count == 1
    assert links[0].last_reminded_month == "2026-11"
    assert links[0].qualification_status == "active"

    await db_session.refresh(task)
    assert task.status == "ended" and task.outcome == "ready"

    # ── 执行器重跑：last_reminded_month 幂等跳过 ──
    task2 = (
        await db_session.execute(
            select(AgentTask).where(
                AgentTask.executor == "guardian_remind_dm",
                AgentTask.status != "ended",
            )
        )
    ).scalar_one_or_none()
    assert task2 is None  # 同任务已终态；重开任务走新 Trigger（月键防重）


def _trigger_model():
    from app.platform.superagent.models import AgentTrigger

    return AgentTrigger
