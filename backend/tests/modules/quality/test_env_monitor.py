"""环境监测测试：点位台账 CRUD、双限三态判定、记录填报快照限值。

注意：db_session 是回滚式夹具（teardown rollback），测试内不 commit。
"""

import uuid

from app.modules.quality.api._env import _env_judge
from app.modules.quality.repository import (
    create_env_point,
    create_env_record,
    delete_env_point,
    delete_env_record,
    get_env_point,
    list_env_points,
    list_env_records,
    update_env_point,
)


def _rand_no() -> str:
    return f"P-{uuid.uuid4().hex[:6].upper()}"


def _point(**kw) -> dict:
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


def test_env_judge_rules():
    # 超行动限 / 超警戒限 / 合格 / 无值
    assert _env_judge(15, 5, 10) == "action"
    assert _env_judge(7, 5, 10) == "alert"
    assert _env_judge(3, 5, 10) == "pass"
    assert _env_judge(None, 5, 10) is None
    # 单限：只有警戒限时 action 不生效
    assert _env_judge(15, 5, None) == "alert"
    # 行动限等于值时仍合格（超限才触发）
    assert _env_judge(10, 5, 10) == "alert"


async def test_env_point_crud(db_session):
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


async def test_env_record_fill_and_list(db_session):
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
