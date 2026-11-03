"""R1 联动台账 REST —— 列表/派生状态/编号回读/失败重试（client+回滚 session）。

links 表事务内自建；bitable 直读 mock。权限口径对齐底座 api.py
（查询 RequireUser / 变更 RequireAdmin——测试 client 绕过认证层，仅验行为）。
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.schema import CreateIndex, CreateTable

from app.modules.safety.models.alarm_hazard_link import AlarmHazardLink


@pytest_asyncio.fixture
async def links_table(db_session):
    await db_session.execute(CreateTable(AlarmHazardLink.__table__, if_not_exists=True))
    for idx in AlarmHazardLink.__table__.indexes:
        await db_session.execute(CreateIndex(idx, if_not_exists=True))
    await db_session.flush()
    yield


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_committed_rows():
    """端点内 db.commit() 穿透回滚语义（真实行为）——用例后按名前缀清理。"""
    yield
    from app.platform.superagent.models import (
        AgentInput,
        AgentSource,
        AgentTask,
        AgentTaskSubscription,
        AgentTrigger,
    )
    from tests.conftest import _test_session_factory

    async with _test_session_factory() as s:
        for src in (
            await s.execute(select(AgentSource).where(AgentSource.name == "test.r1.api"))
        ).scalars().all():
            for t in (
                await s.execute(
                    select(AgentTrigger).where(AgentTrigger.source_id == src.id)
                )
            ).scalars().all():
                await s.delete(t)
            await s.delete(src)
        for task in (
            await s.execute(select(AgentTask).where(AgentTask.short_name == "t"))
        ).scalars().all():
            await s.execute(
                AgentInput.__table__.delete().where(AgentInput.task_id == task.id)
            )
            await s.execute(
                AgentTaskSubscription.__table__.delete().where(
                    AgentTaskSubscription.task_id == task.id
                )
            )
            await s.delete(task)
        await s.execute(
            AlarmHazardLink.__table__.delete().where(
                AlarmHazardLink.alarm_record_id.in_(
                    ["recL1", "recL2", "recN1", "recT1", "recT9"]
                )
            )
        )
        await s.commit()


async def _add_link(db_session, *, rid: str, hazard: str | None, error: str | None = None):
    row = AlarmHazardLink(
        alarm_domain="fire_alarm", alarm_record_id=rid,
        alarm_fingerprint="fp", hazard_record_id=hazard,
        alarm_snapshot={"报警性质": "泄漏报警"}, error_message=error,
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def test_list_derives_status(
    client: AsyncClient, db_session, links_table,
) -> None:
    """列表：succeeded/failed 派生态 + snapshot 摘要 + 分页 meta。"""
    await _add_link(db_session, rid="recL1", hazard="hzR1")
    await _add_link(db_session, rid="recL2", hazard=None, error="create_record 返回空")
    # client 与 db_session 是不同连接：跨 session 可见必须 commit（残留由清理兜底）
    await db_session.commit()

    resp = await client.get("/api/v1/safety/alarm-hazard-links", params={"page_size": 10})
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    by_rid = {x["alarm_record_id"]: x for x in body}
    assert by_rid["recL1"]["status"] == "succeeded"
    assert by_rid["recL1"]["hazard_record_id"] == "hzR1"
    assert by_rid["recL2"]["status"] == "failed"
    assert by_rid["recL2"]["error_message"]
    assert by_rid["recL1"]["alarm_snapshot"]["报警性质"] == "泄漏报警"

    # status SQL 下推：total 与 data 同口径（不缩页不失真）
    resp_failed = await client.get(
        "/api/v1/safety/alarm-hazard-links",
        params={"status": "failed", "page_size": 10},
    )
    assert resp_failed.status_code == 200, resp_failed.text
    failed_body = resp_failed.json()
    assert failed_body["meta"]["total"] >= 1
    assert {x["alarm_record_id"] for x in failed_body["data"]} == {"recL2"}
    assert all(x["status"] == "failed" for x in failed_body["data"])
    await db_session.rollback()


async def test_refresh_hazard_no_backfills(
    client: AsyncClient, db_session, links_table, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """编号回读：mock 直读隐患表 → hazard_no 回填幂等。"""

    link = await _add_link(db_session, rid="recN1", hazard="hzR9")
    await db_session.commit()

    async def _fake_get_record(self, record_id, table_id=None):  # noqa: ANN001
        assert record_id == "hzR9"
        return {"record": {"fields": {"隐患编号": [{"text": "HZ-20261103-001"}]}}}

    monkeypatch.setattr(
        "app.modules.safety.feishu.bitable_client.SafetyBitableClient.get_record",
        _fake_get_record,
    )
    resp = await client.post(f"/api/v1/safety/alarm-hazard-links/{link.id}/refresh-hazard-no")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["hazard_no"] == "HZ-20261103-001"

    # 已回填再刷：不覆盖（幂等）
    resp2 = await client.post(f"/api/v1/safety/alarm-hazard-links/{link.id}/refresh-hazard-no")
    assert resp2.status_code == 200
    await db_session.rollback()


async def test_retry_reposts_input_for_open_task(
    client: AsyncClient, db_session, links_table,
) -> None:
    """失败重试：open 任务重投 system input；无 task 的行 409。"""

    from app.platform.superagent.models import (
        AgentInput,
        AgentSource,
        AgentTask,
        AgentTrigger,
    )

    src = AgentSource(kind="cron_scan", name="test.r1.api", config={}, enabled=False)
    db_session.add(src)
    await db_session.flush()
    trigger = AgentTrigger(
        source_id=src.id, external_id="fire_alarm:recT1:fp",
        thread_key="bitable:fire_alarm:recT1",
        actor={"id": "recT1", "type": "bitable_record"}, payload={},
    )
    db_session.add(trigger)
    await db_session.flush()
    task = AgentTask(short_name="t", title="t", executor="alarm_hazard_create",
                     status="open", origin_trigger_id=trigger.id)
    db_session.add(task)
    await db_session.flush()
    link = await _add_link(db_session, rid="recT1", hazard=None, error="x")
    link.task_id = task.id
    link_nohazard_norisk = await _add_link(db_session, rid="recT9", hazard=None)
    await db_session.commit()

    resp = await client.post(f"/api/v1/safety/alarm-hazard-links/{link.id}/retry")
    assert resp.status_code == 200, resp.text
    inputs = (
        await db_session.execute(
            select(AgentInput).where(
                AgentInput.task_id == task.id, AgentInput.kind == "system",
            )
        )
    ).scalars().all()
    assert len(inputs) == 1
    assert inputs[0].payload.get("type") == "retry"
    assert inputs[0].delivered_at is not None

    resp409 = await client.post(
        f"/api/v1/safety/alarm-hazard-links/{link_nohazard_norisk.id}/retry"
    )
    assert resp409.status_code == 409
    await db_session.rollback()
