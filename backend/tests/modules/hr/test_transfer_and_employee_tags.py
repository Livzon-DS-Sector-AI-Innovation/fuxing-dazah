"""员工异动记录（/transfers）与员工自定义标签（/employee-tags）。"""

from datetime import date
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.modules.hr.deps import HrAccessContext, get_hr_scope
from app.modules.hr.models import Employee
from tests.modules.hr.conftest import _rand


def _mk_employee(department: str) -> Employee:
    return Employee(
        employee_number=_rand("TRF"),
        name="异动员工",
        department=department,
        position="操作工",
        hire_date=date(2020, 1, 1),
    )


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


# ─── 员工异动 ───


async def test_create_and_list_transfers(db_session: AsyncSession, client: AsyncClient):
    """创建异动 201；按员工分页查询按生效日期倒序。"""
    emp = _mk_employee(_rand("异动部"))
    db_session.add(emp)
    await db_session.flush()

    payload = {
        "employee_id": str(emp.id),
        "transfer_type": "调动",
        "from_department": "原部门",
        "to_department": "新部门",
        "from_position": "操作工",
        "to_position": "班组长",
        "effective_date": "2026-06-01",
        "reason": "生产需要",
    }
    created = await client.post("/api/v1/hr/transfers", json=payload)
    assert created.status_code == 201, created.text
    transfer_id = created.json()["data"]["id"]

    res = await client.get("/api/v1/hr/transfers", params={"employee_id": str(emp.id)})
    assert res.status_code == 200, res.text
    rows = res.json()["data"]
    assert len(rows) == 1
    assert rows[0]["id"] == transfer_id
    assert rows[0]["to_department"] == "新部门"
    assert rows[0]["effective_date"] == "2026-06-01"


async def test_transfer_requires_employee_id_query(client: AsyncClient):
    """employee_id 为必填查询参数。"""
    res = await client.get("/api/v1/hr/transfers")
    assert res.status_code == 422


async def test_restricted_transfer_access(db_session: AsyncSession, client: AsyncClient, test_user):
    """受限用户：为授权外员工创建/查询异动 → 403；授权内员工 → 正常。"""
    in_scope = _mk_employee("甲部门")
    out_scope = _mk_employee("乙部门")
    db_session.add_all([in_scope, out_scope])
    await db_session.flush()

    app.dependency_overrides[get_hr_scope] = _scoped(test_user, frozenset({"甲部门"}))
    try:
        payload = {
            "employee_id": str(out_scope.id), "transfer_type": "调动",
            "effective_date": "2026-06-01",
        }
        assert (await client.post("/api/v1/hr/transfers", json=payload)).status_code == 403
        assert (await client.get(
            "/api/v1/hr/transfers", params={"employee_id": str(out_scope.id)},
        )).status_code == 403

        ok = await client.post("/api/v1/hr/transfers", json={
            "employee_id": str(in_scope.id), "transfer_type": "晋升",
            "effective_date": "2026-06-01",
        })
        assert ok.status_code == 201
    finally:
        app.dependency_overrides.pop(get_hr_scope, None)


# ─── 员工标签 ───


async def test_tag_add_list_remove_flow(client: AsyncClient):
    """打标 → 列表计数 → 按员工查询 → 移除后不可见；重复打标幂等。"""
    emp_no = _rand("TAG")
    tag = _rand("标签")

    r1 = await client.post("/api/v1/hr/employee-tags", json={
        "employee_number": emp_no, "tag_name": tag,
    })
    assert r1.status_code == 200, r1.text

    # 重复打标幂等（ON CONFLICT DO NOTHING，不 500）
    r2 = await client.post("/api/v1/hr/employee-tags", json={
        "employee_number": emp_no, "tag_name": tag,
    })
    assert r2.status_code == 200

    lst = await client.get("/api/v1/hr/employee-tags")
    mine = [t for t in lst.json()["data"] if t["tag_name"] == tag]
    assert len(mine) == 1
    assert mine[0]["count"] == 1  # 重复打标只算一个活跃行

    by_emp = await client.get(
        "/api/v1/hr/employee-tags/by-employee", params={"employee_number": emp_no},
    )
    assert by_emp.status_code == 200
    assert [t["tag_name"] for t in by_emp.json()["data"]] == [tag]

    removed = await client.post("/api/v1/hr/employee-tags", json={
        "employee_number": emp_no, "tag_name": tag, "action": "remove",
    })
    assert removed.status_code == 200
    after = await client.get(
        "/api/v1/hr/employee-tags/by-employee", params={"employee_number": emp_no},
    )
    assert after.json()["data"] == []


async def test_tag_requires_number_and_name(client: AsyncClient):
    """工号/标签名缺失 → 400。"""
    res = await client.post("/api/v1/hr/employee-tags", json={"tag_name": "x"})
    assert res.status_code == 400


async def test_tag_scoped_to_creator(db_session: AsyncSession, client: AsyncClient, test_user):
    """标签列表按创建人隔离：直接落库他人创建的标签不出现在列表里。"""
    from app.modules.hr.models import EmployeeTag

    other_tag = _rand("他人标签")
    db_session.add(EmployeeTag(
        employee_number=_rand("EMP"), tag_name=other_tag, created_by="别人",
    ))
    await db_session.flush()

    lst = await client.get("/api/v1/hr/employee-tags")
    assert other_tag not in {t["tag_name"] for t in lst.json()["data"]}


async def test_restricted_tag_on_employee_out_of_scope(
    db_session: AsyncSession, client: AsyncClient, test_user,
):
    """受限用户给授权外员工打标/查标签 → 403。"""
    emp = _mk_employee("乙部门")
    db_session.add(emp)
    await db_session.flush()

    app.dependency_overrides[get_hr_scope] = _scoped(test_user, frozenset({"甲部门"}))
    try:
        r1 = await client.post("/api/v1/hr/employee-tags", json={
            "employee_number": emp.employee_number, "tag_name": _rand("标签"),
        })
        # 打标走培训名单范围校验：不在名单/不在授权部门 → 403
        assert r1.status_code == 403

        r2 = await client.get(
            "/api/v1/hr/employee-tags/by-employee",
            params={"employee_number": emp.employee_number},
        )
        # 查询走员工档案范围校验（ensure_can_access_employee）
        assert r2.status_code == 403
    finally:
        app.dependency_overrides.pop(get_hr_scope, None)


async def test_transfer_unknown_employee_still_records(db_session: AsyncSession, client: AsyncClient):
    """员工不存在时异动记录仍可创建（历史员工补录场景，仅在有员工时校验范围）。"""
    res = await client.post("/api/v1/hr/transfers", json={
        "employee_id": str(uuid4()), "transfer_type": "调动", "effective_date": "2026-06-01",
    })
    assert res.status_code == 201
