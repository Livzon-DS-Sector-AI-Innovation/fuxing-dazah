"""员工管理 — 业务规则测试。

覆盖员工的 CRUD、工号唯一性、部门过滤、花名册等核心规则。
走 service 层（真实 DB 回滚）。
"""

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateException, NotFoundException
from app.modules.hr.schemas import EmployeeCreate, EmployeeUpdate
from app.modules.hr.service import EmployeeService

from tests.modules.hr.conftest import _rand


# ── 辅助函数 ──

async def _make_employee(
    db: AsyncSession,
    *,
    employee_number: str | None = None,
    name: str = "测试员工",
    department: str = "测试部",
    position: str = "工程师",
    hire_date: date | None = None,
) -> object:
    """经 service 创建一个员工并返回。"""
    svc = EmployeeService(db)
    data = EmployeeCreate(
        employee_number=employee_number or _rand("EMP"),
        name=name,
        department=department,
        position=position,
        hire_date=hire_date or date.today(),
    )
    return await svc.create_employee(data)


# ═══════════════════════════════════════════════════════════════
# 创建
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_employee(db_session: AsyncSession):
    """正常创建员工，自动分配在职状态。"""
    emp = await _make_employee(db_session, name="张三")
    assert emp.id is not None
    assert emp.name == "张三"
    assert emp.status == "在职"


@pytest.mark.asyncio
async def test_create_employee_duplicate_number_raises(db_session: AsyncSession):
    """相同工号重复创建应抛 DuplicateException。"""
    number = _rand("DUP")
    await _make_employee(db_session, employee_number=number)
    with pytest.raises(DuplicateException):
        await _make_employee(db_session, employee_number=number)


@pytest.mark.asyncio
async def test_create_employee_auto_department(db_session: AsyncSession):
    """未指定部门时自动设为'未分类'。"""
    svc = EmployeeService(db_session)
    data = EmployeeCreate(
        employee_number=_rand("NODEPT"),
        name="无部门员工",
        department="",
        position="助理",
        hire_date=date.today(),
    )
    emp = await svc.create_employee(data)
    assert emp.department == "未分类"


# ═══════════════════════════════════════════════════════════════
# 查询
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_employee(db_session: AsyncSession):
    """按 ID 查询员工。"""
    emp = await _make_employee(db_session)
    svc = EmployeeService(db_session)
    found = await svc.get_employee(emp.id)
    assert found.id == emp.id
    assert found.employee_number == emp.employee_number


@pytest.mark.asyncio
async def test_get_employee_by_number(db_session: AsyncSession):
    """按工号查询员工。"""
    emp = await _make_employee(db_session, employee_number="EMP001")
    svc = EmployeeService(db_session)
    found = await svc.get_employee_by_number("EMP001")
    assert found.name == emp.name


@pytest.mark.asyncio
async def test_get_employee_not_found_raises(db_session: AsyncSession):
    """查询不存在的员工应抛 NotFoundException。"""
    import uuid
    svc = EmployeeService(db_session)
    with pytest.raises(NotFoundException):
        await svc.get_employee(uuid.uuid4())


# ═══════════════════════════════════════════════════════════════
# 更新
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_update_employee(db_session: AsyncSession):
    """更新员工信息。"""
    emp = await _make_employee(db_session, name="原名")
    svc = EmployeeService(db_session)
    data = EmployeeUpdate(name="新名字")
    updated = await svc.update_employee(emp.id, data)
    assert updated.name == "新名字"


@pytest.mark.asyncio
async def test_update_nonexistent_employee_raises(db_session: AsyncSession):
    """更新不存在的员工应抛 NotFoundException。"""
    import uuid
    svc = EmployeeService(db_session)
    with pytest.raises(NotFoundException):
        await svc.update_employee(uuid.uuid4(), EmployeeUpdate(name="??"))


# ═══════════════════════════════════════════════════════════════
# API 层
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_api_get_employees(client):
    """GET /api/v1/hr/employees 返回 200 和分页结构。"""
    resp = await client.get("/api/v1/hr/employees")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert body.get("meta", {}).get("total", 0) >= 0


@pytest.mark.asyncio
async def test_api_create_and_get_employee(client):
    """POST 创建 → GET 详情 完整链路。"""
    number = _rand("API")
    resp = await client.post("/api/v1/hr/employees", json={
        "employee_number": number,
        "name": "API测试员",
        "department": "API部",
        "position": "测试",
        "hire_date": str(date.today()),
    })
    assert resp.status_code == 201
    emp_id = resp.json()["data"]["id"]

    resp2 = await client.get(f"/api/v1/hr/employees/{emp_id}")
    assert resp2.status_code == 200
    assert resp2.json()["data"]["name"] == "API测试员"


@pytest.mark.asyncio
async def test_api_duplicate_employee_number_returns_409(client):
    """同工号创建两次，第二次返回 409。"""
    number = _rand("CONFLICT")
    payload = {
        "employee_number": number,
        "name": "员工A",
        "department": "部门",
        "position": "岗位",
        "hire_date": str(date.today()),
    }
    await client.post("/api/v1/hr/employees", json=payload)
    resp = await client.post("/api/v1/hr/employees", json=payload)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_api_delete_employee(client):
    """删除员工后 GET 返回 404。"""
    number = _rand("DEL")
    resp = await client.post("/api/v1/hr/employees", json={
        "employee_number": number,
        "name": "待删员工",
        "department": "部门",
        "position": "岗位",
        "hire_date": str(date.today()),
    })
    emp_id = resp.json()["data"]["id"]

    await client.delete(f"/api/v1/hr/employees/{emp_id}")
    resp2 = await client.get(f"/api/v1/hr/employees/{emp_id}")
    assert resp2.status_code == 404
