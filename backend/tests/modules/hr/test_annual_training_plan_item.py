"""年度培训计划项 — 业务规则测试。

覆盖计划项的列表查询、批量更新（全量替换）等核心规则。
走 service 层（真实 DB 回滚）。
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.modules.hr.schemas import (
    AnnualTrainingPlanCreate,
    AnnualTrainingPlanItemBatchUpdate,
    AnnualTrainingPlanItemCreate,
)
from app.modules.hr.service import AnnualTrainingPlanItemService, AnnualTrainingPlanService

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
        department=department or _rand("ITEMPLAN"),
    )
    return await svc.create_plan(data)


# ═══════════════════════════════════════════════════════════════
# 查询
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_list_items_empty(db_session: AsyncSession):
    """新建计划无明细项，列表为空。"""
    plan = await _make_plan(db_session)
    svc = AnnualTrainingPlanItemService(db_session)
    items = await svc.list_items(plan.id)
    assert items == []


# ═══════════════════════════════════════════════════════════════
# 批量更新
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_batch_update_items(db_session: AsyncSession):
    """批量更新计划项：全量替换旧明细。"""
    plan = await _make_plan(db_session)
    svc = AnnualTrainingPlanItemService(db_session)

    items_data = [
        AnnualTrainingPlanItemCreate(content_and_textbook="GMP基础知识", month="1月"),
        AnnualTrainingPlanItemCreate(content_and_textbook="安全操作规范", month="3月"),
        AnnualTrainingPlanItemCreate(content_and_textbook="设备维护保养", month="6月"),
    ]
    batch = AnnualTrainingPlanItemBatchUpdate(items=items_data)
    results = await svc.batch_update_items(plan.id, batch)

    assert len(results) == 3
    # 验证 sort_order 按输入顺序从 0 递增
    for idx, item in enumerate(results):
        assert item.sort_order == idx
    assert results[0].content_and_textbook == "GMP基础知识"
    assert results[1].content_and_textbook == "安全操作规范"
    assert results[2].content_and_textbook == "设备维护保养"


@pytest.mark.asyncio
async def test_batch_update_items_replaces_existing(db_session: AsyncSession):
    """批量更新应删除旧明细，只保留新明细。"""
    plan = await _make_plan(db_session)
    svc = AnnualTrainingPlanItemService(db_session)

    # 第一次批量更新：3 项
    first_batch = AnnualTrainingPlanItemBatchUpdate(items=[
        AnnualTrainingPlanItemCreate(content_and_textbook="项目A"),
        AnnualTrainingPlanItemCreate(content_and_textbook="项目B"),
        AnnualTrainingPlanItemCreate(content_and_textbook="项目C"),
    ])
    await svc.batch_update_items(plan.id, first_batch)

    # 第二次批量更新：2 项（替换旧数据）
    second_batch = AnnualTrainingPlanItemBatchUpdate(items=[
        AnnualTrainingPlanItemCreate(content_and_textbook="项目X"),
        AnnualTrainingPlanItemCreate(content_and_textbook="项目Y"),
    ])
    results = await svc.batch_update_items(plan.id, second_batch)

    assert len(results) == 2
    assert results[0].content_and_textbook == "项目X"
    assert results[1].content_and_textbook == "项目Y"


@pytest.mark.asyncio
async def test_batch_update_items_empty_list(db_session: AsyncSession):
    """空明细列表批量更新：清空所有计划项。"""
    plan = await _make_plan(db_session)
    svc = AnnualTrainingPlanItemService(db_session)

    # 先添加一些项
    batch = AnnualTrainingPlanItemBatchUpdate(items=[
        AnnualTrainingPlanItemCreate(content_and_textbook="待清除项目"),
    ])
    await svc.batch_update_items(plan.id, batch)

    # 空列表替换
    empty_batch = AnnualTrainingPlanItemBatchUpdate(items=[])
    results = await svc.batch_update_items(plan.id, empty_batch)
    assert results == []


# ═══════════════════════════════════════════════════════════════
# 边界
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_batch_update_items_nonexistent_plan_raises(db_session: AsyncSession):
    """对不存在的计划批量更新应抛 NotFoundException。"""
    svc = AnnualTrainingPlanItemService(db_session)
    batch = AnnualTrainingPlanItemBatchUpdate(items=[
        AnnualTrainingPlanItemCreate(content_and_textbook="孤立项"),
    ])
    with pytest.raises(NotFoundException):
        await svc.batch_update_items(uuid.uuid4(), batch)


# ═══════════════════════════════════════════════════════════════
# API 层
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_api_get_plan_items(client):
    """GET /api/v1/hr/annual-training-plans/{plan_id}/items 返回 200。"""
    dept = _rand("APIITEM")
    plan_resp = await client.post("/api/v1/hr/annual-training-plans", json={
        "year": 2025,
        "department": dept,
    })
    plan_id = plan_resp.json()["data"]["id"]

    resp = await client.get(f"/api/v1/hr/annual-training-plans/{plan_id}/items")
    assert resp.status_code == 200
    assert resp.json()["data"] == []


@pytest.mark.asyncio
async def test_api_batch_update_plan_items(client):
    """PUT 批量更新计划项→GET 验证。"""
    dept = _rand("APIBATCH")
    plan_resp = await client.post("/api/v1/hr/annual-training-plans", json={
        "year": 2025,
        "department": dept,
    })
    plan_id = plan_resp.json()["data"]["id"]

    resp = await client.put(
        f"/api/v1/hr/annual-training-plans/{plan_id}/items/batch",
        json={
            "items": [
                {"content_and_textbook": "API项目1", "month": "1月"},
                {"content_and_textbook": "API项目2", "month": "3月"},
            ],
        },
    )
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 2

    # 验证列表
    list_resp = await client.get(f"/api/v1/hr/annual-training-plans/{plan_id}/items")
    assert list_resp.status_code == 200
    assert len(list_resp.json()["data"]) == 2
