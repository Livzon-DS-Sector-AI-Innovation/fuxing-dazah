"""facilities-p1 票 03：校验任务查询/聚合/详情 API 集成测试。

sealed_client fixture（conftest）：外层事务 + savepoint，端点内部 commit
只落 savepoint、teardown 整体回滚；播种直接用其返回的 session——设施 API
无建数端点（拍板口径），故不像 test_api.py 那样经 POST 建数。
reopen/cancel 端点随票 04 在 test_facility_closure.py 覆盖。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.modules.safety.models import FacilityCheckTask, FacilityTaskEvent

# 动态今天（北京时间口径，与 query._bj_today 一致）：固定日期会在跨天后
# 把 due=今天 的种子行翻转成逾期（2026-10-21 实际踩过）
TODAY = (datetime.now(UTC) + timedelta(hours=8)).date()


def _mk(ledger_key: str, *, dept: str, group: str, status: str = "issued",
        due: date = TODAY, subtype: str = "校验") -> FacilityCheckTask:
    return FacilityCheckTask(
        biz_type="accessory", ledger_key=ledger_key, equipment_no=f"AQ-{ledger_key}",
        equipment_name=f"设备{ledger_key}", department=dept,
        task_kind="校验", due_date=due, lead_days=30,
        status=status, group_key=group, task_subtype=subtype,
        anchor_at_dispatch=due, issued_on=TODAY - timedelta(days=10),
    )


async def _seed(db):
    db.add_all([
        _mk("k1", dept="提炼一部", group="安全阀·校验"),                       # issued 未逾期
        _mk("k2", dept="提炼一部", group="安全阀·校验", due=TODAY - timedelta(days=2)),  # issued 逾期
        _mk("k3", dept="提炼一部", group="压力表·校验", status="closed",
            due=TODAY - timedelta(days=5)),
        _mk("k4", dept="仓储部", group="灭火器·换药", subtype="换药",
            due=TODAY + timedelta(days=8)),
        _mk("k5", dept="仓储部", group="灭火器·换药", status="cancelled",
            due=TODAY + timedelta(days=3)),
    ])
    await db.flush()
    t = (await db.execute(
        select(FacilityCheckTask).where(
            FacilityCheckTask.ledger_key == "k3")
    )).scalar_one()
    db.add(FacilityTaskEvent(
        task_id=t.id, event_type="issued", operator="system",
        payload={"due_date": (TODAY - timedelta(days=5)).isoformat()},
        created_at=datetime(2026, 10, 10, 8, 10, tzinfo=UTC),
    ))
    db.add(FacilityTaskEvent(
        task_id=t.id, event_type="closed", operator="system", closed_trigger="poll",
        payload={"anchor_before": (TODAY - timedelta(days=5)).isoformat(),
                 "anchor_after": (TODAY + timedelta(days=300)).isoformat()},
        created_at=datetime(2026, 10, 15, 8, 10, tzinfo=UTC),
    ))
    await db.flush()
    return t


async def test_list_tasks_filters_and_pagination(sealed_client):
    ac, db = sealed_client
    await _seed(db)
    # biz_type 圈定：dev 库 2026-10-21 首轮真实派发已有 fire 任务
    resp = await ac.get("/api/v1/safety/facility-tasks",
                        params={"biz_type": "accessory"})
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["total"] == 5

    resp = await ac.get(
        "/api/v1/safety/facility-tasks",
        params={"status": "issued", "department": "提炼一部"},
    )
    items = resp.json()["data"]["items"]
    assert [i["ledger_key"] for i in items] == ["k2", "k1"]  # 逾期在前

    resp = await ac.get("/api/v1/safety/facility-tasks",
                        params={"overdue": True, "biz_type": "accessory"})
    items = resp.json()["data"]["items"]
    assert [i["ledger_key"] for i in items] == ["k2"]
    assert items[0]["overdue"] is True and items[0]["remaining_days"] == -2

    resp = await ac.get(
        "/api/v1/safety/facility-tasks", params={"group_key": "灭火器·换药"}
    )
    assert resp.json()["data"]["total"] == 2


async def test_task_summary_buckets(sealed_client):
    ac, db = sealed_client
    await _seed(db)
    resp = await ac.get("/api/v1/safety/facility-tasks/summary",
                        params={"biz_type": "accessory"})
    data = resp.json()["data"]
    assert data["total"] == 5
    assert data["open"] == 3
    assert data["closed"] == 1
    assert data["cancelled"] == 1
    assert data["overdue"] == 1
    by_dept = {b["department"]: b for b in data["by_department"]}
    assert by_dept["提炼一部"]["groups"][0] == {
        "group_key": "安全阀·校验", "total": 2, "closed": 0,
    }
    assert by_dept["提炼一部"]["total"] == 3 and by_dept["提炼一部"]["closed"] == 1
    # cancelled 不进部门/分组进度桶（NIT18：closed/total 才能满绿）
    assert by_dept["仓储部"]["total"] == 1 and by_dept["仓储部"]["open"] == 1


async def test_task_detail_with_events(sealed_client):
    ac, db = sealed_client
    task = await _seed(db)
    resp = await ac.get(f"/api/v1/safety/facility-tasks/{task.id}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["task"]["ledger_key"] == "k3"
    assert data["task"]["status"] == "closed"
    assert [e["event_type"] for e in data["events"]] == ["issued", "closed"]
    assert data["events"][1]["payload"]["anchor_after"] == (
        TODAY + timedelta(days=300)
    ).isoformat()


async def test_task_detail_404(sealed_client):
    import uuid

    ac, _db = sealed_client
    resp = await ac.get(f"/api/v1/safety/facility-tasks/{uuid.uuid4()}")
    assert resp.status_code == 404
