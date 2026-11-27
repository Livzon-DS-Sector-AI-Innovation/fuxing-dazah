"""入职记录 — 业务规则测试。

覆盖入职台账列表视图（数据源=员工档案，按入职年份自动归类）、
年份聚合、台账记录删除等核心规则。
员工由创建/飞书同步进入员工档案后自动出现在台账视图，无需手动登记。
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
    hire_date: date | None = None,
) -> object:
    """经 service 创建一个员工（会自动创建入职记录）并返回。"""
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
# 台账列表视图（数据源=员工档案）
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_list_onboarding_records(db_session: AsyncSession):
    """员工档案里的员工自动出现在台账视图，往年入职也在全量列表。"""
    await _make_employee(db_session, name="入职测试员", hire_date=date.today().replace(year=date.today().year - 1))
    svc = OnboardingRecordService(db_session)
    records, total = await svc.list_records(keyword="入职测试员")
    assert total >= 1
    names = [r.name for r in records]
    assert "入职测试员" in names


@pytest.mark.asyncio
async def test_list_onboarding_records_by_department(db_session: AsyncSession):
    """按部门过滤台账视图。"""
    dept_name = _rand("DEPART")
    await _make_employee(db_session, name="部门员工", department=dept_name)
    svc = OnboardingRecordService(db_session)
    records, total = await svc.list_records(department=dept_name)
    assert total >= 1
    for r in records:
        assert r.department == dept_name


@pytest.mark.asyncio
async def test_list_onboarding_records_by_year(db_session: AsyncSession):
    """按入职年份归类：年份过滤命中当年入职、排除往年入职。"""
    this_year = date.today().year
    await _make_employee(db_session, name="当年入职员", hire_date=date(this_year, 3, 1))
    await _make_employee(db_session, name="往年入职员", hire_date=date(this_year - 1, 3, 1))
    svc = OnboardingRecordService(db_session)

    records, total = await svc.list_records(year=this_year, keyword="入职员")
    assert total == 1
    assert records[0].name == "当年入职员"

    records_prev, total_prev = await svc.list_records(year=this_year - 1, keyword="入职员")
    assert total_prev == 1
    assert records_prev[0].name == "往年入职员"


@pytest.mark.asyncio
async def test_list_onboarding_records_by_employment(db_session: AsyncSession):
    """是否在职筛选按员工 status 派生：非「离职」即在职。"""
    await _make_employee(db_session, name="在职台账员")
    svc = OnboardingRecordService(db_session)
    records, total = await svc.list_records(is_employed="是", keyword="在职台账员")
    assert total == 1  # 新建员工 status 默认「待审批」，派生为在职


@pytest.mark.asyncio
async def test_list_onboarding_hire_years(db_session: AsyncSession):
    """年份选项聚合：员工档案入职日期的 distinct 年份降序返回。"""
    this_year = date.today().year
    await _make_employee(db_session, name="年份甲", hire_date=date(this_year, 1, 15))
    await _make_employee(db_session, name="年份乙", hire_date=date(this_year - 2, 6, 1))
    svc = OnboardingRecordService(db_session)
    years = await svc.list_hire_years()
    assert this_year in years
    assert this_year - 2 in years
    assert years == sorted(years, reverse=True)


@pytest.mark.asyncio
async def test_ledger_sources_empty_without_records(db_session: AsyncSession):
    """无系统内入职流程记录的员工，来源映射为空（前端显示「员工档案」）。"""
    svc = OnboardingRecordService(db_session)
    assert await svc.ledger_sources([]) == {}
    sources = await svc.ledger_sources([_rand("NOEXIST")])
    assert sources == {}


@pytest.mark.asyncio
async def test_get_onboarding_record_not_found_raises(db_session: AsyncSession):
    """查询不存在的入职记录应抛 NotFoundException。"""
    svc = OnboardingRecordService(db_session)
    with pytest.raises(NotFoundException):
        await svc.get_record(uuid.uuid4())


# ═══════════════════════════════════════════════════════════════
# 台账记录删除（保留的系统内记录清理）
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_delete_onboarding_record(db_session: AsyncSession):
    """删除入职记录后查询应抛 NotFoundException。"""
    emp = await _make_employee(db_session, name="待删入职员工")
    svc = OnboardingRecordService(db_session)
    records, _ = await svc.list_records(keyword="待删入职员工")
    assert len(records) >= 1

    # 创建员工自动生成的台账记录（员工视图返回 Employee，需经台账表定位记录）
    from sqlalchemy import select
    from app.modules.hr.models import OnboardingRecord
    rec = (await db_session.execute(
        select(OnboardingRecord).where(OnboardingRecord.name == "待删入职员工")
    )).scalars().first()
    assert rec is not None

    await svc.delete_record(rec.id)
    with pytest.raises(NotFoundException):
        await svc.get_record(rec.id)


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
async def test_api_get_onboarding_records_by_year(client):
    """GET /api/v1/hr/onboarding-records?year= 支持按入职年份归类。"""
    resp = await client.get(f"/api/v1/hr/onboarding-records?year={date.today().year}")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    for item in body["data"]:
        assert (item.get("hire_date") or "")[:4] == str(date.today().year)


@pytest.mark.asyncio
async def test_api_get_onboarding_records_employed_derived(client):
    """API 返回的 is_employed 由员工 status 派生（非离职=是）。"""
    resp = await client.get("/api/v1/hr/onboarding-records?page_size=5")
    assert resp.status_code == 200
    for item in resp.json()["data"]:
        assert item["is_employed"] in ("是", "否")


@pytest.mark.asyncio
async def test_api_get_onboarding_filter_options(client):
    """GET /api/v1/hr/onboarding-records/filter-options 返回年份聚合。"""
    resp = await client.get("/api/v1/hr/onboarding-records/filter-options")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "years" in data
    assert isinstance(data["years"], list)
