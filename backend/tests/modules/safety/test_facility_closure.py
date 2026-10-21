"""facilities-p1 票 04：闭环双通道 + reopen/cancel 干预。

覆盖：
- process_row_change（事件通道共用内核）：锚点前移闭环 trigger=event、
  行删除/停用 cancelled、只改无关列不闭环；
- event_handler：匹配已登记连接才处理 + v2 action_list 解析（monkeypatch
  store 连接 + reader 替身）；
- 对账通道 trigger=poll（dispatch 侧已在 test_facility_dispatch 覆盖）；
- API reopen/cancel：404/409/422/200 与事件留痕。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from app.modules.safety.facilities.closure import (
    cancel_task,
    process_row_change,
    reopen_task,
)
from app.modules.safety.facilities.ledger import (
    BIZ_ACCESSORY,
    to_view,
)
from app.modules.safety.models import (
    FacilityCheckTask,
    FacilityNoticeBatch,
    FacilityTaskEvent,
)

from .test_facilities_ledger import _ms, _rec

TODAY = date(2026, 10, 20)


def _mk_task(ledger_key: str, *, due: date, issued_on: date = TODAY,
             dept: str = "提炼一部", status: str = "issued") -> FacilityCheckTask:
    return FacilityCheckTask(
        biz_type=BIZ_ACCESSORY, ledger_key=ledger_key,
        equipment_no=f"AQ-{ledger_key}", department=dept,
        task_kind="校验", due_date=due, lead_days=30, status=status,
        group_key="安全阀·校验", task_subtype="校验",
        anchor_at_dispatch=due, issued_on=issued_on,
    )


def _view(rid: str, *, anchor: date | None, last: date | None = None,
          status: str = ""):
    fields: dict[str, Any] = {"设备编号": f"AQ-{rid}", "责任部门": "提炼一部"}
    if anchor is not None:
        fields["下次校验日期"] = _ms(anchor)
    if last is not None:
        fields["上次校验日期"] = _ms(last)
    if status:
        fields["设备状态"] = status
    return to_view(_rec(rid, fields), BIZ_ACCESSORY)


# ── process_row_change（实时通道内核）───────────────────────────────


async def test_event_channel_closes_on_anchor_advanced(db_session):
    task = _mk_task("r1", due=TODAY + timedelta(days=5))
    db_session.add(task)
    await db_session.flush()

    stats = await process_row_change(
        db_session, BIZ_ACCESSORY, "r1", deleted=False,
        view=_view("r1", anchor=TODAY + timedelta(days=300)),
    )
    assert stats == {"closed": 1, "cancelled": 0}
    assert task.status == "closed"
    assert task.closed_trigger == "event"
    ev = (await db_session.execute(
        select(FacilityTaskEvent).where(FacilityTaskEvent.task_id == task.id)
    )).scalars().one()
    assert ev.event_type == "closed"
    assert ev.payload["anchor_after"] == (TODAY + timedelta(days=300)).isoformat()


async def test_event_channel_closes_on_new_last_date(db_session):
    task = _mk_task("r2", due=TODAY + timedelta(days=5), issued_on=TODAY)
    db_session.add(task)
    await db_session.flush()

    stats = await process_row_change(
        db_session, BIZ_ACCESSORY, "r2", deleted=False,
        view=_view("r2", anchor=TODAY + timedelta(days=5), last=TODAY),
    )
    assert stats["closed"] == 1


async def test_event_channel_ignores_unrelated_change(db_session):
    task = _mk_task("r3", due=TODAY + timedelta(days=5))
    db_session.add(task)
    await db_session.flush()

    stats = await process_row_change(
        db_session, BIZ_ACCESSORY, "r3", deleted=False,
        view=_view("r3", anchor=TODAY + timedelta(days=5), last=TODAY - timedelta(days=300)),
    )
    assert stats == {"closed": 0, "cancelled": 0}
    assert task.status == "issued"


async def test_event_channel_cancels_on_row_deleted(db_session):
    task = _mk_task("r4", due=TODAY + timedelta(days=5))
    db_session.add(task)
    await db_session.flush()

    stats = await process_row_change(
        db_session, BIZ_ACCESSORY, "r4", deleted=True, view=None,
    )
    assert stats == {"closed": 0, "cancelled": 1}
    assert task.status == "cancelled"
    assert "删除" in task.closed_reason


async def test_event_channel_cancels_on_row_stopped(db_session):
    task = _mk_task("r5", due=TODAY + timedelta(days=5))
    db_session.add(task)
    await db_session.flush()

    stats = await process_row_change(
        db_session, BIZ_ACCESSORY, "r5", deleted=False,
        view=_view("r5", anchor=TODAY + timedelta(days=5), status="停用"),
    )
    assert stats["cancelled"] == 1
    assert "停用" in task.closed_reason


async def test_notifier_receives_changed_departments(db_session):
    task = _mk_task("r6", due=TODAY + timedelta(days=5))
    db_session.add(task)
    await db_session.flush()

    seen: list[list[str]] = []

    class Spy:
        async def on_tasks_changed(self, session, departments):
            seen.append(list(departments))

    await process_row_change(
        db_session, BIZ_ACCESSORY, "r6", deleted=True, view=None, notifier=Spy(),
    )
    assert seen == [["提炼一部"]]


# ── reopen / cancel（内核语义）───────────────────────────────────────


async def test_reopen_resets_to_issued_and_clears_archived_batch(db_session):
    task = _mk_task("r7", due=TODAY + timedelta(days=5), status="closed")
    task.closed_trigger = "poll"
    batch = FacilityNoticeBatch(department="提炼一部", status="archived")
    db_session.add_all([task, batch])
    await db_session.flush()
    task.batch_id = batch.id

    ok = await reopen_task(db_session, task, operator="ou_admin", reason="误关")
    assert ok is True
    assert task.status == "issued"
    assert task.closed_trigger is None
    assert task.batch_id is None  # 批次已归档 → 清空

    events = (await db_session.execute(
        select(FacilityTaskEvent).where(FacilityTaskEvent.task_id == task.id)
    )).scalars().all()
    assert events[-1].event_type == "reopened"
    assert events[-1].operator == "ou_admin"


async def test_reopen_keeps_open_batch_link(db_session):
    task = _mk_task("r8", due=TODAY + timedelta(days=5), status="cancelled")
    batch = FacilityNoticeBatch(department="提炼一部", status="open")
    db_session.add(batch)
    await db_session.flush()
    task.batch_id = batch.id

    await reopen_task(db_session, task, operator="ou_admin")
    assert task.status == "issued"
    assert task.batch_id == batch.id


async def test_reopen_noop_when_issued(db_session):
    task = _mk_task("r9", due=TODAY)
    db_session.add(task)
    await db_session.flush()
    assert await reopen_task(db_session, task, operator="ou_admin") is False


async def test_cancel_manual_records_reason_and_operator(db_session):
    task = _mk_task("r10", due=TODAY)
    db_session.add(task)
    await db_session.flush()

    await cancel_task(
        db_session, task, trigger="manual", reason="设备已淘汰", operator="ou_admin",
    )
    assert task.status == "cancelled"
    assert task.closed_trigger == "manual"
    assert task.closed_reason == "设备已淘汰"
    assert task.closed_by == "ou_admin"
    ev = (await db_session.execute(
        select(FacilityTaskEvent).where(FacilityTaskEvent.task_id == task.id)
    )).scalars().one()
    assert ev.event_type == "cancelled"
    assert ev.payload["reason"] == "设备已淘汰"


# ── event_handler 匹配与解析 ────────────────────────────────────────


def _fake_conn(app_token: str, table_id: str, enabled: bool = True):
    class Conn:
        pass
    c = Conn()
    c.app_token, c.table_id, c.enabled = app_token, table_id, enabled
    return c


async def test_match_facilities_biz_via_store(monkeypatch):
    from app.modules.safety.facilities import event_handler as eh

    conns = {
        ("facilities", "accessory_ledger"): _fake_conn("tokA", "tbl1"),
        ("facilities", "fire_equipment_ledger"): _fake_conn("tokF", "tbl2"),
    }

    def fake_get(domain, kind):
        return conns.get((domain, kind))
    monkeypatch.setattr(eh.store, "get_connection", fake_get)

    assert eh.match_facilities_biz("tokA", "tbl1") == BIZ_ACCESSORY
    assert eh.match_facilities_biz("tokF", "tbl2") == "fire_equipment"
    assert eh.match_facilities_biz("tokA", "tblX") is None
    assert eh.match_facilities_biz("unknown", "tbl1") is None
    assert eh.match_facilities_biz("", "") is None


async def test_event_handler_ignores_unregistered_table(monkeypatch, db_session):
    """未登记连接（一期常态）→ handler 直接返回，零副作用。"""
    from app.modules.safety.facilities import event_handler as eh

    called = []

    async def boom_process(*a, **k):
        called.append(a)
    monkeypatch.setattr(eh, "_process_batch", boom_process)
    # 不 patch store：真实 store 无 facilities 连接 → 不匹配
    await eh.handle_facilities_record_changed({
        "file_token": "tok_unknown", "table_id": "tbl_unknown",
        "action_list": [{"record_id": "r1", "action": "record_edited"}],
    })
    assert called == []


async def test_event_handler_dispatches_action_list(monkeypatch, db_session):
    from app.modules.safety.facilities import event_handler as eh

    monkeypatch.setattr(
        eh.store, "get_connection",
        lambda domain, kind: _fake_conn("tokA", "tbl1") if kind == "accessory_ledger" else None,
    )
    processed: list[tuple[str, list[tuple[str, bool]]]] = []

    async def fake_process(biz, actions):
        processed.append((biz, actions))

    monkeypatch.setattr(eh, "_process_batch", fake_process)
    await eh.handle_facilities_record_changed({
        "file_token": "tokA", "table_id": "tbl1",
        "action_list": [
            {"record_id": "r1", "action": "record_edited"},
            {"record_id": "r2", "action": "record_deleted"},
            {"record_id": "", "action": "record_edited"},  # 无 record_id 跳过
        ],
    })
    assert processed == [(BIZ_ACCESSORY, [("r1", False), ("r2", True)])]


async def test_event_handler_flat_format_compat(monkeypatch):
    from app.modules.safety.facilities import event_handler as eh

    monkeypatch.setattr(
        eh.store, "get_connection",
        lambda domain, kind: _fake_conn("tokA", "tbl1") if kind == "accessory_ledger" else None,
    )
    processed: list[tuple[str, list[tuple[str, bool]]]] = []

    async def fake_process(biz, actions):
        processed.append((biz, actions))
    monkeypatch.setattr(eh, "_process_batch", fake_process)
    await eh.handle_facilities_record_changed({
        "file_token": "tokA", "table_id": "tbl1",
        "record_id": "r9", "action": "record_deleted",
    })
    assert processed == [(BIZ_ACCESSORY, [("r9", True)])]


# ── API reopen/cancel ──────────────────────────────────────────────


async def test_api_reopen_and_cancel(sealed_client):
    ac, db = sealed_client
    t_closed = _mk_task("c1", due=TODAY - timedelta(days=1), status="closed")
    t_open = _mk_task("c2", due=TODAY + timedelta(days=3))
    db.add_all([t_closed, t_open])
    await db.flush()

    # reopen 误关任务
    resp = await ac.post(
        f"/api/v1/safety/facility-tasks/{t_closed.id}/reopen",
        json={"reason": "误关恢复"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["task"]["status"] == "issued"
    events = resp.json()["data"]["events"]
    assert events[-1]["event_type"] == "reopened"

    # cancel 必填原因
    resp = await ac.post(
        f"/api/v1/safety/facility-tasks/{t_open.id}/cancel", json={"reason": "  "}
    )
    assert resp.status_code == 422

    resp = await ac.post(
        f"/api/v1/safety/facility-tasks/{t_open.id}/cancel",
        json={"reason": "设备已淘汰报废"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["task"]["status"] == "cancelled"
    assert data["task"]["closed_trigger"] == "manual"
    assert data["task"]["closed_reason"] == "设备已淘汰报废"

    # 已取消任务不可再 cancel（409）
    resp = await ac.post(
        f"/api/v1/safety/facility-tasks/{t_open.id}/cancel", json={"reason": "再取消"}
    )
    assert resp.status_code == 409

    # issued 任务不可 reopen（409）
    resp = await ac.post(
        f"/api/v1/safety/facility-tasks/{t_closed.id}/reopen", json={}
    )
    assert resp.status_code == 409


async def test_api_reopen_404(sealed_client):
    import uuid

    ac, _db = sealed_client
    resp = await ac.post(
        f"/api/v1/safety/facility-tasks/{uuid.uuid4()}/reopen", json={}
    )
    assert resp.status_code == 404

async def test_fire_refill_task_not_closed_by_last_date(db_session):
    """MINOR5 回归：换药任务只认换药到期列前移，不被「上次检查日期」连坐闭环。"""
    fields = {
        "器材编号": "FE-1", "责任部门": "仓储部", "类别": "灭火器",
        "换药到期": _ms(TODAY + timedelta(days=5)),
        "下次检查日期": _ms(TODAY + timedelta(days=200)),
        "上次检查日期": _ms(TODAY - timedelta(days=300)),
    }
    from app.modules.safety.facilities.ledger import BIZ_FIRE
    from app.modules.safety.facilities.ledger import to_view as _tv

    task = FacilityCheckTask(
        biz_type=BIZ_FIRE, ledger_key="fe1", equipment_no="FE-1",
        department="仓储部", task_kind="检查",
        due_date=TODAY + timedelta(days=5), lead_days=30,
        group_key="灭火器·换药", task_subtype="换药",
        anchor_at_dispatch=TODAY + timedelta(days=5), issued_on=TODAY - timedelta(days=3),
    )
    db_session.add(task)
    await db_session.flush()

    # 只更新「上次检查日期」=今天：换药锚点未动 → 不闭环
    view = _tv(_rec("fe1", {**fields, "上次检查日期": _ms(TODAY)}), BIZ_FIRE)
    stats = await process_row_change(
        db_session, BIZ_FIRE, "fe1", deleted=False, view=view,
    )
    assert stats == {"closed": 0, "cancelled": 0}

    # 换药到期列前移 → 闭环
    view2 = _tv(_rec("fe1", {**fields, "换药到期": _ms(TODAY + timedelta(days=400))}), BIZ_FIRE)
    stats2 = await process_row_change(
        db_session, BIZ_FIRE, "fe1", deleted=False, view=view2,
    )
    assert stats2 == {"closed": 1, "cancelled": 0}
    assert task.closed_trigger == "event"
