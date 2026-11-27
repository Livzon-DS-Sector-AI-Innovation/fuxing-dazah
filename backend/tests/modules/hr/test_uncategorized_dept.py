"""「未分类」人员的部门筛选口径（新数据源无实际部门回落）。"""

from datetime import date as _date
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def _create_uncategorized_employee(db_session) -> str:
    from app.modules.hr.models import Employee
    emp_no = f"UC{uuid4().hex[:6].upper()}"
    db_session.add(Employee(
        employee_number=emp_no, name=f"未分类员工{uuid4().hex[:4]}", department="未分类",
        position="操作工", status="在职",
        hire_date=_date.today(),
    ))
    await db_session.flush()
    return emp_no


@pytest.mark.asyncio
async def test_profile_uncategorized_not_in_other_departments(db_session, client):
    """员工档案视角：未分类人员只属于「未分类」，不因 include_uncategorized 并入其他部门。"""
    emp_no = await _create_uncategorized_employee(db_session)
    res = await client.get("/api/v1/hr/employees", params={
        "department": "提炼工程二部",
        "keyword": "未分类员工",
        "include_uncategorized": "true",
    })
    assert res.status_code == 200, res.text
    numbers = [e["employee_number"] for e in res.json()["data"]]
    assert emp_no not in numbers

    # 显式筛选「未分类」部门时可见
    res2 = await client.get("/api/v1/hr/employees", params={
        "department": "未分类",
        "keyword": "未分类员工",
    })
    assert res2.status_code == 200, res2.text
    numbers2 = [e["employee_number"] for e in res2.json()["data"]]
    assert emp_no in numbers2


@pytest.mark.asyncio
async def test_signin_excludes_uncategorized(db_session, client):
    """签到表口径：默认不引入未分类人员（仅体现部门）。"""
    emp_no = await _create_uncategorized_employee(db_session)
    res = await client.get("/api/v1/hr/employees", params={
        "department": "提炼工程二部",
        "keyword": "未分类员工",
    })
    assert res.status_code == 200, res.text
    numbers = [e["employee_number"] for e in res.json()["data"]]
    assert emp_no not in numbers, "签到表人员列表不应包含未分类人员"


@pytest.mark.asyncio
async def test_employee_list_default_includes_all_statuses(db_session, client):
    """默认列表与源表全量对齐：不传 status 时试用期/离职/产假人员都可见。

    回归：API 层 Query 默认值曾为「在职」（repository 已不过滤但被默认值
    覆盖），导致同步 1285 人而列表只剩在职口径。
    """
    from app.modules.hr.models import Employee

    tag = uuid4().hex[:6].upper()
    rows = [
        Employee(employee_number=f"TS{tag}1", name=f"口径测试试用期{tag}", department="质控部",
                 position="QC", status="试用期", hire_date=_date.today()),
        Employee(employee_number=f"TS{tag}2", name=f"口径测试离职{tag}", department="质控部",
                 position="QC", status="离职", hire_date=_date.today()),
        Employee(employee_number=f"TS{tag}3", name=f"口径测试产假{tag}", department="质控部",
                 position="QC", status="产假", hire_date=_date.today()),
    ]
    db_session.add_all(rows)
    await db_session.flush()

    res = await client.get("/api/v1/hr/employees", params={"keyword": f"口径测试"})
    assert res.status_code == 200, res.text
    numbers = {e["employee_number"]: e["status"] for e in res.json()["data"]}
    assert numbers.get(f"TS{tag}1") == "试用期"
    assert numbers.get(f"TS{tag}2") == "离职"
    assert numbers.get(f"TS{tag}3") == "产假"


@pytest.mark.asyncio
async def test_uncategorized_only_returns_unmatched_employees(db_session, client):
    """「未归类」版面：只返回部门为空、或部门名不在部门表中的人员。

    回归：档案页的合成页签此前传 include_uncategorized（仓储层从未实现），
    实际查询与「全部」页签完全相同；而部门表里另有一个真实存在、名为「未分类」的部门。
    """
    from app.modules.hr.models import Employee, HrDepartment

    tag = uuid4().hex[:6].upper()
    db_session.add(HrDepartment(name=f"未归类测试部门{tag}", code=f"UO{tag}"))
    rows = [
        # 部门在部门表中 → 已归类
        Employee(employee_number=f"UO{tag}1", name=f"未归类测试在册{tag}", department=f"未归类测试部门{tag}",
                 position="HR", status="在职", hire_date=_date.today()),
        # 部门名不在部门表中 → 未归类
        Employee(employee_number=f"UO{tag}2", name=f"未归类测试无匹配{tag}", department=f"不存在的部门{tag}",
                 position="操作工", status="在职", hire_date=_date.today()),
        # 部门为空 → 未归类
        Employee(employee_number=f"UO{tag}3", name=f"未归类测试空部门{tag}", department="",
                 position="操作工", status="在职", hire_date=_date.today()),
    ]
    db_session.add_all(rows)
    await db_session.flush()

    res = await client.get("/api/v1/hr/employees", params={
        "keyword": "未归类测试", "page_size": 100, "uncategorized_only": "true",
    })
    assert res.status_code == 200, res.text
    numbers = {e["employee_number"] for e in res.json()["data"]}
    assert numbers == {f"UO{tag}2", f"UO{tag}3"}

    # 不带该参数时三人都在：默认口径不受影响
    res2 = await client.get("/api/v1/hr/employees", params={
        "keyword": "未归类测试", "page_size": 100,
    })
    assert res2.status_code == 200, res2.text
    numbers2 = {e["employee_number"] for e in res2.json()["data"]}
    assert numbers2 == {f"UO{tag}1", f"UO{tag}2", f"UO{tag}3"}
