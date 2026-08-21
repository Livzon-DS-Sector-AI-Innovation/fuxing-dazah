"""「未分类」人员按实际部门归属的场景开关测试"""

from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def _create_uncategorized_employee(db_session, actual_dept: str) -> str:
    from datetime import date as _date

    from app.modules.hr.models import Employee
    emp_no = f"UC{uuid4().hex[:6].upper()}"
    db_session.add(Employee(
        employee_number=emp_no, name=f"未分类员工{uuid4().hex[:4]}", department="未分类",
        actual_department=actual_dept, position="操作工", status="在职",
        hire_date=_date.today(),
    ))
    await db_session.flush()
    return emp_no


@pytest.mark.asyncio
async def test_profile_include_uncategorized_by_actual_department(db_session, client):
    """员工档案视角：include_uncategorized=true 时，未分类人员按实际部门可见。"""
    emp_no = await _create_uncategorized_employee(db_session, "提炼工程二部")
    res = await client.get("/api/v1/hr/employees", params={
        "department": "提炼工程二部",
        "keyword": "未分类员工",
        "include_uncategorized": "true",
    })
    assert res.status_code == 200, res.text
    numbers = [e["employee_number"] for e in res.json()["data"]]
    assert emp_no in numbers


@pytest.mark.asyncio
async def test_signin_excludes_uncategorized(db_session, client):
    """签到表口径：默认不引入未分类人员（仅体现部门+兼任部门）。"""
    emp_no = await _create_uncategorized_employee(db_session, "提炼工程二部")
    res = await client.get("/api/v1/hr/employees", params={
        "department": "提炼工程二部",
        "keyword": "未分类员工",
    })
    assert res.status_code == 200, res.text
    numbers = [e["employee_number"] for e in res.json()["data"]]
    assert emp_no not in numbers, "签到表人员列表不应包含未分类人员"
