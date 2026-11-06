"""R2 取消资格/恢复链路 —— observe→promote→执行器→links 状态→双 DM。

分支：逾期（overdue）与不合格（failed）两路 reason；恒 observe 人工确认
（promote=「经审核确认」）；恢复（restore）确认人留痕；幂等重跑不重复流转。
"""

from __future__ import annotations

import uuid as _uuid
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.schema import CreateTable, CreateIndex

from app.modules.safety.models.guardian_qualification_link import (
    GuardianQualificationLink,
)

_CERT_SRC = "safety.guardian.r2"


def _uuid_zero():
    return _uuid.UUID("00000000-0000-0000-0000-000000000000")


def _derived(trigger_type: str, rid: str, **kw: Any) -> dict:
    base = dict(
        trigger_type=trigger_type, record_id=rid, person_name="赵逾期",
        guardian_open_id="ou_revoke", department="提炼工程一部",
        cert_category="guardian_a", node_key="first_review",
        node_label="第一次复审", deadline="2025-01-10", remaining_days=-300,
        qualification_status="active", remind_count=3, remind_seq=4,
    )
    base.update(kw)
    return base


@pytest_asyncio.fixture(autouse=True)
async def _purge():
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
        await s.execute(
            CreateTable(GuardianQualificationLink.__table__, if_not_exists=True)
        )
        for idx in GuardianQualificationLink.__table__.indexes:
            await s.execute(CreateIndex(idx, if_not_exists=True))
        tids: list = []
        for src in (
            await s.execute(select(AgentSource).where(AgentSource.name == _CERT_SRC))
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
                AgentOutboxMessage.conversation.like("guardian_revoke%")
                | AgentOutboxMessage.conversation.like("guardian_restore%")
            )
        )
        await s.execute(
            GuardianQualificationLink.__table__.delete().where(
                GuardianQualificationLink.record_id.like("recRv%")
            )
        )
        await s.commit()


@pytest_asyncio.fixture
async def revoke_env(db_session):
    """links 表 + R2 源 + observe Policy。"""
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
        kind="guardian_cert_scan", name=_CERT_SRC, enabled=True,
        config={"schedule": {"strategy": "cron", "expression": "0 8 * * *",
                              "timezone": "Asia/Shanghai"},
                 "evaluate": True, "thread_prefix": "guardian_cert"},
    )
    db_session.add(src)
    await db_session.flush()
    _, policy = await apply_new_policy(
        db_session,
        rules=[
            r1_fire_rule(), guardian_remind_rule(), guardian_revoke_rule(),
            guardian_restore_rule(), guardian_score_map_rule(),
        ],
        accept_mode="observe",
    )
    await db_session.flush()
    yield src


class _Ctx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


async def _trigger(db_session, src, rid: str, derived: dict) -> Any:
    from app.platform.superagent.models import AgentTrigger

    trig = AgentTrigger(
        source_id=src.id,
        external_id=f"guardian:{rid}:{derived['trigger_type']}:t1",
        thread_key=f"guardian_cert:{rid}",
        actor={"id": rid, "type": "bitable_record"},
        human=False,
        addressed=False,
        payload={"record_id": rid, "_derived": derived,
                 "channel": {"kind": "bitable", "record_id": rid}},
    )
    db_session.add(trig)
    await db_session.flush()
    return trig


async def _promote_and_run(db_session, monkeypatch, trig, executor_name: str) -> Any:
    from app.platform.superagent.executors import run_task_once
    from app.platform.superagent.models import AgentDecision, AgentTask
    from app.platform.superagent.policy import (
        evaluate_trigger,
        get_current_policy,
        resolve_decision,
    )

    policy = await get_current_policy(db_session)
    await evaluate_trigger(db_session, trig, policy=policy, source_name=_CERT_SRC)
    await db_session.flush()
    decisions = (
        await db_session.execute(
            select(AgentDecision).where(AgentDecision.trigger_id == trig.id)
        )
    ).scalars().all()
    hit = next(d for d in decisions if d.would_accept)
    await resolve_decision(db_session, hit, resolution="promoted", resolved_by="admin-xk")
    await db_session.flush()
    task = (
        await db_session.execute(
            select(AgentTask).where(AgentTask.origin_trigger_id == trig.id)
        )
    ).scalar_one()
    monkeypatch.setattr(
        "app.core.database.async_session_factory", lambda: _Ctx(db_session),
    )
    return await run_task_once(db_session, task.id)


async def test_failed_revoke_full_chain(
    db_session, revoke_env, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """不合格 → promote → revoked（reason=考核不合格）+ 本人/安管双 DM + 确认人。"""
    from app.platform.superagent.models import AgentOutboxMessage

    trig = await _trigger(db_session, revoke_env, "recRv1", _derived("failed", "recRv1"))
    outcome = await _promote_and_run(db_session, monkeypatch, trig, "guardian_qualify_revoke")
    assert outcome == "ran"
    await db_session.flush()

    link = (
        await db_session.execute(
            select(GuardianQualificationLink).where(
                GuardianQualificationLink.record_id == "recRv1"
            )
        )
    ).scalar_one()
    assert link.qualification_status == "revoked"
    assert link.revoked_reason == "考核不合格"
    assert link.revoked_by == "admin-xk"          # promote 操作人留痕
    assert link.node_deadline is not None

    outbox = (
        await db_session.execute(
            select(AgentOutboxMessage).where(
                AgentOutboxMessage.conversation.like("guardian_revoke%")
            )
        )
    ).scalars().all()
    assert len(outbox) == 2                        # 本人 + 安管
    person_card = next(
        o for o in outbox if o.channel["open_id"] == "ou_revoke"
    )
    admin_card = next(
        o for o in outbox if o.channel["open_id"] != "ou_revoke"
    )
    assert "取消监护资格" in person_card.body["content"] or "资格已取消" in person_card.body["content"]
    assert "停止发放" in person_card.body["content"]
    assert "恢复路径" in person_card.body["content"]
    assert "admin-xk" in admin_card.body["content"]  # 审核确认留痕

    # ── 幂等：同 Trigger 重跑（人工 retry）→ 不重复流转/发卡 ──
    from app.modules.safety.service.guardian_r2.executor import guardian_qualify_revoke
    from app.platform.superagent.executors import register_executor

    try:
        register_executor("guardian_qualify_revoke", guardian_qualify_revoke)
    except ValueError:
        pass
    task_dict = {"id": str(outbox[0].task_id), "mandate": {
        "origin_actor": {"id": "recRv1"}, "strength": "promoted",
    }}
    report = await guardian_qualify_revoke(task_dict, [])
    assert report.kind == "ready"
    await db_session.flush()
    outbox2 = (
        await db_session.execute(
            select(AgentOutboxMessage).where(
                AgentOutboxMessage.conversation.like("guardian_revoke%")
            )
        )
    ).scalars().all()
    assert len(outbox2) == 2
    link2 = (
        await db_session.execute(
            select(GuardianQualificationLink).where(
                GuardianQualificationLink.record_id == "recRv1"
            )
        )
    ).scalar_one()
    assert link2.qualification_status == "revoked"


async def test_failed_exam_revoke_reason(
    db_session, revoke_env, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """不合格 → reason=考核不合格。"""
    trig = await _trigger(
        db_session, revoke_env, "recRv2",
        _derived("failed", "recRv2", person_name="钱不合格",
                 guardian_open_id="ou_fail", node_label="第二次复审"),
    )
    outcome = await _promote_and_run(db_session, monkeypatch, trig, "guardian_qualify_revoke")
    assert outcome == "ran"
    await db_session.flush()
    link = (
        await db_session.execute(
            select(GuardianQualificationLink).where(
                GuardianQualificationLink.record_id == "recRv2"
            )
        )
    ).scalar_one()
    assert link.revoked_reason == "考核不合格"


async def test_revoke_refuses_auto_mandate() -> None:
    """恒 observe 护栏：auto 强度（Policy 全局切 auto 时）执行器拒绝取消资格。"""
    from app.modules.safety.service.guardian_r2.executor import guardian_qualify_revoke

    report = await guardian_qualify_revoke(
        {"id": str(_uuid.uuid4()), "mandate": {
            "origin_actor": {"id": "recAuto1"}, "strength": "auto",
        }},
        [],
    )
    assert report.kind == "failed"
    assert "恒 observe" in report.note and "promote" in report.note


async def test_restore_chain(
    db_session, revoke_env, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """revoked + 新合格事件 → restore Trigger → promote → restored + 确认人 + DM。"""
    from app.modules.safety.service.guardian_r2.links import (
        append_score_event,
        get_or_create_link,
    )
    from app.platform.superagent.models import AgentOutboxMessage

    await get_or_create_link(
        db_session, record_id="recRv3", person_name="孙恢复",
        department="提炼工程一部", cert_category="guardian_a", snapshot={},
    )
    await append_score_event(db_session, "recRv3", {
        "exam_type": "复审", "passed": "合格", "exam_date": "2026-11-20",
        "discriminated": "复审",
    })
    await db_session.flush()
    # 把行改成 revoked（模拟此前已取消）
    row = (
        await db_session.execute(
            select(GuardianQualificationLink).where(
                GuardianQualificationLink.record_id == "recRv3"
            )
        )
    ).scalar_one()
    row.qualification_status = "revoked"
    row.revoked_reason = "逾期未复审"
    await db_session.flush()

    trig = await _trigger(
        db_session, revoke_env, "recRv3",
        _derived("restore", "recRv3", person_name="孙恢复",
                 guardian_open_id="ou_restore", qualification_status="revoked"),
    )
    outcome = await _promote_and_run(db_session, monkeypatch, trig, "guardian_qualify_restore")
    assert outcome == "ran"
    await db_session.flush()

    link = (
        await db_session.execute(
            select(GuardianQualificationLink).where(
                GuardianQualificationLink.record_id == "recRv3"
            )
        )
    ).scalar_one()
    assert link.qualification_status == "restored"
    assert link.confirmed_by == "admin-xk"
    assert link.restored_at is not None

    outbox = (
        await db_session.execute(
            select(AgentOutboxMessage).where(
                AgentOutboxMessage.conversation.like("guardian_restore%")
            )
        )
    ).scalars().all()
    assert len(outbox) == 1
    assert "资格已恢复" in outbox[0].body["content"]
    assert "2026-11-20" in outbox[0].body["content"]   # 合格考核日期
    assert "admin-xk" in outbox[0].body["content"]
