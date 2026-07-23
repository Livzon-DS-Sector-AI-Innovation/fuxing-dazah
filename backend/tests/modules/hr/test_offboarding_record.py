"""离职记录 — 业务规则测试。

覆盖离职记录的 CRUD、创建后自动更新员工状态等核心规则。
走 service 层（真实 DB 回滚）。
"""

import uuid
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.modules.hr.schemas import EmployeeCreate, OffboardingRecordCreate, OffboardingRecordUpdate
from app.modules.hr.service import EmployeeService, OffboardingRecordService

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
    """经 service 创建一个在职员工并返回。"""
    svc = EmployeeService(db)
    data = EmployeeCreate(
        employee_number=employee_number or _rand("EMP"),
        name=name,
        department=department,
        position=position,
        hire_date=date.today(),
    )
    return await svc.create_employee(data)


async def _make_offboarding_record(
    db: AsyncSession,
    *,
    employee_id: uuid.UUID | None = None,
    offboarding_date: date | None = None,
) -> object:
    """经 service 创建一个离职记录并返回。"""
    if employee_id is None:
        emp = await _make_employee(db)
        employee_id = emp.id
    svc = OffboardingRecordService(db)
    data = OffboardingRecordCreate(
        employee_id=employee_id,
        offboarding_date=offboarding_date or date.today(),
    )
    return await svc.create_record(data)


# ═══════════════════════════════════════════════════════════════
# 创建
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_offboarding_record(db_session: AsyncSession):
    """正常创建离职记录，默认离职类型为'辞职'。"""
    record = await _make_offboarding_record(db_session)
    assert record.id is not None
    assert record.offboarding_type == "辞职"


@pytest.mark.asyncio
async def test_create_offboarding_record_sets_employee_status(db_session: AsyncSession):
    """创建离职记录后，关联员工的在职状态自动更新为'离职'。"""
    emp = await _make_employee(db_session, name="待离职员工")
    assert emp.status == "在职"

    await _make_offboarding_record(db_session, employee_id=emp.id)

    svc = EmployeeService(db_session)
    updated_emp = await svc.get_employee(emp.id)
    assert updated_emp.status == "离职"


@pytest.mark.asyncio
async def test_create_offboarding_record_nonexistent_employee_raises(db_session: AsyncSession):
    """关联不存在的员工应抛 NotFoundException。"""
    svc = OffboardingRecordService(db_session)
    data = OffboardingRecordCreate(
        employee_id=uuid.uuid4(),
        offboarding_date=date.today(),
    )
    with pytest.raises(NotFoundException):
        await svc.create_record(data)


# ═══════════════════════════════════════════════════════════════
# 查询
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_offboarding_record(db_session: AsyncSession):
    """按 ID 查询离职记录。"""
    record = await _make_offboarding_record(db_session)
    svc = OffboardingRecordService(db_session)
    found = await svc.get_record(record.id)
    assert found.id == record.id


@pytest.mark.asyncio
async def test_get_offboarding_record_not_found_raises(db_session: AsyncSession):
    """查询不存在的离职记录应抛 NotFoundException。"""
    svc = OffboardingRecordService(db_session)
    with pytest.raises(NotFoundException):
        await svc.get_record(uuid.uuid4())


@pytest.mark.asyncio
async def test_list_offboarding_records(db_session: AsyncSession):
    """列表查询可找到刚创建的离职记录。"""
    emp = await _make_employee(db_session)
    svc = OffboardingRecordService(db_session)
    record = await _make_offboarding_record(db_session, employee_id=emp.id)

    records, total = await svc.list_records(employee_id=emp.id)
    assert total >= 1
    ids = [r.id for r in records]
    assert record.id in ids


# ═══════════════════════════════════════════════════════════════
# 更新
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_update_offboarding_record(db_session: AsyncSession):
    """正常更新离职记录的离职类型。"""
    record = await _make_offboarding_record(db_session)
    svc = OffboardingRecordService(db_session)
    data = OffboardingRecordUpdate(offboarding_type="协商解除")
    updated = await svc.update_record(record.id, data)
    assert updated.offboarding_type == "协商解除"


@pytest.mark.asyncio
async def test_update_nonexistent_offboarding_record_raises(db_session: AsyncSession):
    """更新不存在的离职记录应抛 NotFoundException。"""
    svc = OffboardingRecordService(db_session)
    with pytest.raises(NotFoundException):
        await svc.update_record(uuid.uuid4(), OffboardingRecordUpdate(reason="不存在"))


# ═══════════════════════════════════════════════════════════════
# 删除
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_delete_offboarding_record(db_session: AsyncSession):
    """删除后查询应抛 NotFoundException。"""
    record = await _make_offboarding_record(db_session)
    svc = OffboardingRecordService(db_session)
    await svc.delete_record(record.id)
    with pytest.raises(NotFoundException):
        await svc.get_record(record.id)


# ═══════════════════════════════════════════════════════════════
# API 层
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_api_get_offboarding_records(client):
    """GET /api/v1/hr/offboarding-records 返回 200。"""
    resp = await client.get("/api/v1/hr/offboarding-records")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body


@pytest.mark.asyncio
async def test_api_create_and_get_offboarding_record(client):
    """POST 创建员工→离职记录，GET 详情验证。"""
    # 先创建员工
    emp_no = _rand("API")
    emp_resp = await client.post("/api/v1/hr/employees", json={
        "employee_number": emp_no,
        "name": "API离职员工",
        "department": "API部",
        "position": "测试",
        "hire_date": str(date.today()),
    })
    assert emp_resp.status_code == 201
    emp_id = emp_resp.json()["data"]["id"]

    # 创建离职记录
    resp = await client.post("/api/v1/hr/offboarding-records", json={
        "employee_id": emp_id,
        "offboarding_date": str(date.today()),
    })
    assert resp.status_code == 201
    record_id = resp.json()["data"]["id"]

    # 查询详情
    resp2 = await client.get(f"/api/v1/hr/offboarding-records/{record_id}")
    assert resp2.status_code == 200


@pytest.mark.asyncio
async def test_api_delete_offboarding_record(client):
    """DELETE 离职记录后 GET 返回 404。"""
    emp_no = _rand("DEL")
    emp_resp = await client.post("/api/v1/hr/employees", json={
        "employee_number": emp_no,
        "name": "API待删离职员工",
        "department": "API部",
        "position": "测试",
        "hire_date": str(date.today()),
    })
    emp_id = emp_resp.json()["data"]["id"]

    resp = await client.post("/api/v1/hr/offboarding-records", json={
        "employee_id": emp_id,
        "offboarding_date": str(date.today()),
    })
    record_id = resp.json()["data"]["id"]

    await client.delete(f"/api/v1/hr/offboarding-records/{record_id}")
    resp2 = await client.get(f"/api/v1/hr/offboarding-records/{record_id}")
    assert resp2.status_code == 404
