"""年度培训计划 — 业务规则测试。

覆盖年度培训计划的 CRUD、年份+部门唯一性等核心规则。
走 service 层（真实 DB 回滚）。
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateException, NotFoundException
from app.modules.hr.schemas import AnnualTrainingPlanCreate, AnnualTrainingPlanUpdate
from app.modules.hr.service import AnnualTrainingPlanService

from tests.modules.hr.conftest import _rand


# ── 辅助函数 ──

async def _make_plan(
    db: AsyncSession,
    *,
    year: int = 2025,
    department: str | None = None,
) -> object:
    """经 service 创建一个年度培训计划并返回。"""
    svc = AnnualTrainingPlanService(db)
    data = AnnualTrainingPlanCreate(
        year=year,
        department=department or _rand("PLAN"),
    )
    return await svc.create_plan(data)


# ═══════════════════════════════════════════════════════════════
# 创建
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_annual_training_plan(db_session: AsyncSession):
    """正常创建年度培训计划，默认状态为草稿。"""
    plan = await _make_plan(db_session, year=2025, department="生产部")
    assert plan.id is not None
    assert plan.year == 2025
    assert plan.department == "生产部"
    assert plan.status == "草稿"


@pytest.mark.asyncio
async def test_create_plan_duplicate_year_department_raises(db_session: AsyncSession):
    """同年+同部门重复创建应抛 DuplicateException。"""
    dept = _rand("DEPT")
    await _make_plan(db_session, year=2025, department=dept)
    with pytest.raises(DuplicateException):
        await _make_plan(db_session, year=2025, department=dept)


# ═══════════════════════════════════════════════════════════════
# 查询
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_annual_training_plan(db_session: AsyncSession):
    """按 ID 查询年度培训计划。"""
    plan = await _make_plan(db_session, year=2024, department="质量部")
    svc = AnnualTrainingPlanService(db_session)
    found = await svc.get_plan(plan.id)
    assert found.id == plan.id
    assert found.department == "质量部"


@pytest.mark.asyncio
async def test_get_plan_not_found_raises(db_session: AsyncSession):
    """查询不存在的年度培训计划应抛 NotFoundException。"""
    svc = AnnualTrainingPlanService(db_session)
    with pytest.raises(NotFoundException):
        await svc.get_plan(uuid.uuid4())


@pytest.mark.asyncio
async def test_list_plans_by_year(db_session: AsyncSession):
    """按年份过滤年度培训计划。"""
    svc = AnnualTrainingPlanService(db_session)
    plan = await _make_plan(db_session, year=2026, department=_rand("YEAR"))

    plans, total = await svc.list_plans(year=2026)
    assert total >= 1
    ids = [p.id for p in plans]
    assert plan.id in ids


@pytest.mark.asyncio
async def test_list_plans_by_department(db_session: AsyncSession):
    """按部门过滤年度培训计划。"""
    dept = _rand("DEPT")
    svc = AnnualTrainingPlanService(db_session)
    plan = await _make_plan(db_session, year=2026, department=dept)

    plans, total = await svc.list_plans(department=dept)
    assert total >= 1
    ids = [p.id for p in plans]
    assert plan.id in ids


# ═══════════════════════════════════════════════════════════════
# 更新
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_update_annual_training_plan(db_session: AsyncSession):
    """正常更新年度培训计划状态。"""
    plan = await _make_plan(db_session, year=2025, department="设备部")
    svc = AnnualTrainingPlanService(db_session)
    data = AnnualTrainingPlanUpdate(status="已发布")
    updated = await svc.update_plan(plan.id, data)
    assert updated.status == "已发布"


@pytest.mark.asyncio
async def test_update_nonexistent_plan_raises(db_session: AsyncSession):
    """更新不存在的年度培训计划应抛 NotFoundException。"""
    svc = AnnualTrainingPlanService(db_session)
    with pytest.raises(NotFoundException):
        await svc.update_plan(uuid.uuid4(), AnnualTrainingPlanUpdate(status="不存在"))


# ═══════════════════════════════════════════════════════════════
# 删除
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_delete_annual_training_plan(db_session: AsyncSession):
    """删除后查询应抛 NotFoundException。"""
    plan = await _make_plan(db_session, year=2025, department=_rand("DEL"))
    svc = AnnualTrainingPlanService(db_session)
    await svc.delete_plan(plan.id)
    with pytest.raises(NotFoundException):
        await svc.get_plan(plan.id)


# ═══════════════════════════════════════════════════════════════
# API 层
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_api_get_annual_training_plans(client):
    """GET /api/v1/hr/annual-training-plans 返回 200。"""
    resp = await client.get("/api/v1/hr/annual-training-plans")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body


@pytest.mark.asyncio
async def test_api_create_and_get_annual_training_plan(client):
    """POST 创建年度培训计划→GET 详情验证。"""
    dept = _rand("APIPLAN")
    resp = await client.post("/api/v1/hr/annual-training-plans", json={
        "year": 2025,
        "department": dept,
    })
    assert resp.status_code == 201
    plan_id = resp.json()["data"]["id"]

    resp2 = await client.get(f"/api/v1/hr/annual-training-plans/{plan_id}")
    assert resp2.status_code == 200
    assert resp2.json()["data"]["department"] == dept


@pytest.mark.asyncio
async def test_api_delete_annual_training_plan(client):
    """DELETE 年度培训计划后 GET 返回 404。"""
    dept = _rand("DELPLAN")
    resp = await client.post("/api/v1/hr/annual-training-plans", json={
        "year": 2025,
        "department": dept,
    })
    plan_id = resp.json()["data"]["id"]

    await client.delete(f"/api/v1/hr/annual-training-plans/{plan_id}")
    resp2 = await client.get(f"/api/v1/hr/annual-training-plans/{plan_id}")
    assert resp2.status_code == 404
