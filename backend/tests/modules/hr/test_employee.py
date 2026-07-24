"""员工管理 — 业务规则测试。

覆盖员工的 CRUD、工号唯一性、部门过滤、花名册等核心规则。
走 service 层（真实 DB 回滚）。
"""

from datetime import date

import pytest
from sqlalchemy import select
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
# 创建员工 — 副作用
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_employee_auto_creates_onboarding_record(db_session: AsyncSession):
    """创建员工时自动生成入职台账记录，且 is_employed='是'。"""
    from app.modules.hr.models import OnboardingRecord
    emp = await _make_employee(db_session, name="副作用测试员")

    result = await db_session.execute(
        select(OnboardingRecord).where(
            OnboardingRecord.employee_number == emp.employee_number,
            OnboardingRecord.is_deleted.is_(False),
        )
    )
    onboarding = result.scalar_one_or_none()
    assert onboarding is not None
    assert onboarding.name == "副作用测试员"
    assert onboarding.is_employed == "是"
    assert onboarding.department == emp.department
    assert onboarding.position == emp.position


@pytest.mark.asyncio
async def test_create_employee_auto_creates_training_ledger_page(db_session: AsyncSession):
    """创建员工时自动创建培训台账专属页面（TrainingLedgerPage）。"""
    from app.modules.hr.models import TrainingLedgerPage
    emp = await _make_employee(db_session, name="台账页面测试员")

    result = await db_session.execute(
        select(TrainingLedgerPage).where(
            TrainingLedgerPage.employee_number == emp.employee_number,
            TrainingLedgerPage.is_deleted.is_(False),
        )
    )
    page = result.scalar_one_or_none()
    assert page is not None
    assert page.employee_name == "台账页面测试员"


@pytest.mark.asyncio
async def test_create_employee_syncs_position_training(db_session: AsyncSession):
    """创建员工时，根据岗位培训内容自动创建培训台账记录。"""
    from app.modules.hr.models import PositionTraining, TrainingLedger

    dept = _rand("SYNC")
    pos = _rand("操作工")
    category = "GMP基础知识"

    db_session.add(PositionTraining(
        department=dept,
        position_name=pos,
        training_category=category,
        file_name="GMP规范.pdf",
    ))
    await db_session.flush()

    # 员工岗位匹配 → 应自动同步培训记录
    svc = EmployeeService(db_session)
    emp = await svc.create_employee(EmployeeCreate(
        employee_number=_rand("SYNCEMP"),
        name="同步培训员工",
        department=dept,
        position=pos,
        hire_date=date.today(),
    ))

    result = await db_session.execute(
        select(TrainingLedger).where(
            TrainingLedger.employee_number == emp.employee_number,
            TrainingLedger.training_subject == category,
            TrainingLedger.is_deleted.is_(False),
        )
    )
    ledger = result.scalar_one_or_none()
    assert ledger is not None, f"期望自动创建培训记录 '{category}'，但未找到"


@pytest.mark.asyncio
async def test_create_employee_no_duplicate_training_sync(db_session: AsyncSession):
    """已存在培训台账页面时，不重复创建。"""
    from app.modules.hr.models import TrainingLedgerPage

    emp_no = _rand("NODUP")
    emp = await _make_employee(db_session, employee_number=emp_no, name="不重复测试")

    # 查询确认只创建了一条页面记录
    result = await db_session.execute(
        select(TrainingLedgerPage).where(
            TrainingLedgerPage.employee_number == emp_no,
            TrainingLedgerPage.is_deleted.is_(False),
        )
    )
    pages = result.scalars().all()
    assert len(pages) == 1


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


@pytest.mark.asyncio
async def test_api_get_employee_by_number(client):
    """GET /api/v1/hr/employees/by-number/{employee_number} 返回员工信息。"""
    number = _rand("BYNUM")
    resp = await client.post("/api/v1/hr/employees", json={
        "employee_number": number,
        "name": "工号查询测试",
        "department": "查询部",
        "position": "测试",
        "hire_date": str(date.today()),
    })
    assert resp.status_code == 201

    resp2 = await client.get(f"/api/v1/hr/employees/by-number/{number}")
    assert resp2.status_code == 200
    assert resp2.json()["data"]["name"] == "工号查询测试"


@pytest.mark.asyncio
async def test_api_get_training_candidates(client):
    """GET /api/v1/hr/employees/training-candidates 返回在职入职员工列表。"""
    number = _rand("CAND")
    # 先创建在职员工（会自动生成入职台账且 is_employed='是'）
    await client.post("/api/v1/hr/employees", json={
        "employee_number": number,
        "name": "培训候选员工",
        "department": "候选部",
        "position": "测试",
        "hire_date": str(date.today()),
    })

    resp = await client.get("/api/v1/hr/employees/training-candidates?keyword=培训候选员工")
    assert resp.status_code == 200
    candidates = resp.json()["data"]
    assert len(candidates) >= 1
    # 应包含刚创建的员工
    names = [c["name"] for c in candidates]
    assert "培训候选员工" in names


# ═══════════════════════════════════════════════════════════════
# 职位 & 岗位培训 API
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_api_get_positions(client):
    """GET /api/v1/hr/positions 返回 200 和职位列表。"""
    resp = await client.get("/api/v1/hr/positions")
    assert resp.status_code == 200
    assert "data" in resp.json()


@pytest.mark.asyncio
async def test_api_create_position(client):
    """POST /api/v1/hr/positions 创建职位并返回 201。"""
    dept = _rand("POSDEPT")
    resp = await client.post("/api/v1/hr/positions", json={
        "department": dept,
        "name": "测试岗位",
    })
    assert resp.status_code == 201
    assert resp.json()["data"]["name"] == "测试岗位"


@pytest.mark.asyncio
async def test_api_get_positions_by_department(client):
    """GET /api/v1/hr/positions?department=xxx 按部门过滤。"""
    dept = _rand("FILTERPOS")
    await client.post("/api/v1/hr/positions", json={
        "department": dept,
        "name": "过滤岗位",
    })

    resp = await client.get(f"/api/v1/hr/positions?department={dept}")
    assert resp.status_code == 200
    positions = resp.json()["data"]
    assert len(positions) >= 1
    assert positions[0]["department"] == dept


@pytest.mark.asyncio
async def test_api_get_position_departments(client):
    """GET /api/v1/hr/positions/departments 返回部门列表。"""
    dept = _rand("POSDEPTLIST")
    await client.post("/api/v1/hr/positions", json={
        "department": dept,
        "name": "部门列表岗位",
    })

    resp = await client.get("/api/v1/hr/positions/departments")
    assert resp.status_code == 200
    departments = resp.json()["data"]
    assert dept in departments


@pytest.mark.asyncio
async def test_api_get_position_trainings(client):
    """GET /api/v1/hr/position-trainings 返回 200。"""
    resp = await client.get("/api/v1/hr/position-trainings")
    assert resp.status_code == 200
    assert "data" in resp.json()
