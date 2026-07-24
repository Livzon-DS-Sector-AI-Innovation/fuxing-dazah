"""离职台账 — 业务规则测试。

覆盖离职台账的 CRUD、创建后按姓名+部门匹配员工更新状态等核心规则。
走 service 层（真实 DB 回滚）。
"""

import uuid
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.modules.hr.schemas import DepartureRecordCreate, DepartureRecordUpdate, EmployeeCreate
from app.modules.hr.service import DepartureRecordService, EmployeeService

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


async def _make_departure_record(
    db: AsyncSession,
    *,
    name: str = "离职台账员工",
    department: str = "测试部",
    position: str = "工程师",
    offboarding_type: str = "辞职",
) -> object:
    """经 service 创建一个离职台账记录并返回。"""
    svc = DepartureRecordService(db)
    data = DepartureRecordCreate(
        name=name,
        department=department,
        position=position,
        offboarding_type=offboarding_type,
    )
    return await svc.create_record(data)


# ═══════════════════════════════════════════════════════════════
# 创建
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_departure_record(db_session: AsyncSession):
    """正常创建离职台账记录。"""
    record = await _make_departure_record(db_session, name="台账员工A")
    assert record.id is not None
    assert record.name == "台账员工A"
    assert record.offboarding_type == "辞职"


@pytest.mark.asyncio
async def test_create_departure_record_sets_employee_status(db_session: AsyncSession):
    """已有匹配员工时，创建离职台账后自动将员工状态设为'离职'。"""
    dept_name = _rand("DEPT")
    emp = await _make_employee(db_session, name="匹配员工", department=dept_name, position="操作工")
    assert emp.status == "在职"

    await _make_departure_record(db_session, name="匹配员工", department=dept_name, position="操作工")

    svc = EmployeeService(db_session)
    updated_emp = await svc.get_employee(emp.id)
    assert updated_emp.status == "离职"


@pytest.mark.asyncio
async def test_create_departure_record_no_matching_employee(db_session: AsyncSession):
    """无匹配员工时，创建离职台账不抛异常（仅跳过状态更新）。"""
    record = await _make_departure_record(
        db_session, name="不存在的员工", department="不存在部门", position="无"
    )
    assert record.id is not None


# ═══════════════════════════════════════════════════════════════
# 查询
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_departure_record(db_session: AsyncSession):
    """按 ID 查询离职台账记录。"""
    record = await _make_departure_record(db_session)
    svc = DepartureRecordService(db_session)
    found = await svc.get_record(record.id)
    assert found.id == record.id
    assert found.name == record.name


@pytest.mark.asyncio
async def test_get_departure_record_not_found_raises(db_session: AsyncSession):
    """查询不存在的离职台账记录应抛 NotFoundException。"""
    svc = DepartureRecordService(db_session)
    with pytest.raises(NotFoundException):
        await svc.get_record(uuid.uuid4())


@pytest.mark.asyncio
async def test_list_departure_records(db_session: AsyncSession):
    """列表查询可按部门过滤。"""
    dept_name = _rand("台账部")
    svc = DepartureRecordService(db_session)
    record = await _make_departure_record(db_session, name="列表员工", department=dept_name)

    records, total = await svc.list_records(department=dept_name)
    assert total >= 1
    ids = [r.id for r in records]
    assert record.id in ids


# ═══════════════════════════════════════════════════════════════
# 更新
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_update_departure_record(db_session: AsyncSession):
    """正常更新离职台账的离职类型。"""
    record = await _make_departure_record(db_session, offboarding_type="辞职")
    svc = DepartureRecordService(db_session)
    data = DepartureRecordUpdate(offboarding_type="协商解除")
    updated = await svc.update_record(record.id, data)
    assert updated.offboarding_type == "协商解除"


@pytest.mark.asyncio
async def test_update_nonexistent_departure_record_raises(db_session: AsyncSession):
    """更新不存在的离职台账记录应抛 NotFoundException。"""
    svc = DepartureRecordService(db_session)
    with pytest.raises(NotFoundException):
        await svc.update_record(uuid.uuid4(), DepartureRecordUpdate(offboarding_type="不存在"))


# ═══════════════════════════════════════════════════════════════
# 删除
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_delete_departure_record(db_session: AsyncSession):
    """删除后查询应抛 NotFoundException。"""
    record = await _make_departure_record(db_session)
    svc = DepartureRecordService(db_session)
    await svc.delete_record(record.id)
    with pytest.raises(NotFoundException):
        await svc.get_record(record.id)


@pytest.mark.asyncio
async def test_delete_departure_record_restores_employee_status(db_session: AsyncSession):
    """删除离职台账后，匹配员工的状态应从'离职'恢复为'在职'。"""
    dept = _rand("RESTORE")
    emp = await _make_employee(db_session, name="恢复状态员工", department=dept, position="操作工")
    assert emp.status == "在职"

    record = await _make_departure_record(db_session, name="恢复状态员工", department=dept, position="操作工")

    # 创建离职台账后员工应变为离职
    svc = EmployeeService(db_session)
    updated = await svc.get_employee(emp.id)
    assert updated.status == "离职"

    # 删除离职台账后员工应恢复为在职
    departure_svc = DepartureRecordService(db_session)
    await departure_svc.delete_record(record.id)

    restored = await svc.get_employee(emp.id)
    assert restored.status == "在职"


@pytest.mark.asyncio
async def test_delete_departure_record_restores_onboarding_is_employed(db_session: AsyncSession):
    """删除离职台账后，入职台账的 is_employed 应从'否'恢复为'是'。"""
    from sqlalchemy import select as sel
    from app.modules.hr.models import OnboardingRecord

    dept = _rand("ONBREST")
    emp = await _make_employee(db_session, name="恢复入职员工", department=dept, position="操作工")

    # 获取自动生成的入职记录
    r = await db_session.execute(
        sel(OnboardingRecord).where(
            OnboardingRecord.employee_number == emp.employee_number,
            OnboardingRecord.is_deleted.is_(False),
        )
    )
    onboarding = r.scalar_one()
    assert onboarding.is_employed == "是"

    # 创建离职台账 → is_employed 变为"否"
    record = await _make_departure_record(db_session, name="恢复入职员工", department=dept, position="操作工")
    await db_session.refresh(onboarding)
    assert onboarding.is_employed == "否"

    # 删除离职台账 → is_employed 恢复为"是"
    departure_svc = DepartureRecordService(db_session)
    await departure_svc.delete_record(record.id)
    await db_session.refresh(onboarding)
    assert onboarding.is_employed == "是"


# ═══════════════════════════════════════════════════════════════
# API 层
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_api_get_departure_records(client):
    """GET /api/v1/hr/departure-records 返回 200。"""
    resp = await client.get("/api/v1/hr/departure-records")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body


@pytest.mark.asyncio
async def test_api_create_and_get_departure_record(client):
    """POST 创建离职台账→GET 详情验证。"""
    dept_name = _rand("API台账部")
    resp = await client.post("/api/v1/hr/departure-records", json={
        "name": "API台账员工",
        "department": dept_name,
        "position": "操作工",
    })
    assert resp.status_code == 201
    record_id = resp.json()["data"]["id"]

    resp2 = await client.get(f"/api/v1/hr/departure-records/{record_id}")
    assert resp2.status_code == 200
    assert resp2.json()["data"]["name"] == "API台账员工"


@pytest.mark.asyncio
async def test_api_delete_departure_record(client):
    """DELETE 离职台账后 GET 返回 404。"""
    dept_name = _rand("DEL台账部")
    resp = await client.post("/api/v1/hr/departure-records", json={
        "name": "API待删台账员工",
        "department": dept_name,
        "position": "操作工",
    })
    record_id = resp.json()["data"]["id"]

    await client.delete(f"/api/v1/hr/departure-records/{record_id}")
    resp2 = await client.get(f"/api/v1/hr/departure-records/{record_id}")
    assert resp2.status_code == 404
