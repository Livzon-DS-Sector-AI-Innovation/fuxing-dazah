"""招聘岗位信息（岗位库上的岗位职责 / 任职要求）接口测试。

- 列表 / 详情 / 保存（含清空）、岗位不存在 404
- 数据范围：受部门范围限制的用户只看得到授权部门的岗位，越权读写 403；self_only 列表为空
- 权限：查看走 hr:recruitment:read，保存走 hr:recruitment:manage
- 新建岗位需求两个描述字段都没传时，带出岗位库里配置的招聘岗位信息；传了任意一个就完全按传入的来
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.modules.hr.deps import HrAccessContext, get_hr_scope
from app.modules.hr.models import HrDepartment, HrPosition
from app.platform.identity.models import User
from tests.modules.hr.conftest import _rand

BASE = "/api/v1/hr/recruitment/position-infos"


def _mk_position(
    db: AsyncSession, department: str, *, name: str | None = None, **kw,
) -> HrPosition:
    position = HrPosition(id=uuid4(), department=department, name=name or _rand("岗位"), **kw)
    db.add(position)
    return position


async def _row_of(client: AsyncClient, position_id, keyword: str) -> dict:
    res = await client.get(BASE, params={"keyword": keyword})
    assert res.status_code == 200, res.text
    return next(r for r in res.json()["data"] if r["position_id"] == str(position_id))


def _scoped_client(test_user: User, *, data_scope: str, departments: frozenset[str] = frozenset()) -> None:
    """把 get_hr_scope 覆写为指定的数据范围（client 夹具 teardown 会统一清理）。"""

    async def _override() -> HrAccessContext:
        return HrAccessContext(
            user=test_user,
            data_scope=data_scope,
            department=next(iter(departments)) if departments else None,
            employee_number=test_user.employee_no,
            scoped_departments=departments,
        )

    app.dependency_overrides[get_hr_scope] = _override


class TestRecruitmentPositionInfo:
    async def test_save_get_and_clear(self, db_session: AsyncSession, client: AsyncClient, test_user: User):
        dept = _rand("招聘信息部门")
        position = _mk_position(db_session, dept)
        await db_session.flush()

        # 未配置：列表里有这个岗位，标成未配置；概要不带描述正文
        row = await _row_of(client, position.id, dept)
        assert row["configured"] is False
        assert row["duties_length"] == 0 and row["requirements_length"] == 0
        assert row["excerpt"] is None
        assert row["updated_by_name"] is None
        assert "duties" not in row

        # 保存：首尾空白去掉，记下最后修改人
        res = await client.put(f"{BASE}/{position.id}", json={
            "duties": "  负责车间日常管理\n", "requirements": "本科及以上",
        })
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert data["duties"] == "负责车间日常管理"
        assert data["requirements"] == "本科及以上"
        assert data["configured"] is True
        assert data["department"] == dept and data["position_name"] == position.name
        assert data["updated_by_name"] == test_user.name
        assert data["updated_at"] is not None

        # 详情与列表概要保持一致
        res = await client.get(f"{BASE}/{position.id}")
        assert res.status_code == 200, res.text
        assert res.json()["data"]["duties"] == "负责车间日常管理"
        row = await _row_of(client, position.id, dept)
        assert row["configured"] is True
        assert row["duties_length"] == len("负责车间日常管理")
        assert row["requirements_length"] == len("本科及以上")
        assert row["updated_by_name"] == test_user.name
        assert row["excerpt"] == "负责车间日常管理"

        # 清空：回到未配置
        res = await client.put(f"{BASE}/{position.id}", json={"duties": "  ", "requirements": None})
        assert res.status_code == 200, res.text
        assert res.json()["data"]["configured"] is False
        row = await _row_of(client, position.id, dept)
        assert row["configured"] is False

    async def test_list_filters(self, db_session: AsyncSession, client: AsyncClient):
        dept = _rand("筛选部门")
        configured = _mk_position(
            db_session, dept, name=_rand("已配置岗位"), recruitment_duties="岗位职责",
        )
        missing = _mk_position(db_session, dept, name=_rand("未配置岗位"))
        await db_session.flush()

        # 按部门
        ids = {r["position_id"] for r in (await client.get(BASE, params={"department": dept})).json()["data"]}
        assert ids == {str(configured.id), str(missing.id)}
        # 只看未配置
        ids = {r["position_id"] for r in (await client.get(BASE, params={"only_missing": True, "keyword": dept})).json()["data"]}
        assert ids == {str(missing.id)}
        # 关键字匹配岗位名
        res = await client.get(BASE, params={"keyword": missing.name})
        assert [r["position_id"] for r in res.json()["data"]] == [str(missing.id)]

    async def test_list_orders_departments_like_org_chart(self, db_session: AsyncSession, client: AsyncClient):
        """部门按组织架构里的建立先后排；不在组织架构里的历史部门名排最后。"""
        early, late, legacy = _rand("早建部门"), _rand("晚建部门"), _rand("历史部门")
        stamp = datetime(2026, 1, 1, tzinfo=UTC)
        for offset, name in enumerate((early, late)):  # 建得越早越靠前，同部门管理
            db_session.add(HrDepartment(
                id=uuid4(), name=name, code=_rand("CODE"), created_at=stamp + timedelta(days=offset),
            ))
        for dept in (legacy, late, early):
            _mk_position(db_session, dept)
        await db_session.flush()

        res = await client.get(BASE, params={"keyword": "部门"})
        names = [row["department"] for row in res.json()["data"]]
        assert names.index(early) < names.index(late) < names.index(legacy)

    async def test_missing_position_404(self, client: AsyncClient):
        missing = uuid4()
        assert (await client.get(f"{BASE}/{missing}")).status_code == 404
        assert (await client.put(f"{BASE}/{missing}", json={"duties": "x"})).status_code == 404

    async def test_deleted_position_404(self, db_session: AsyncSession, client: AsyncClient):
        dept = _rand("已删岗位部门")
        removed = _mk_position(db_session, dept, is_deleted=True)
        await db_session.flush()
        assert (await client.get(f"{BASE}/{removed.id}")).status_code == 404
        assert (await client.get(BASE, params={"keyword": dept})).json()["data"] == []


class TestRecruitmentPositionInfoScope:
    async def test_department_scope(self, db_session: AsyncSession, client: AsyncClient, test_user: User):
        dept_a, dept_b = _rand("招聘信息部门A"), _rand("招聘信息部门B")
        own, other = _mk_position(db_session, dept_a), _mk_position(db_session, dept_b)
        await db_session.flush()
        _scoped_client(test_user, data_scope="department", departments=frozenset({dept_a}))

        # 只看得到授权部门的岗位；指定授权外的部门也查不到
        assert [r["position_id"] for r in (await client.get(BASE, params={"keyword": dept_a})).json()["data"]] == [str(own.id)]
        assert (await client.get(BASE, params={"keyword": dept_b})).json()["data"] == []
        assert (await client.get(BASE, params={"department": dept_b})).json()["data"] == []

        # 越权读、写都 403；本部门可写
        assert (await client.get(f"{BASE}/{other.id}")).status_code == 403
        assert (await client.put(f"{BASE}/{other.id}", json={"duties": "越权"})).status_code == 403
        res = await client.put(f"{BASE}/{own.id}", json={"duties": "本部门"})
        assert res.status_code == 200, res.text

    async def test_self_only_sees_nothing(self, db_session: AsyncSession, client: AsyncClient, test_user: User):
        dept = _rand("本人范围部门")
        _mk_position(db_session, dept)
        await db_session.flush()
        _scoped_client(test_user, data_scope="self_only")

        assert (await client.get(BASE, params={"keyword": dept})).json()["data"] == []

    async def test_write_requires_manage_permission(self, db_session: AsyncSession, client: AsyncClient):
        dept = _rand("只读权限部门")
        position = _mk_position(db_session, dept)
        await db_session.flush()

        async def _read_only(user_id: str, db: object) -> set[str]:
            return {"hr:recruitment:read"}

        with patch("app.platform.permission.deps.get_user_permissions", new=_read_only):
            # 只读可以看，不能改
            assert (await client.get(f"{BASE}/{position.id}")).status_code == 200
            assert (await client.put(f"{BASE}/{position.id}", json={"duties": "x"})).status_code == 403

        async def _position_only(user_id: str, db: object) -> set[str]:
            return {"hr:position:read", "hr:position:manage"}

        with patch("app.platform.permission.deps.get_user_permissions", new=_position_only):
            # 岗位管理权限不等于招聘权限：招聘岗位信息不走岗位管理的权限码
            assert (await client.get(f"{BASE}/{position.id}")).status_code == 403
            assert (await client.put(f"{BASE}/{position.id}", json={"duties": "x"})).status_code == 403


class TestJobRequirementUsesPositionInfo:
    async def test_default_fill(self, db_session: AsyncSession, client: AsyncClient):
        dept = _rand("带出部门")
        configured = _mk_position(
            db_session, dept, name="配置过的岗位",
            recruitment_duties="岗位职责甲", recruitment_requirements="任职要求甲",
        )
        partial = _mk_position(db_session, dept, name="只填了职责的岗位", recruitment_duties="岗位职责乙")
        _mk_position(db_session, dept, name="没配置的岗位")
        await db_session.flush()
        url = "/api/v1/hr/job-requirements"

        # 概要的开头一段：职责优先；只有任职要求时取任职要求，换行压成空格
        excerpt = {r["position_name"]: r["excerpt"] for r in (await client.get(BASE, params={"department": dept})).json()["data"]}
        assert excerpt[configured.name] == "岗位职责甲"
        assert excerpt[partial.name] == "岗位职责乙"
        assert excerpt["没配置的岗位"] is None

        # 两个描述字段都没传 → 带出岗位库里配置的
        res = await client.post(url, json={"position_name": configured.name, "department": dept})
        assert res.status_code == 201, res.text
        assert res.json()["data"]["duties"] == "岗位职责甲"
        assert res.json()["data"]["requirements"] == "任职要求甲"

        # 只配置了一项：带出已填的，另一项为空
        res = await client.post(url, json={"position_name": partial.name, "department": dept})
        assert res.json()["data"]["duties"] == "岗位职责乙"
        assert res.json()["data"]["requirements"] is None

        # 岗位没配置 → 照旧为空
        res = await client.post(url, json={"position_name": "没配置的岗位", "department": dept})
        assert res.json()["data"]["duties"] is None
        assert res.json()["data"]["requirements"] is None

        # 传了任意一个描述字段（哪怕是空串）→ 完全按传入的来，不偷偷补另一项
        res = await client.post(url, json={
            "position_name": configured.name, "department": dept, "requirements": "本次另有要求",
        })
        assert res.json()["data"]["requirements"] == "本次另有要求"
        assert res.json()["data"]["duties"] is None
        res = await client.post(url, json={
            "position_name": configured.name, "department": dept, "duties": "", "requirements": "",
        })
        # 空串按「没填」存
        assert res.json()["data"]["duties"] is None
        assert res.json()["data"]["requirements"] is None

    async def test_update_can_clear_description(self, db_session: AsyncSession, client: AsyncClient):
        """编辑岗位需求时把描述删光再保存，要真的清掉；没传的字段不动。"""
        position = _mk_position(db_session, _rand("清空部门"), name="清空测试岗位", recruitment_duties="原职责")
        res = await client.post("/api/v1/hr/job-requirements", json={
            "position_name": position.name, "department": position.department,
        })
        assert res.json()["data"]["duties"] == "原职责"
        jid = res.json()["data"]["id"]

        res = await client.put(f"/api/v1/hr/job-requirements/{jid}", json={"duties": "", "headcount": 3})
        assert res.status_code == 200, res.text
        assert res.json()["data"]["duties"] is None
        assert res.json()["data"]["headcount"] == 3

    async def test_fill_matches_department(self, db_session: AsyncSession, client: AsyncClient):
        """同名岗位在不同部门各有各的描述：按（需求部门, 岗位名）取，不串。"""
        dept_a, dept_b = _rand("同名部门A"), _rand("同名部门B")
        name = _rand("同名岗位")
        _mk_position(db_session, dept_a, name=name, recruitment_duties="A 部门的职责")
        _mk_position(db_session, dept_b, name=name, recruitment_duties="B 部门的职责")
        await db_session.flush()

        res = await client.post("/api/v1/hr/job-requirements", json={"position_name": name, "department": dept_b})
        assert res.status_code == 201, res.text
        assert res.json()["data"]["duties"] == "B 部门的职责"
