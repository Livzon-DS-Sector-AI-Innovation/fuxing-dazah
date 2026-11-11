"""员工档案同步 HTTP 层（/employee-sync/*）：配置读写、手动同步、脱敏名单。

bitable 飞书调用与 Redis 锁全部 monkeypatch（与 test_employee_sync.py 同策略）。
"""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.modules.hr.deps import HrAccessContext, get_hr_scope
from app.modules.hr.employee_sync import config as sync_config
from app.modules.hr.employee_sync.service import (
    EmployeeSyncService,
    SyncInProgressError,
)
from app.modules.hr.models import TrainingRosterProfile
from tests.modules.hr.conftest import _rand


async def _write_ready_config(db_session: AsyncSession) -> None:
    await sync_config.save_config_values(db_session, {
        sync_config.KEY_ENABLED: "true",
        sync_config.KEY_APP_TOKEN: "app_test_token",
        sync_config.KEY_SOURCE_TABLE_ID: "tbl_source",
    })
    await db_session.flush()


def _scoped(test_user, departments: frozenset[str]):
    async def _override() -> HrAccessContext:
        return HrAccessContext(
            user=test_user,
            data_scope="department",
            department=next(iter(departments)) if departments else None,
            employee_number=test_user.employee_no,
            scoped_departments=departments,
        )
    return _override


# ─── 配置读写 ───


async def test_get_config_defaults_to_disabled(client: AsyncClient):
    """conftest autouse 已把同步写为未启用：读取返回 enabled=false。"""
    res = await client.get("/api/v1/hr/employee-sync/config")
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["enabled"] is False
    assert data["is_ready"] is False


async def test_save_config_requires_binding_before_enable(client: AsyncClient):
    """启用但未绑定 token/table → 400。"""
    res = await client.put("/api/v1/hr/employee-sync/config", json={
        "enabled": True, "app_token": "", "source_table_id": "",
    })
    assert res.status_code == 400
    assert "app_token" in res.json()["message"]


async def test_save_config_validates_connectivity_and_columns(
    db_session: AsyncSession, client: AsyncClient,
):
    """保存配置：连通性校验 + 列匹配报告；容忍粘贴完整链接。"""
    with (
        patch(
            "app.modules.hr.employee_sync.bitable_client.list_tables",
            new=AsyncMock(return_value=[
                {"table_id": "tbl18mDH9QcCdw8a", "name": "员工档案"},
            ]),
        ),
        patch(
            "app.modules.hr.employee_sync.bitable_client.list_fields",
            new=AsyncMock(return_value=[
                {"field_id": "f1", "field_name": "工号"},
                {"field_id": "f2", "field_name": "姓名"},
                {"field_id": "f3", "field_name": "自定义列"},
            ]),
        ),
    ):
        res = await client.put("/api/v1/hr/employee-sync/config", json={
            "enabled": True,
            # 粘贴完整链接：路由层先清洗再校验
            "app_token": "https://x.feishu.cn/base/TOK123?table=tbl18mDH9QcCdw8a",
            "source_table_id": "tbl18mDH9QcCdw8a",
        })
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["enabled"] is True
    assert data["app_token"] == "TOK123"
    assert data["source_table_name"] == "员工档案"
    report = data["column_report"]
    assert report["has_employee_number"] is True
    assert "工号" in report["mapped"]
    assert "自定义列" in report["ignored"]

    # 配置在同一事务内已生效
    cfg_now = await client.get("/api/v1/hr/employee-sync/config")
    assert cfg_now.json()["data"]["is_ready"] is True


async def test_save_config_unknown_table_rejected(client: AsyncClient):
    """绑定的 table_id 不在 Base 中 → 400 且列出可用数据表。"""
    with patch(
        "app.modules.hr.employee_sync.bitable_client.list_tables",
        new=AsyncMock(return_value=[{"table_id": "tblA", "name": "员工档案"}]),
    ):
        res = await client.put("/api/v1/hr/employee-sync/config", json={
            "enabled": False, "app_token": "TOK", "source_table_id": "tblB",
        })
    assert res.status_code == 400
    assert "tblB" in res.json()["message"]
    assert "员工档案" in res.json()["message"]


# ─── 手动同步 ───


async def test_sync_not_ready_returns_400(client: AsyncClient):
    """未启用/未绑定完整时手动同步 → 400。"""
    res = await client.post("/api/v1/hr/employee-sync/sync")
    assert res.status_code == 400
    assert "绑定" in res.json()["message"]


async def test_sync_returns_stats(db_session: AsyncSession, client: AsyncClient):
    """配置就绪时手动同步返回对账统计。"""
    await _write_ready_config(db_session)
    with patch.object(
        EmployeeSyncService, "reconcile",
        new=AsyncMock(return_value={"created": 2, "updated": 1, "deleted": 0, "total": 3, "errors": []}),
    ):
        res = await client.post("/api/v1/hr/employee-sync/sync")
    assert res.status_code == 200, res.text
    assert res.json()["data"]["created"] == 2
    assert res.json()["data"]["total"] == 3


async def test_sync_conflict_returns_409(db_session: AsyncSession, client: AsyncClient):
    """并发同步（锁被占）→ 409。"""
    await _write_ready_config(db_session)
    with patch.object(
        EmployeeSyncService, "reconcile",
        new=AsyncMock(side_effect=SyncInProgressError("同步正在执行中，请稍后再试")),
    ):
        res = await client.post("/api/v1/hr/employee-sync/sync")
    assert res.status_code == 409


# ─── 培训脱敏名单 ───


async def _add_roster(db_session: AsyncSession, department: str) -> TrainingRosterProfile:
    profile = TrainingRosterProfile(
        employee_number=_rand("ROS"), name="名单员工", department=department,
        position="操作工", duty="组员",
    )
    db_session.add(profile)
    await db_session.flush()
    return profile


async def test_training_roster_filters_and_meta(
    db_session: AsyncSession, client: AsyncClient, test_user,
):
    """部门筛选/数据范围过滤 + meta.scoped_departments 标识受限范围。"""
    dept_a, dept_b = _rand("名单A部"), _rand("名单B部")
    pa = await _add_roster(db_session, dept_a)
    await _add_roster(db_session, dept_b)

    # 不限权：部门前缀筛选
    res = await client.get(
        "/api/v1/hr/employee-sync/training-roster", params={"department": dept_a},
    )
    assert res.status_code == 200, res.text
    numbers = {r["employee_number"] for r in res.json()["data"]}
    assert numbers == {pa.employee_number}
    assert res.json()["meta"]["scoped_departments"] is None

    # 受限：只看授权部门，meta 带授权部门列表
    app.dependency_overrides[get_hr_scope] = _scoped(test_user, frozenset({dept_a}))
    try:
        scoped = await client.get("/api/v1/hr/employee-sync/training-roster")
        assert scoped.status_code == 200, scoped.text
        assert {r["employee_number"] for r in scoped.json()["data"]} == {pa.employee_number}
        assert scoped.json()["meta"]["scoped_departments"] == [dept_a]
    finally:
        app.dependency_overrides.pop(get_hr_scope, None)


async def test_training_roster_keyword_search(
    db_session: AsyncSession, client: AsyncClient,
):
    """关键字按姓名/工号模糊匹配。"""
    dept = _rand("搜索部")
    profile = await _add_roster(db_session, dept)
    res = await client.get(
        "/api/v1/hr/employee-sync/training-roster",
        params={"keyword": profile.employee_number},
    )
    assert res.status_code == 200
    assert {r["employee_number"] for r in res.json()["data"]} == {profile.employee_number}


async def test_update_roster_entry_lifecycle(
    db_session: AsyncSession, client: AsyncClient, test_user,
):
    """编辑白名单字段成功；未知工号 404；受限范围外 403。"""
    dept = _rand("编辑部")
    profile = await _add_roster(db_session, dept)

    ok = await client.put(
        f"/api/v1/hr/employee-sync/training-roster/{profile.employee_number}",
        json={"duty": "班长", "team": "一班"},
    )
    assert ok.status_code == 200, ok.text
    await db_session.flush()
    await db_session.refresh(profile)
    assert profile.duty == "班长"

    unknown = await client.put(
        f"/api/v1/hr/employee-sync/training-roster/{_rand('NOPE')}",
        json={"duty": "班长"},
    )
    assert unknown.status_code == 404

    app.dependency_overrides[get_hr_scope] = _scoped(test_user, frozenset({"别的部门"}))
    try:
        forbidden = await client.put(
            f"/api/v1/hr/employee-sync/training-roster/{profile.employee_number}",
            json={"duty": "主管"},
        )
        assert forbidden.status_code == 403
    finally:
        app.dependency_overrides.pop(get_hr_scope, None)
