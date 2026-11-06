"""R2 成绩映射链路 —— 三分支（取证/复审/换证）写回 + links 事件 + DM。

FakeBitableClient 替身断言真实调用（取证 create_record 字段全 / 复审三列 /
换证已换证日期）；幂等：同 Trigger 重放写回跳过。集成模式照 R1 executor 测试。
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
_SCORE_SRC = "safety.guardian.score"


def _uuid_zero():
    return _uuid.UUID("00000000-0000-0000-0000-000000000000")


class FakeCertClient:
    """持证表替身：建列零成本、记录写回断言。"""

    def __init__(self, existing_fields: list[str] | None = None) -> None:
        self.fields = list(existing_fields or [])
        self.create_calls: list[dict] = []
        self.update_calls: list[tuple[str, dict]] = []

    async def list_fields(self, table_id: str | None = None) -> list[dict]:
        return [{"field_name": n} for n in self.fields]

    async def create_field(self, name: str, ftype: int, **kw) -> dict:  # noqa: ANN002, ANN003
        self.fields.append(name)
        return {"field_name": name}

    async def create_record(self, fields: dict, table_id: str | None = None):
        self.create_calls.append(fields)
        return {"record_id": "recEnroll001", "shared_url": "u"}

    async def update_record(self, rid: str, fields: dict, table_id=None) -> bool:  # noqa: ANN001
        self.update_calls.append((rid, fields))
        return True


def _cert_rec(rid: str, name: str, issue_ms: int, kind: str = "guardian_a") -> dict:
    import datetime as dt

    def plus(ms: int, years: int) -> int:
        d = dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc).date()
        try:
            d = d.replace(year=d.year + years)
        except ValueError:
            d = dt.date(d.year + years, 2, 28)
        return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc)
                   .timestamp() * 1000)

    return {
        "record_id": rid, "kind": kind,
        "fields": {
            "姓名": [{"id": f"ou_{rid}", "name": name}],
            "部门": ["提炼工程一部"],
            "取证日期": issue_ms,
            "第一次复审截止日期": plus(issue_ms, 1),
            "第二次复审截止日期": plus(issue_ms, 2),
            "应换证日期": plus(issue_ms, 3),
        },
    }


def _score_fields(name: str, passed: str, exam_ms: int, cat: str = "监护人A证") -> dict:
    return {
        "姓名": [{"id": "ou_score", "name": name}],
        "部门": "提炼工程一部",
        "报名考试类型": cat,
        "考试分数": 88,
        "是否合格": {"type": 1, "value": [{"text": passed, "type": "text"}]},
        "考试日期": {"type": 5, "value": [exam_ms]},
    }


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
            await s.execute(select(AgentSource).where(AgentSource.name == _SCORE_SRC))
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
                AgentOutboxMessage.conversation.like("guardian_score:%")
            )
        )
        await s.execute(
            GuardianQualificationLink.__table__.delete().where(
                GuardianQualificationLink.record_id.in_(
                    ["recEnroll001", "recMapR", "recMapZ", "recFail"]
                )
            )
        )
        await s.commit()


@pytest_asyncio.fixture
async def score_env(db_session):
    """links 表 + 成绩源行（enabled）+ observe Policy + 注册。"""
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
        kind="guardian_score_poll", name=_SCORE_SRC, enabled=True,
        config={
            "fetcher": "guardian_score_ledger",
            "relevant_fields": ["姓名", "报名考试类型", "考试分数", "是否合格", "参加考试日期"],
            "evaluate": True, "thread_prefix": "guardian_score",
        },
    )
    db_session.add(src)
    await db_session.flush()
    policy, _ = await apply_new_policy(
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


async def _make_score_trigger(db_session, src, fields) -> Any:
    """直接落一条成绩 Trigger（跳过轮询 IO），simulate bitable_poll payload。"""
    from app.platform.superagent.bitable_poll import relevant_fingerprint
    from app.platform.superagent.models import AgentTrigger

    fp = relevant_fingerprint(
        fields, ["姓名", "报名考试类型", "考试分数", "是否合格", "参加考试日期"]
    )
    from datetime import UTC, datetime

    # _derived 翻译层由 GuardianScorePollSource.poll 注入——测试模拟同构输出
    from app.modules.safety.service.guardian_r2.score_parse import parse_score_record

    facts = parse_score_record(fields)
    derived = {
        "person_name": facts.person_name,
        "open_id": facts.open_id,
        "department": facts.department,
        "cert_category": facts.cert_category,
        "passed": facts.passed,
        "exam_date": facts.exam_date.isoformat() if facts.exam_date else None,
        "score_value": facts.score_value,
    }
    trig = AgentTrigger(
        source_id=src.id,
        external_id=f"sc{fields['姓名'][0]['name']}:{fp}",
        thread_key="bitable:guardian_score:sc1",
        actor={"id": "sc1", "type": "bitable_record"},
        human=False,
        addressed=False,
        payload={
            "record_id": "sc1", "fields": fields,
            "fingerprint": fp,
            "_derived": derived,
            "channel": {"kind": "bitable", "record_id": "sc1"},
        },
    )
    _ = (datetime.now(UTC),)  # created_at 由模型 server_default 负责
    db_session.add(trig)
    await db_session.flush()
    return trig


async def _promote_and_run(
    db_session, monkeypatch, trig, cert_records, fake_client,
) -> Any:
    """observe 评估 → promote → run_task_once（patch 持证拉取 + 客户端）。"""
    from app.platform.superagent.executors import run_task_once
    from app.platform.superagent.models import AgentDecision, AgentTask
    from app.platform.superagent.policy import (
        evaluate_trigger,
        get_current_policy,
        resolve_decision,
    )

    policy = await get_current_policy(db_session)
    await evaluate_trigger(db_session, trig, policy=policy, source_name=_SCORE_SRC)
    await db_session.flush()
    decisions = (
        await db_session.execute(
            select(AgentDecision).where(AgentDecision.trigger_id == trig.id)
        )
    ).scalars().all()
    hit = next(d for d in decisions if d.would_accept)
    await resolve_decision(db_session, hit, resolution="promoted", resolved_by="admin-s")
    await db_session.flush()
    task = (
        await db_session.execute(
            select(AgentTask).where(AgentTask.origin_trigger_id == trig.id)
        )
    ).scalar_one()

    from app.modules.safety.service.guardian_r2 import executor as r2_exec
    from app.modules.safety.service.guardian_r2 import scan_source

    async def _fetch():
        return list(cert_records)

    monkeypatch.setattr(scan_source, "fetch_guardian_cert_records", _fetch)
    monkeypatch.setattr(r2_exec, "_cert_client", lambda cat: fake_client)
    monkeypatch.setattr(
        "app.core.database.async_session_factory", lambda: _Ctx(db_session),
    )
    return await run_task_once(db_session, task.id)


# ═══════════════════════════════════════════════════════════
# 三分支
# ═══════════════════════════════════════════════════════════


async def test_enroll_branch_creates_cert_record(
    db_session, score_env, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """合格+不在名单 → 取证：create_record 字段全（人员/取证日/1-2-3年/三列）。"""
    from app.platform.superagent.models import AgentOutboxMessage

    trig = await _make_score_trigger(
        db_session, score_env, _score_fields("王新人", "合格", 1793462400000)
    )  # 公式列毫秒=北京零点 2026-11-01（实测口径）
    fake = FakeCertClient()
    outcome = await _promote_and_run(
        db_session, monkeypatch, trig, cert_records=[], fake_client=fake
    )
    assert outcome == "ran"
    await db_session.flush()
    assert len(fake.create_calls) == 1
    sent = fake.create_calls[0]
    assert sent["姓名"] == [{"id": "ou_score"}]
    assert sent["考核类型"] == "取证"
    # 考核日期公式毫秒北京零点 2026-11-01 → date；+1 年 = 2027-11-01 UTC 零点
    import datetime as dt
    expect_first = int(dt.datetime(2027, 11, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    assert sent["第一次复审截止日期"] == expect_first
    # links 落新 record + 事件
    link = (
        await db_session.execute(
            select(GuardianQualificationLink).where(
                GuardianQualificationLink.record_id == "recEnroll001"
            )
        )
    ).scalar_one()
    assert link.last_score_event["discriminated"] == "取证"
    # DM 取证欢迎
    outbox = (
        await db_session.execute(
            select(AgentOutboxMessage).where(
                AgentOutboxMessage.conversation.like("guardian_score:%")
            )
        )
    ).scalars().all()
    assert len(outbox) == 1
    assert "取证成功" in outbox[0].body["content"]


async def test_review_branch_writes_three_columns(
    db_session, score_env, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """合格+节点=复审 → 写回考核三列 + links 事件。"""
    import datetime as dt

    issue_ms = int(dt.datetime(2026, 1, 10, tzinfo=dt.timezone.utc).timestamp() * 1000)
    trig = await _make_score_trigger(
        db_session, score_env, _score_fields("张在册", "合格", 1793462400000)
    )
    fake = FakeCertClient()
    outcome = await _promote_and_run(
        db_session, monkeypatch, trig,
        cert_records=[_cert_rec("recMapR", "张在册", issue_ms)], fake_client=fake,
    )
    assert outcome == "ran"
    await db_session.flush()
    assert fake.create_calls == []
    assert len(fake.update_calls) == 1
    rid, fields = fake.update_calls[0]
    assert rid == "recMapR"
    assert fields["考核类型"] == "复审"
    assert fields["考核成绩"] == "合格"
    assert "已换证日期" not in fields
    link = (
        await db_session.execute(
            select(GuardianQualificationLink).where(
                GuardianQualificationLink.record_id == "recMapR"
            )
        )
    ).scalar_one()
    assert link.exam_history[-1]["discriminated"] == "复审"


async def test_renew_branch_writes_renewed_date(
    db_session, score_env, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """两次复审已过 + 节点=换证 → 写回三列 + 已换证日期（成功延期换证）。"""
    import datetime as dt

    issue_ms = int(dt.datetime(2024, 1, 10, tzinfo=dt.timezone.utc).timestamp() * 1000)
    trig = await _make_score_trigger(
        db_session, score_env, _score_fields("李待换", "合格", 1793462400000)
    )
    # links 历史两次复审合格 → 当前节点=换证
    from app.modules.safety.service.guardian_r2.links import get_or_create_link
    from app.modules.safety.service.guardian_r2.links import append_score_event

    await get_or_create_link(
        db_session, record_id="recMapZ", person_name="李待换",
        department="提炼工程一部", cert_category="guardian_a", snapshot={},
    )
    await append_score_event(db_session, "recMapZ", {
        "exam_type": "复审", "passed": "合格", "exam_date": "2024-12-01",
        "discriminated": "复审",
    })
    await append_score_event(db_session, "recMapZ", {
        "exam_type": "复审", "passed": "合格", "exam_date": "2025-12-01",
        "discriminated": "复审",
    })
    await db_session.flush()

    fake = FakeCertClient()
    outcome = await _promote_and_run(
        db_session, monkeypatch, trig,
        cert_records=[_cert_rec("recMapZ", "李待换", issue_ms)], fake_client=fake,
    )
    assert outcome == "ran"
    await db_session.flush()
    rid, fields = fake.update_calls[0]
    assert rid == "recMapZ"
    assert fields["考核类型"] == "换证"
    expect_renewed = int(dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    assert fields["已换证日期"] == expect_renewed
    # DM 延期换证
    from app.platform.superagent.models import AgentOutboxMessage

    outbox = (
        await db_session.execute(
            select(AgentOutboxMessage).where(
                AgentOutboxMessage.conversation.like("guardian_score:%")
            )
        )
    ).scalars().all()
    assert "换证成功" in outbox[0].body["content"]


async def test_rerun_after_writeback_is_idempotent(
    db_session, score_env, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """持证表已写回同次考核 → ready 幂等跳过（不重复 update/append）。"""
    import datetime as dt

    issue_ms = int(dt.datetime(2026, 1, 10, tzinfo=dt.timezone.utc).timestamp() * 1000)
    rec = _cert_rec("recMapR", "张在册", issue_ms)
    # 模拟上一轮已写回：考核三列已在 fields
    rec["fields"]["考核成绩"] = "合格"
    rec["fields"]["考核类型"] = "复审"
    rec["fields"]["考核日期"] = 1793462400000 // 1  # UTC 2026-11-01? 见视图口径
    # 视图按 UTC 口径解析原生日期列：构造 UTC 零点毫秒
    utc_ms = int(dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    rec["fields"]["考核日期"] = utc_ms

    trig = await _make_score_trigger(
        db_session, score_env, _score_fields("张在册", "合格", 1793462400000)
    )
    fake = FakeCertClient()
    outcome = await _promote_and_run(
        db_session, monkeypatch, trig, cert_records=[rec], fake_client=fake,
    )
    assert outcome == "ran"
    await db_session.flush()
    assert fake.update_calls == []  # 幂等：零写回
    assert fake.create_calls == []
