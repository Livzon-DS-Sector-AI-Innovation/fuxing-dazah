"""工伤/劳动纠纷台账（/incidents）：CRUD、类型校验、软删、部门数据范围。"""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.modules.hr.deps import HrAccessContext, get_hr_scope
from app.modules.hr.models import HrIncidentRecord
from tests.modules.hr.conftest import _rand


def _payload(department: str, **overrides) -> dict:
    data = {
        "incident_type": "work_injury",
        "employee_name": "张三",
        "employee_number": _rand("INJ"),
        "department": department,
        "occurred_date": "2026-05-01",
        "description": "测试记录",
        "status": "processing",
        "remark": "",
    }
    data.update(overrides)
    return data


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


async def test_create_and_list_with_filters(db_session: AsyncSession, client: AsyncClient):
    """创建 201；列表支持按类型与发生年份筛选。"""
    dept = _rand("纠纷部")
    r1 = await client.post("/api/v1/hr/incidents", json=_payload(dept))
    assert r1.status_code == 201, r1.text
    incident_id = r1.json()["data"]["id"]

    await client.post("/api/v1/hr/incidents", json=_payload(
        dept, incident_type="labor_dispute", occurred_date="2025-11-02",
    ))
    await db_session.flush()

    res = await client.get("/api/v1/hr/incidents", params={"incident_type": "work_injury"})
    assert res.status_code == 200, res.text
    rows = res.json()["data"]
    got = [r for r in rows if r["id"] == incident_id]
    assert len(got) == 1
    assert got[0]["department"] == dept

    # 年份筛选：2026 只有工伤记录可见，2025 的纠纷记录不在
    res_2026 = await client.get("/api/v1/hr/incidents", params={"year": 2026})
    ids_2026 = {r["id"] for r in res_2026.json()["data"]}
    assert incident_id in ids_2026

    res_2025 = await client.get("/api/v1/hr/incidents", params={"year": 2025})
    ids_2025 = {r["id"] for r in res_2025.json()["data"]}
    assert incident_id not in ids_2025


async def test_create_rejects_unknown_incident_type(client: AsyncClient):
    """incident_type 白名单校验：仅 work_injury / labor_dispute。"""
    res = await client.post(
        "/api/v1/hr/incidents", json=_payload(_rand("X"), incident_type="other"),
    )
    assert res.status_code == 400
    assert "work_injury" in res.json()["message"]


async def test_update_and_soft_delete(db_session: AsyncSession, client: AsyncClient):
    """更新可改状态；删除为软删，列表不再可见；重复操作 404。"""
    dept = _rand("台账部")
    created = await client.post("/api/v1/hr/incidents", json=_payload(dept))
    incident_id = created.json()["data"]["id"]

    upd = await client.put(f"/api/v1/hr/incidents/{incident_id}", json={"status": "closed"})
    assert upd.status_code == 200, upd.text

    # 软删后列表不可见
    dele = await client.delete(f"/api/v1/hr/incidents/{incident_id}")
    assert dele.status_code == 200
    await db_session.flush()
    rows = await client.get("/api/v1/hr/incidents", params={"incident_type": "work_injury"})
    assert incident_id not in {r["id"] for r in rows.json()["data"]}

    # 已删除的记录再更新/再删除 → 404
    assert (await client.put(
        f"/api/v1/hr/incidents/{incident_id}", json={"status": "processing"},
    )).status_code == 404
    assert (await client.delete(f"/api/v1/hr/incidents/{incident_id}")).status_code == 404


async def test_restricted_create_other_department_forbidden(
    client: AsyncClient, test_user,
):
    """受限用户对授权外部门写入 → 403。"""
    app.dependency_overrides[get_hr_scope] = _scoped(test_user, frozenset({"甲部门"}))
    try:
        res = await client.post("/api/v1/hr/incidents", json=_payload("乙部门"))
        assert res.status_code == 403
        # 授权部门内可写
        ok = await client.post("/api/v1/hr/incidents", json=_payload("甲部门"))
        assert ok.status_code == 201
    finally:
        app.dependency_overrides.pop(get_hr_scope, None)


async def test_restricted_list_filters_by_department(
    db_session: AsyncSession, client: AsyncClient, test_user,
):
    """受限列表只返回授权部门记录。"""
    db_session.add(HrIncidentRecord(**_payload("甲部门", occurred_date="2026-06-01")))
    db_session.add(HrIncidentRecord(**_payload("乙部门", occurred_date="2026-06-02")))
    await db_session.flush()

    app.dependency_overrides[get_hr_scope] = _scoped(test_user, frozenset({"甲部门"}))
    try:
        res = await client.get("/api/v1/hr/incidents")
        assert res.status_code == 200, res.text
        departments = {r["department"] for r in res.json()["data"]}
        assert departments == {"甲部门"}
    finally:
        app.dependency_overrides.pop(get_hr_scope, None)
