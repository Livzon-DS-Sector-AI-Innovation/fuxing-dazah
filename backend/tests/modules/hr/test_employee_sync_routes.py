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
from app.platform.identity.models import User
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


# ─── 名单跟随档案规则 ───


_FOLLOW_URL = "/api/v1/hr/employee-sync/training-roster/follow-config"


async def test_roster_follow_config_preview_save_and_validate(
    db_session: AsyncSession, client: AsyncClient, test_user: User,
) -> None:
    """apply=false 只预览不保存；apply=true 保存并立即生效（名单 meta/行带跟随信息）；非法入参 400。

    断言一律相对「保存前」比较：KV 与开发库共享，不假设初始未配置。
    测试行所在部门是随机名，部门规则扫不到真实名单。
    """
    dept = _rand("跟随部")
    profile = await _add_roster(db_session, dept)
    number = profile.employee_number
    original = await sync_config.load_roster_follow_config(db_session)
    try:
        before = (await client.get(_FOLLOW_URL)).json()["data"]
        assert [o["attr"] for o in before["followable"]] \
            == list(sync_config.ROSTER_FOLLOWABLE_FIELDS)
        assert [o["attr"] for o in before["locked"]] == ["status"]
        # 可选部门清单：名单上出现过的体现部门、带人数、不含兜底占位「未分类」
        dept_names = {d["name"] for d in before["departments"]}
        assert all(d["count"] > 0 for d in before["departments"])
        assert "未分类" not in dept_names
        assert dept in dept_names

        # 预览：返回影响统计，规则不落库
        preview = await client.put(_FOLLOW_URL, json={
            "fields": sorted(set(before["fields"]) | {"level"}), "apply": False,
        })
        assert preview.status_code == 200, preview.text
        stats = preview.json()["data"]["preview"]
        assert stats["dry_run"] is True
        assert set(stats["field_changes"]) <= {"level"}
        after_preview = (await client.get(_FOLLOW_URL)).json()["data"]
        assert after_preview["fields"] == before["fields"]

        # 保存并应用：全局字段原样保留；测试行所在部门设「全部跟随档案」，
        # 该行本人再设「全部手动」——人员例外覆盖部门例外，应用时不改动这一行
        fields = before["fields"]
        member_modes = {**before["member_modes"], number: "manual"}
        department_modes = {**before["department_modes"], dept: "follow"}
        saved = await client.put(_FOLLOW_URL, json={
            "fields": fields,
            "member_modes": member_modes,
            "department_modes": department_modes,
            "apply": True,
        })
        assert saved.status_code == 200, saved.text
        assert saved.json()["data"]["preview"]["dry_run"] is False
        data = (await client.get(_FOLLOW_URL)).json()["data"]
        assert data["fields"] == fields
        assert data["member_modes"] == member_modes
        assert data["exceptions"] == [
            *before["exceptions"],
            {"employee_number": number, "mode": "manual",
             "name": "名单员工", "department": dept},
        ]
        assert data["department_modes"] == department_modes
        assert data["department_exceptions"] == [
            *before["department_exceptions"],
            {"department": dept, "mode": "follow", "count": 1},
        ]
        assert dept not in {d["name"] for d in data["departments"]}  # 已配置的不再可选

        # 名单接口：meta 带全局跟随字段与可跟随范围，行带生效的例外模式及来源
        res = await client.get(
            "/api/v1/hr/employee-sync/training-roster",
            params={"keyword": number},
        )
        assert res.status_code == 200, res.text
        assert res.json()["meta"]["follow_fields"] == fields
        assert res.json()["meta"]["followable_fields"] == list(
            sync_config.ROSTER_FOLLOWABLE_FIELDS,
        )
        assert res.json()["data"][0]["follow_mode"] == "manual"
        assert res.json()["data"][0]["follow_source"] == "member"

        # 人员状态不开放配置；未知字段 / 未知部门模式 400
        bad = await client.put(_FOLLOW_URL, json={"fields": ["status"], "apply": False})
        assert bad.status_code == 400
        assert "不可配置" in bad.json()["message"]
        bad_mode = await client.put(_FOLLOW_URL, json={
            "department_modes": {"研发部": "whatever"}, "apply": False,
        })
        assert bad_mode.status_code == 400
        assert "未知的部门跟随模式" in bad_mode.json()["message"]
    finally:
        await sync_config.save_roster_follow_config(db_session, original)
