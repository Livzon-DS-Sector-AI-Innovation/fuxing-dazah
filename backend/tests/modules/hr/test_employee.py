"""员工管理 — 业务规则测试。

覆盖员工的 CRUD、工号唯一性、部门过滤、花名册等核心规则。
走 service 层（真实 DB 回滚）。
"""

from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateException, NotFoundException
from app.main import app
from app.modules.hr.deps import HrAccessContext, get_hr_scope
from app.modules.hr.models import Employee, TransferRecord
from app.modules.hr.schemas import EmployeeCreate, EmployeeUpdate
from app.modules.hr.service import EmployeeService
from app.platform.identity.models import User
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
    """更新员工信息：身份标识字段（工号/姓名/性别/身份证号）不可改，其余照常。"""
    emp = await _make_employee(db_session, name="原名")
    svc = EmployeeService(db_session)
    # 姓名/工号为受保护字段：更新时被忽略
    data = EmployeeUpdate(name="新名字", employee_number="999999", position="新岗位")
    updated = await svc.update_employee(emp.id, data)
    assert updated.name == "原名"
    assert updated.employee_number == emp.employee_number
    assert updated.position == "新岗位"


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


async def _add_synced_employee(
    db: AsyncSession,
    *,
    name: str,
    department: str = "入职培训测试部",
    hire_date: date | None = None,
    status: str = "在职",
) -> Employee:
    """模拟飞书同步的员工：只有员工档案行，没有入职台账行。"""
    emp = Employee(
        employee_number=_rand("SYNC"),
        name=name,
        department=department,
        position="操作工",
        hire_date=hire_date or date.today(),
        status=status,
    )
    db.add(emp)
    await db.flush()
    return emp


async def _get_candidates(client: AsyncClient, **params: Any) -> dict[str, dict[str, Any]]:
    """查询入职培训下拉候选，返回 {姓名: 候选}。"""
    resp = await client.get("/api/v1/hr/employees/training-candidates", params=params)
    assert resp.status_code == 200, resp.text
    return {c["name"]: c for c in resp.json()["data"]}


async def _add_transfer(
    db: AsyncSession,
    emp: Employee,
    *,
    effective_date: date,
    transfer_type: str = "转岗",
) -> TransferRecord:
    """直接落一条职位变动记录（真实入口 POST /transfers，这里为聚焦判定逻辑走 ORM）。"""
    t = TransferRecord(
        employee_id=emp.id,
        transfer_type=transfer_type,
        from_department=emp.department,
        to_department=emp.department,
        effective_date=effective_date,
    )
    db.add(t)
    await db.flush()
    return t


@pytest.mark.asyncio
async def test_training_candidates_include_synced_employee_without_onboarding_row(
    db_session: AsyncSession, client: AsyncClient,
) -> None:
    """下拉与入职台账列表同源：飞书同步进员工档案、没有入职台账行的员工也能搜到。"""
    name = _rand("同步员工")
    emp = await _add_synced_employee(db_session, name=name)

    found = await _get_candidates(client, keyword=name)
    assert found[name]["employee_number"] == emp.employee_number
    assert found[name]["employee_id"] == str(emp.id)
    assert found[name]["prejob_completed"] is False


@pytest.mark.asyncio
async def test_training_candidates_hide_completed_by_default(
    db_session: AsyncSession, client: AsyncClient,
) -> None:
    """培训台账有入职培训记录表导出记录（prejob_export）的员工默认不返回，
    include_completed=true 时返回并标记已完成；岗前计划导出记录（prejob）不算完成。"""
    name = _rand("已完成员工")
    emp = await _add_synced_employee(db_session, name=name)

    resp = await client.post("/api/v1/hr/training-ledgers", json={
        "employee_number": emp.employee_number,
        "training_date": str(date.today()),
        "training_subject": "岗前安全教育",
        "source_type": "prejob",
    })
    assert resp.status_code == 201, resp.text
    assert name in await _get_candidates(client, keyword=name)

    resp = await client.post("/api/v1/hr/training-ledgers", json={
        "employee_number": emp.employee_number,
        "training_date": str(date.today()),
        "training_subject": "入职培训记录表导出写入",
        "source_type": "prejob_export",
    })
    assert resp.status_code == 201, resp.text

    assert name not in await _get_candidates(client, keyword=name)
    shown = await _get_candidates(client, keyword=name, include_completed="true")
    assert shown[name]["prejob_completed"] is True


async def _add_prejob_export_ledger(client: AsyncClient, number: str, training_date: date) -> None:
    """经培训台账接口写入一条入职培训完成记录（与页面导出写台账同链路）。"""
    resp = await client.post("/api/v1/hr/training-ledgers", json={
        "employee_number": number,
        "training_date": str(training_date),
        "training_subject": f"入职培训记录表导出写入-{training_date}",
        "source_type": "prejob_export",
    })
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_training_candidates_transfer_resets_completion(
    db_session: AsyncSession, client: AsyncClient,
) -> None:
    """转岗/晋升后需重新培训：异动前的完成记录不算数，员工重新进入待培训名单；
    异动生效日期之后重新完成（培训日期 ≥ 生效日）才再次视为完成。"""
    name = _rand("转岗员工")
    emp = await _add_synced_employee(db_session, name=name)
    transfer_day = date.today()

    # 异动前的完成记录（培训日期早于异动生效日）
    await _add_prejob_export_ledger(client, emp.employee_number, date.today() - timedelta(days=30))
    await _add_transfer(db_session, emp, effective_date=transfer_day, transfer_type="转岗")

    found = await _get_candidates(client, keyword=name)
    assert found[name]["prejob_completed"] is False
    assert found[name]["transfers"][0]["transfer_type"] == "转岗"
    assert found[name]["transfers"][0]["effective_date"] == str(transfer_day)

    # 异动后重新完成 → 默认隐藏，include_completed 时标记已完成
    await _add_prejob_export_ledger(client, emp.employee_number, transfer_day)
    assert name not in await _get_candidates(client, keyword=name)
    shown = await _get_candidates(client, keyword=name, include_completed="true")
    assert shown[name]["prejob_completed"] is True


@pytest.mark.asyncio
async def test_training_candidates_maternity_return_triggers_retraining(
    db_session: AsyncSession, client: AsyncClient,
) -> None:
    """产假复岗与晋升/转岗同口径：复岗异动同样重置入职培训完成状态。"""
    name = _rand("产假复岗员工")
    emp = await _add_synced_employee(db_session, name=name)
    await _add_prejob_export_ledger(client, emp.employee_number, date.today() - timedelta(days=60))
    return_day = date.today() - timedelta(days=7)
    await _add_transfer(db_session, emp, effective_date=return_day, transfer_type="产假复岗")

    found = await _get_candidates(client, keyword=name)
    assert found[name]["prejob_completed"] is False
    assert found[name]["transfers"][0]["transfer_type"] == "产假复岗"

    # 复岗后重新完成（培训日期 ≥ 复岗生效日）→ 再次视为完成
    await _add_prejob_export_ledger(client, emp.employee_number, return_day)
    assert name not in await _get_candidates(client, keyword=name)


@pytest.mark.asyncio
async def test_training_candidates_multiple_transfers_use_latest(
    db_session: AsyncSession, client: AsyncClient,
) -> None:
    """多次职位变动取最近一次生效日期判定：完成记录夹在两次异动之间不算完成，
    transfers 按生效日期降序、[0] 是最近一次。"""
    name = _rand("多次异动员工")
    emp = await _add_synced_employee(db_session, name=name)
    today = date.today()
    await _add_transfer(db_session, emp, effective_date=today - timedelta(days=20), transfer_type="调动")
    await _add_transfer(db_session, emp, effective_date=today - timedelta(days=5), transfer_type="晋升")

    # 完成记录晚于第一次异动、早于最近一次 → 仍需重新培训
    await _add_prejob_export_ledger(client, emp.employee_number, today - timedelta(days=10))
    found = await _get_candidates(client, keyword=name)
    assert found[name]["prejob_completed"] is False
    assert [t["transfer_type"] for t in found[name]["transfers"]] == ["晋升", "调动"]

    # 异动当日或之后完成才算完成（≥ 口径）
    await _add_prejob_export_ledger(client, emp.employee_number, today - timedelta(days=5))
    assert name not in await _get_candidates(client, keyword=name)


@pytest.mark.asyncio
async def test_training_candidates_year_matches_transfer_year(
    db_session: AsyncSession, client: AsyncClient,
) -> None:
    """year 命中入职年份或最近异动年份：往年入职、今年异动的员工进默认「当年」视图。"""
    name = _rand("异动年份员工")
    this_year = date.today().year
    emp = await _add_synced_employee(db_session, name=name, hire_date=date(this_year - 3, 6, 1))
    await _add_transfer(db_session, emp, effective_date=date(this_year, 3, 1))

    assert name in await _get_candidates(client, keyword=name, year=this_year)
    assert name in await _get_candidates(client, keyword=name, year=this_year - 3)
    assert name not in await _get_candidates(client, keyword=name, year=this_year - 1)


@pytest.mark.asyncio
async def test_training_candidates_exclude_departed(
    db_session: AsyncSession, client: AsyncClient,
) -> None:
    """与入职台账列表同口径：状态为「离职」的员工不在下拉候选中。"""
    name = _rand("离职员工")
    await _add_synced_employee(db_session, name=name, status="离职")

    assert name not in await _get_candidates(client, keyword=name)


@pytest.mark.asyncio
async def test_training_candidates_filter_by_year(
    db_session: AsyncSession, client: AsyncClient,
) -> None:
    """year 按入职日期所在年份筛选（与入职台账列表一致）；不传则不限年份。"""
    name = _rand("往年员工")
    this_year = date.today().year
    await _add_synced_employee(db_session, name=name, hire_date=date(this_year - 1, 6, 1))

    assert name not in await _get_candidates(client, keyword=name, year=this_year)
    assert name in await _get_candidates(client, keyword=name, year=this_year - 1)
    assert name in await _get_candidates(client, keyword=name)


@pytest.mark.asyncio
async def test_training_candidates_restricted_to_scoped_departments(
    db_session: AsyncSession, client: AsyncClient, test_user: User,
) -> None:
    """数据范围受限时只返回授权部门的员工。"""
    dept_a, dept_b = _rand("授权部"), _rand("外部部")
    emp_a = await _add_synced_employee(
        db_session, name=_rand("授权员工"), department=dept_a,
    )
    emp_b = await _add_synced_employee(
        db_session, name=_rand("外部员工"), department=dept_b,
    )

    async def _scoped() -> HrAccessContext:
        return HrAccessContext(
            user=test_user,
            data_scope="department",
            department=dept_a,
            employee_number=test_user.employee_no,
            scoped_departments=frozenset({dept_a}),
        )

    app.dependency_overrides[get_hr_scope] = _scoped
    try:
        resp = await client.get("/api/v1/hr/employees/training-candidates")
    finally:
        app.dependency_overrides.pop(get_hr_scope, None)
    assert resp.status_code == 200, resp.text
    numbers = {c["employee_number"] for c in resp.json()["data"]}
    assert emp_a.employee_number in numbers
    assert emp_b.employee_number not in numbers


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


@pytest.mark.asyncio
async def test_training_positions_by_department_merges_linked_table_and_catalog(
    db_session: AsyncSession, client: AsyncClient,
) -> None:
    """部门下的培训岗位取「岗位培训关联表 ∪ SOP 目录」：历史数据可能只落在其中一张表。

    同一大类两表都有时只出一次，培训师 / 培训方式以关联表为准；
    SOP 目录未填适用岗位的条目、别的部门的条目都不算本部门的培训岗位。
    """
    from app.modules.hr.models import PositionTraining, SopCatalog

    dept = _rand("培训岗")
    db_session.add_all([
        PositionTraining(department=dept, position_name="工艺员", training_category="工艺操作",
                         trainer="张三", training_method="面授", sop_number="S-1", file_name="粗提岗位操作规程"),
        PositionTraining(department=dept, position_name="工艺员", training_category="质量管理",
                         sop_number="S-2", file_name="偏差处理管理规程"),
        SopCatalog(department=dept, position_name="工艺员", category="工艺操作",
                   sop_number="S-1", file_name="粗提岗位操作规程"),
        SopCatalog(department=dept, position_name="工艺员", category="设备操作",
                   sop_number="S-3", file_name="离心机操作规程"),
        SopCatalog(department=dept, position_name="班组长", category="安全管理",
                   sop_number="S-4", file_name="受限空间作业安全操作规程"),
        SopCatalog(department=dept, position_name=None, category="文件管理",
                   sop_number="S-5", file_name="文件管理规程"),
        SopCatalog(department=_rand("别的部门"), position_name="检验员", category="质量管理",
                   sop_number="S-6", file_name="偏差处理管理规程"),
    ])
    await db_session.flush()

    resp = await client.get(
        "/api/v1/hr/position-trainings/by-department", params={"department": dept},
    )
    assert resp.status_code == 200, resp.text
    positions = {p["position_name"]: p["categories"] for p in resp.json()["data"]}
    assert set(positions) == {"工艺员", "班组长"}

    gongyi = {c["training_category"]: c for c in positions["工艺员"]}
    assert set(gongyi) == {"工艺操作", "质量管理", "设备操作"}
    # 关联表带培训师 / 培训方式；只在 SOP 目录里的大类没有
    assert gongyi["工艺操作"] == {
        "training_category": "工艺操作", "trainer": "张三", "training_method": "面授",
    }
    assert gongyi["设备操作"] == {
        "training_category": "设备操作", "trainer": None, "training_method": None,
    }
    assert [c["training_category"] for c in positions["班组长"]] == ["安全管理"]


@pytest.mark.asyncio
async def test_training_positions_by_department_empty_and_required(
    client: AsyncClient,
) -> None:
    """没配置过培训内容的部门返回空列表；department 为必填参数。"""
    resp = await client.get(
        "/api/v1/hr/position-trainings/by-department", params={"department": _rand("空部门")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == []

    missing = await client.get("/api/v1/hr/position-trainings/by-department")
    assert missing.status_code == 422


# ═══════════════════════════════════════════════════════════════
# 字段级筛选 + 筛选选项（档案筛选面板）
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_api_list_employees_field_filters(client):
    """字段级筛选：下拉精确匹配 + 入职日期范围 + 年龄区间。"""
    number = _rand("FLT")
    resp = await client.post("/api/v1/hr/employees", json={
        "employee_number": number,
        "name": "筛选测试员",
        "department": "筛选部",
        "position": "质检员",
        "education": "本科",
        "gender": "女",
        "birth_year": 1990,
        "hire_date": "2024-06-15",
    })
    assert resp.status_code == 201

    # 下拉精确匹配：以工号关键词锚定，命中本人
    resp = await client.get("/api/v1/hr/employees", params={
        "keyword": number, "position": "质检员", "education": "本科", "gender": "女",
    })
    assert resp.json()["meta"]["total"] == 1

    # 岗位为精确匹配：传前缀「质检」不应命中「质检员」
    resp = await client.get("/api/v1/hr/employees", params={
        "keyword": number, "position": "质检",
    })
    assert resp.json()["meta"]["total"] == 0

    # 入职日期范围：起止均含边界日内命中
    resp = await client.get("/api/v1/hr/employees", params={
        "keyword": number,
        "hire_date_after": "2024-06-01", "hire_date_before": "2024-06-30",
    })
    assert resp.json()["meta"]["total"] == 1
    resp = await client.get("/api/v1/hr/employees", params={
        "keyword": number, "hire_date_after": "2024-07-01",
    })
    assert resp.json()["meta"]["total"] == 0

    # 年龄区间换算出生年份：1990 年生 → 今年满 (今年-1990) 岁
    age = date.today().year - 1990
    resp = await client.get("/api/v1/hr/employees", params={
        "keyword": number, "age_min": age, "age_max": age,
    })
    assert resp.json()["meta"]["total"] == 1
    resp = await client.get("/api/v1/hr/employees", params={
        "keyword": number, "age_min": age + 5,
    })
    assert resp.json()["meta"]["total"] == 0

    # 出生年份区间
    resp = await client.get("/api/v1/hr/employees", params={
        "keyword": number, "birth_year_min": 1990, "birth_year_max": 1990,
    })
    assert resp.json()["meta"]["total"] == 1


@pytest.mark.asyncio
async def test_api_employee_filter_options(client):
    """filter-options 聚合现有取值：新员工的字段值出现在对应选项中。"""
    resp = await client.post("/api/v1/hr/employees", json={
        "employee_number": _rand("OPT"),
        "name": "选项测试员",
        "department": "选项部",
        "position": "选项岗位XYZ",
        "education": "硕士XYZ",
        "duty": "选项职务XYZ",
        "hire_date": str(date.today()),
    })
    assert resp.status_code == 201

    resp2 = await client.get("/api/v1/hr/employees/filter-options")
    assert resp2.status_code == 200
    options = resp2.json()["data"]
    assert "选项岗位XYZ" in options["position"]
    assert "硕士XYZ" in options["education"]
    assert "选项职务XYZ" in options["duty"]
    # 空值不入选项
    assert "" not in options["position"]
