"""环境监测测试：点位台账 CRUD、双限三态判定、记录填报快照限值、应测未测、超限闭环。

注意：db_session 是回滚式夹具（teardown rollback），测试内不 commit。
"""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import today as _app_today
from app.modules.quality.api._env import _env_judge
from app.modules.quality.repository import (
    create_env_point,
    create_env_record,
    delete_env_point,
    delete_env_record,
    env_missed_points,
    generate_env_plans,
    get_env_point,
    handle_env_record,
    list_env_plans,
    list_env_points,
    list_env_records,
    update_env_point,
)


def _rand_no() -> str:
    return f"P-{uuid.uuid4().hex[:6].upper()}"


def _point(**kw: Any) -> dict:
    base = {
        "room": "灌装间",
        "point_no": _rand_no(),
        "monitor_type": "settle",
        "frequency": "weekly",
        "alert_limit": 5.0,
        "action_limit": 10.0,
    }
    base.update(kw)
    return base


def test_env_judge_rules() -> None:
    # 超行动限 / 超警戒限 / 合格 / 无值
    assert _env_judge(15, 5, 10) == "action"
    assert _env_judge(7, 5, 10) == "alert"
    assert _env_judge(3, 5, 10) == "pass"
    assert _env_judge(None, 5, 10) is None
    # 单限：只有警戒限时 action 不生效
    assert _env_judge(15, 5, None) == "alert"
    # 行动限等于值时仍合格（超限才触发）
    assert _env_judge(10, 5, 10) == "alert"


async def test_env_point_crud(db_session: AsyncSession) -> None:
    point = await create_env_point(db_session, _point())
    got = await get_env_point(db_session, point.id)
    assert got is not None and got.point_no == point.point_no and got.status == "active"

    await update_env_point(db_session, point.id, {"action_limit": 20.0, "status": "inactive"})
    got2 = await get_env_point(db_session, point.id)
    assert got2 is not None and got2.action_limit == 20.0 and got2.status == "inactive"

    # 列表过滤：点位编号模糊 / 类型
    rows = await list_env_points(db_session, keyword=point.point_no[:4])
    assert any(p.id == point.id for p in rows)
    rows_settle = await list_env_points(db_session, monitor_type="settle")
    assert all(p.monitor_type == "settle" for p in rows_settle)

    assert await delete_env_point(db_session, point.id) is True
    assert await get_env_point(db_session, point.id) is None


async def test_env_record_fill_and_list(db_session: AsyncSession) -> None:
    point = await create_env_point(db_session, _point())
    rec = await create_env_record(db_session, {
        "point_id": point.id,
        "record_date": "2026-10-21",
        "result_value": 12.0,
        "alert_limit": point.alert_limit,
        "action_limit": point.action_limit,
        "judge": "action",
        "remark": "超行动限示例",
    })
    rows = await list_env_records(db_session, point_id=point.id)
    assert len(rows) == 1
    item = rows[0]
    assert item["id"] == rec.id
    assert item["point_no"] == point.point_no and item["room"] == "灌装间"
    assert item["monitor_type"] == "settle"
    assert item["judge"] == "action"
    assert item["alert_limit"] == 5.0 and item["action_limit"] == 10.0

    # 判定筛选与软删除
    assert await list_env_records(db_session, judge="action") != []
    assert await list_env_records(db_session, judge="pass") == []
    assert await delete_env_record(db_session, rec.id) is True
    assert await list_env_records(db_session, point_id=point.id) == []


async def test_env_missed_points(db_session: AsyncSession) -> None:
    today = _app_today()
    # 每周点位：本周无记录 → 欠账
    weekly_no_record = await create_env_point(db_session, _point(frequency="weekly"))
    # 每周点位：本周有记录 → 不欠账
    weekly_ok = await create_env_point(db_session, _point(frequency="weekly"))
    await create_env_record(db_session, {
        "point_id": weekly_ok.id, "record_date": today.isoformat(),
        "result_value": 3.0, "alert_limit": 5.0, "action_limit": 10.0, "judge": "pass",
    })
    # 每月点位：上月有记录 → 欠账
    monthly_stale = await create_env_point(db_session, _point(frequency="monthly"))
    await create_env_record(db_session, {
        "point_id": monthly_stale.id,
        "record_date": (today - timedelta(days=40)).isoformat(),
        "result_value": 3.0, "alert_limit": 5.0, "action_limit": 10.0, "judge": "pass",
    })
    # 每批点位：不参与自动点名
    await create_env_point(db_session, _point(frequency="per_batch"))
    # 停用点位：不点名
    await create_env_point(db_session, _point(frequency="weekly", status="inactive"))

    missed = await env_missed_points(db_session)
    missed_keys = {(m["point_no"], m["frequency"]) for m in missed}
    assert (weekly_no_record.point_no, "weekly") in missed_keys
    assert (monthly_stale.point_no, "monthly") in missed_keys
    assert (weekly_ok.point_no, "weekly") not in missed_keys
    # 每批与停用点位不出现
    assert all(m["frequency"] != "per_batch" for m in missed)
    # 欠账记录带上次检测日期
    stale = next(m for m in missed if m["point_no"] == monthly_stale.point_no)
    assert stale["last_date"] == (today - timedelta(days=40)).isoformat()


async def test_env_plans_generate_and_complete(db_session: AsyncSession) -> None:
    today = _app_today()
    # 每周点位：本周期无记录 → 生成计划
    weekly_due = await create_env_point(db_session, _point(frequency="weekly"))
    # 每周点位：本周期已有记录 → 不生成
    weekly_ok = await create_env_point(db_session, _point(frequency="weekly"))
    await create_env_record(db_session, {
        "point_id": weekly_ok.id, "record_date": today.isoformat(),
        "result_value": 3.0, "alert_limit": 5.0, "action_limit": 10.0, "judge": "pass",
    })
    # 每月点位：本月无记录 → 生成
    monthly_due = await create_env_point(db_session, _point(frequency="monthly"))
    # 每批点位：不参与自动点名
    await create_env_point(db_session, _point(frequency="per_batch"))
    # 停用点位：不点名
    await create_env_point(db_session, _point(frequency="weekly", status="inactive"))

    created = await generate_env_plans(db_session, today.isoformat())
    assert created == 2
    # 幂等：同一天重复生成不新增
    assert await generate_env_plans(db_session, today.isoformat()) == 0

    plans = await list_env_plans(db_session, today.isoformat())
    by_no = {p["point_no"]: p for p in plans}
    assert set(by_no) == {weekly_due.point_no, monthly_due.point_no}
    assert by_no[weekly_due.point_no]["completed"] is False
    assert by_no[weekly_due.point_no]["frequency"] == "weekly"

    # 当日填报后完成状态派生为 True
    await create_env_record(db_session, {
        "point_id": weekly_due.id, "record_date": today.isoformat(),
        "result_value": 3.0, "alert_limit": 5.0, "action_limit": 10.0, "judge": "pass",
    })
    plans = await list_env_plans(db_session, today.isoformat())
    by_no = {p["point_no"]: p for p in plans}
    assert by_no[weekly_due.point_no]["completed"] is True
    assert by_no[weekly_due.point_no]["completed_at"] == today.isoformat()


async def test_env_record_handle_closure(db_session: AsyncSession) -> None:
    point = await create_env_point(db_session, _point())
    rec = await create_env_record(db_session, {
        "point_id": point.id, "record_date": "2026-10-22",
        "result_value": 15.0, "alert_limit": 5.0, "action_limit": 10.0, "judge": "action",
    })
    assert rec.handle_status == "open"
    updated = await handle_env_record(db_session, rec.id, {
        "handle_status": "handled", "handled_at": "2026-10-22",
        "handled_remark": "已现场处置并复核", "updated_by": None,
    })
    assert updated is not None and updated.handle_status == "handled"
    assert updated.handled_at == "2026-10-22" and updated.handled_remark == "已现场处置并复核"

    # 列表带处理字段与筛选
    rows = await list_env_records(db_session, judge="action", handle_status="handled")
    assert len(rows) == 1 and rows[0]["handle_status"] == "handled"
    assert await list_env_records(db_session, judge="action", handle_status="open") == []
