"""入职记录 — 业务规则测试。

覆盖入职记录的查询、列表（含 days 自动清理）、删除等核心规则。
入职记录由创建员工时自动生成，本文件测试 OnboardingRecordService 的读/删/列表逻辑。
走 service 层（真实 DB 回滚）。
"""

import uuid
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.modules.hr.schemas import EmployeeCreate
from app.modules.hr.service import EmployeeService, OnboardingRecordService

from tests.modules.hr.conftest import _rand


# ── 辅助函数 ──

async def _make_employee(
    db: AsyncSession,
    *,
    employee_number: str | None = None,
    name: str = "测试员工",
    department: str = "测试部",
    position: str = "工程师",
) -> object:
    """经 service 创建一个员工（会自动创建入职记录）并返回。"""
    svc = EmployeeService(db)
    data = EmployeeCreate(
        employee_number=employee_number or _rand("EMP"),
        name=name,
        department=department,
        position=position,
        hire_date=date.today(),
    )
    return await svc.create_employee(data)


# ═══════════════════════════════════════════════════════════════
# 查询
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_list_onboarding_records(db_session: AsyncSession):
    """创建员工后入职台账列表应有对应记录。"""
    await _make_employee(db_session, name="入职测试员")
    svc = OnboardingRecordService(db_session)
    records, total = await svc.list_records(keyword="入职测试员", days=0)
    assert total >= 1
    names = [r.name for r in records]
    assert "入职测试员" in names


@pytest.mark.asyncio
async def test_list_onboarding_records_by_department(db_session: AsyncSession):
    """按部门过滤入职记录。"""
    dept_name = _rand("DEPART")
    await _make_employee(db_session, name="部门员工", department=dept_name)
    svc = OnboardingRecordService(db_session)
    records, total = await svc.list_records(department=dept_name, days=0)
    assert total >= 1
    for r in records:
        assert r.department == dept_name


@pytest.mark.asyncio
async def test_get_onboarding_record_not_found_raises(db_session: AsyncSession):
    """查询不存在的入职记录应抛 NotFoundException。"""
    svc = OnboardingRecordService(db_session)
    with pytest.raises(NotFoundException):
        await svc.get_record(uuid.uuid4())


# ═══════════════════════════════════════════════════════════════
# 删除
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_delete_onboarding_record(db_session: AsyncSession):
    """删除入职记录后查询应抛 NotFoundException。"""
    emp = await _make_employee(db_session, name="待删入职员工")
    svc = OnboardingRecordService(db_session)
    records, _ = await svc.list_records(keyword="待删入职员工", days=0)
    assert len(records) >= 1
    record_id = records[0].id

    await svc.delete_record(record_id)
    with pytest.raises(NotFoundException):
        await svc.get_record(record_id)


# ═══════════════════════════════════════════════════════════════
# API 层
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_api_get_onboarding_records(client):
    """GET /api/v1/hr/onboarding-records 返回 200。"""
    resp = await client.get("/api/v1/hr/onboarding-records")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body


@pytest.mark.asyncio
async def test_api_delete_onboarding_record(client):
    """创建员工自动生成入职记录，DELETE 后 GET 返回 404。"""
    emp_no = _rand("ONDEL")
    create_resp = await client.post("/api/v1/hr/employees", json={
        "employee_number": emp_no,
        "name": "API入职待删员工",
        "department": "API部",
        "position": "测试",
        "hire_date": str(date.today()),
    })
    assert create_resp.status_code == 201

    # 查询自动生成的入职记录
    list_resp = await client.get("/api/v1/hr/onboarding-records?keyword=API入职待删员工&days=0")
    assert list_resp.status_code == 200
    records = list_resp.json()["data"]
    assert len(records) >= 1
    record_id = records[0]["id"]

    # 删除
    await client.delete(f"/api/v1/hr/onboarding-records/{record_id}")
    get_resp = await client.get(f"/api/v1/hr/onboarding-records/{record_id}")
    assert get_resp.status_code == 404
