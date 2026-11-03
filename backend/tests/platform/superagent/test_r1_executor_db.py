"""alarm_hazard_create 执行器 —— 成功/失败/重试幂等/outbox 卡（B 层，真 PG）。

mock SafetyBitableClient（patch executor 模块引用）；links/Trigger/Task 走真
表。executor 自开 session 并 commit（真机形态）——测试数据用名前缀标识，
autouse 异步 fixture 用例后清理，不污染库。
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.schema import CreateTable

from app.modules.safety.models.alarm_hazard_link import AlarmHazardLink

_CLIENT_SRC = "app.modules.safety.feishu.bitable_client"
_REC_PREFIX = "recExec"


class FakeBitableClient:
    """假 Bitable：记录 create_record/create_field 调用。"""

    def __init__(self, *, created: dict | None, fields_existing: list[dict] | None = None):
        self.created = created
        self.create_calls: list[dict] = []
        self.created_field_names: list[str] = []
        self._fields_existing = fields_existing or []

    async def list_fields(self, table_id: str | None = None) -> list[dict[str, Any]]:
        return list(self._fields_existing)

    async def create_field(self, field_name: str, field_type: int = 1) -> dict:
        self.created_field_names.append(field_name)
        self._fields_existing.append({"field_name": field_name})
        return True

    async def create_record(self, fields: dict[str, Any], table_id: str | None = None):
        self.create_calls.append(fields)
        if self.created is None:
            return None
        return self.created


_ALARM_FIELDS = {
    "报警时间": 1793630412844,
    "报警类型": "火灾报警",
    "报警部门负责人.部门": ["提炼工程一部"],
    "报警楼栋": "提三",
    "报警部位": [{"type": "text", "text": "1楼罐区"}],
    "报警性质": "泄漏报警",
    "报警原因分类": "氨水引发",
    "具体报警原因": [{"type": "text", "text": "接浓氨挥发"}],
    "处理情况": [{"type": "text", "text": "已通知仪表"}],
}


@pytest_asyncio.fixture
async def links_table(db_session):
    from sqlalchemy.schema import CreateIndex

    await db_session.execute(CreateTable(AlarmHazardLink.__table__, if_not_exists=True))
    for idx in AlarmHazardLink.__table__.indexes:
        await db_session.execute(CreateIndex(idx, if_not_exists=True))
    await db_session.flush()
    yield


@pytest_asyncio.fixture(autouse=True)
async def _share_session_with_executor(db_session, monkeypatch: pytest.MonkeyPatch):
    """executor 自开 async_session_factory（新连接）看不到 db_session 事务内
    的临时 DDL/数据——patch 成复用 db_session 同一连接；其 commit 的落库由
    _cleanup_created_rows 按名前缀清理。
    """
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
    yield


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_created_rows():
    """executor 真实形态自开 session+commit——用例后按名前缀清理真落库行。"""
    yield
    from app.platform.superagent.models import (
        AgentInput,
        AgentOutboxMessage,
        AgentSource,
        AgentTask,
        AgentTaskSubscription,
        AgentTrigger,
    )
    from tests.conftest import _test_session_factory

    async with _test_session_factory() as s:
        srcs = (
            await s.execute(
                select(AgentSource).where(AgentSource.name == "test.r1.exec")
            )
        ).scalars().all()
        for src in srcs:
            triggers = (
                await s.execute(
                    select(AgentTrigger).where(AgentTrigger.source_id == src.id)
                )
            ).scalars().all()
            for t in triggers:
                await s.execute(
                    AgentInput.__table__.delete().where(AgentInput.trigger_id == t.id)
                )
            tasks = (
                await s.execute(
                    select(AgentTask).where(AgentTask.origin_trigger_id.in_(
                        [t.id for t in triggers] or [uuid_zero()]
                    ))
                )
            ).scalars().all()
            for task in tasks:
                await s.execute(
                    AgentInput.__table__.delete().where(AgentInput.task_id == task.id)
                )
                await s.execute(
                    AgentTaskSubscription.__table__.delete().where(
                        AgentTaskSubscription.task_id == task.id
                    )
                )
                await s.delete(task)
            for t in triggers:
                await s.delete(t)
            await s.delete(src)
        await s.execute(
            AgentOutboxMessage.__table__.delete().where(
                AgentOutboxMessage.conversation.like(f"r1_fire:{_REC_PREFIX}%")
            )
        )
        await s.execute(
            AlarmHazardLink.__table__.delete().where(
                AlarmHazardLink.alarm_record_id.like(f"{_REC_PREFIX}%")
            )
        )
        await s.commit()


def uuid_zero():
    import uuid

    return uuid.UUID("00000000-0000-0000-0000-000000000000")


async def _make_task(db_session, *, record_id: str) -> dict[str, Any]:
    """造 Trigger+Task（executor=alarm_hazard_create），commit 供 executor 读。"""
    from app.platform.superagent.models import AgentSource, AgentTrigger
    from app.platform.superagent.tasks import create_task

    src = AgentSource(kind="cron_scan", name="test.r1.exec", config={}, enabled=False)
    db_session.add(src)
    await db_session.flush()
    trigger = AgentTrigger(
        source_id=src.id,
        external_id=f"fire_alarm:{record_id}:fp1",
        thread_key=f"bitable:fire_alarm:{record_id}",
        actor={"id": record_id, "type": "bitable_record"},
        payload={"record_id": record_id, "fields": _ALARM_FIELDS, "fingerprint": "fp1"},
    )
    db_session.add(trigger)
    await db_session.flush()
    task = await create_task(
        db_session,
        short_name=f"fire_alarm_candidate:{str(trigger.id)[:8]}",
        title="转正：规则 fire_alarm_candidate",
        executor="alarm_hazard_create",
        origin_trigger_id=trigger.id,
        mandate={
            "policy_version": "v-test", "scope": {}, "strength": "promoted",
            "rule_id": "fire_alarm_candidate",
            "origin_actor": {"id": record_id, "type": "bitable_record"},
        },
        origin_thread_key=trigger.thread_key,
    )
    await db_session.commit()
    return {
        "id": str(task.id), "short_name": task.short_name,
        "title": task.title, "mandate": dict(task.mandate or {}),
    }


async def test_success_creates_hazard_and_fills_links(
    db_session, links_table, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """成功链：建隐患（含 ensure 列）→ links 回填 → outbox 卡 → Report ready+end。"""
    from app.modules.safety.service.alarm_hazard_r1.executor import alarm_hazard_create
    from app.platform.superagent.models import AgentOutboxMessage

    fake = FakeBitableClient(created={"record_id": "hzRec001", "shared_url": "u"})
    monkeypatch.setattr(f"{_CLIENT_SRC}.SafetyBitableClient", lambda: fake)
    monkeypatch.setenv("SAFETY_R1_FIRE_CARD_CHAT_ID", "oc_r1_test")

    task_dict = await _make_task(db_session, record_id="recExec1")
    report = await alarm_hazard_create(task_dict, [])

    assert report.kind == "ready" and report.end_task is True
    # ensure 列：无「关联报警」列时建文本列（幂等：已有则跳过）
    assert fake.created_field_names == ["关联报警"]
    # create 恰一次，字段=映射产物（抽查关键显式值）
    assert len(fake.create_calls) == 1
    sent = fake.create_calls[0]
    assert sent["整改状态"] == "未关闭"
    assert sent["检查类别"] == ["报警联动"]
    assert sent["关联报警"] == "fire_alarm:recExec1"
    # links 回填
    link = (
        await db_session.execute(
            select(AlarmHazardLink).where(AlarmHazardLink.alarm_record_id == "recExec1")
        )
    ).scalar_one()
    assert link.hazard_record_id == "hzRec001"
    assert link.decided_by  # promoted → 处置来源派生
    assert link.error_message is None
    # outbox 卡（chat_id 行内权威）
    outbox = (
        await db_session.execute(
            select(AgentOutboxMessage).where(
                AgentOutboxMessage.conversation == "r1_fire:recExec1"
            )
        )
    ).scalars().all()
    assert len(outbox) == 1
    assert outbox[0].channel["chat_id"] == "oc_r1_test"
    await db_session.rollback()


async def test_failure_blocks_and_leaves_error(
    db_session, links_table, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """失败链：create_record None → Report blocked + links.error_message 留痕。"""
    from app.modules.safety.service.alarm_hazard_r1.executor import alarm_hazard_create

    fake = FakeBitableClient(created=None)
    monkeypatch.setattr(f"{_CLIENT_SRC}.SafetyBitableClient", lambda: fake)

    task_dict = await _make_task(db_session, record_id="recExec2")
    report = await alarm_hazard_create(task_dict, [])

    assert report.kind == "blocked"
    assert report.end_task is False
    link = (
        await db_session.execute(
            select(AlarmHazardLink).where(AlarmHazardLink.alarm_record_id == "recExec2")
        )
    ).scalar_one()
    assert link.hazard_record_id is None
    assert link.error_message
    await db_session.rollback()


async def test_retry_idempotent_after_success(
    db_session, links_table, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """重试幂等：成功后再跑 → ready 跳过，create 不再调用（幂等第三道保险）。"""
    from app.modules.safety.service.alarm_hazard_r1.executor import alarm_hazard_create

    fake = FakeBitableClient(created={"record_id": "hzRec003"})
    monkeypatch.setattr(f"{_CLIENT_SRC}.SafetyBitableClient", lambda: fake)

    task_dict = await _make_task(db_session, record_id="recExec3")
    first = await alarm_hazard_create(task_dict, [])
    second = await alarm_hazard_create(task_dict, [])
    assert first.kind == "ready" and second.kind == "ready"
    assert len(fake.create_calls) == 1  # 只建一次
    await db_session.rollback()


async def test_no_chat_id_skips_outbox(
    db_session, links_table, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """chat_id 未配置（默认空）→ 不入队 outbox（P4 卡默认静默）。"""
    from app.modules.safety.service.alarm_hazard_r1.executor import alarm_hazard_create
    from app.platform.superagent.models import AgentOutboxMessage

    fake = FakeBitableClient(created={"record_id": "hzRec004"})
    monkeypatch.setattr(f"{_CLIENT_SRC}.SafetyBitableClient", lambda: fake)
    monkeypatch.delenv("SAFETY_R1_FIRE_CARD_CHAT_ID", raising=False)

    task_dict = await _make_task(db_session, record_id="recExec4")
    report = await alarm_hazard_create(task_dict, [])
    assert report.kind == "ready"
    rows = (
        await db_session.execute(
            select(AgentOutboxMessage).where(
                AgentOutboxMessage.conversation == "r1_fire:recExec4"
            )
        )
    ).scalars().all()
    assert rows == []
    await db_session.rollback()
