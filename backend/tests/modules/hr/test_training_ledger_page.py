"""培训台账页面 — 业务规则测试。

覆盖台账页面的创建（工号唯一性）、列表查询等核心规则。
走 service 层（真实 DB 回滚）。
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateException
from app.modules.hr.schemas import TrainingLedgerPageCreate
from app.modules.hr.service import TrainingLedgerPageService

from tests.modules.hr.conftest import _rand


# ── 辅助函数 ──

async def _make_page(
    db: AsyncSession,
    *,
    employee_number: str | None = None,
    employee_name: str = "测试学员",
) -> object:
    """经 service 创建一个培训台账页面并返回。"""
    svc = TrainingLedgerPageService(db)
    data = TrainingLedgerPageCreate(
        employee_number=employee_number or _rand("PAGE"),
        employee_name=employee_name,
    )
    return await svc.create_page(data)


# ═══════════════════════════════════════════════════════════════
# 创建
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_training_ledger_page(db_session: AsyncSession):
    """正常创建培训台账页面。"""
    page = await _make_page(db_session, employee_name="张三")
    assert page.id is not None
    assert page.employee_name == "张三"


@pytest.mark.asyncio
async def test_create_page_duplicate_employee_number_raises(db_session: AsyncSession):
    """同工号重复创建台账页面应抛 DuplicateException。"""
    emp_no = _rand("DUPAGE")
    await _make_page(db_session, employee_number=emp_no)
    with pytest.raises(DuplicateException):
        await _make_page(db_session, employee_number=emp_no)


# ═══════════════════════════════════════════════════════════════
# 查询
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_list_pages(db_session: AsyncSession):
    """列表查询可找到刚创建的台账页面。"""
    svc = TrainingLedgerPageService(db_session)
    page = await _make_page(db_session, employee_name="列表测试员")

    pages = await svc.list_pages()
    assert len(pages) >= 1
    ids = [p.id for p in pages]
    assert page.id in ids


@pytest.mark.asyncio
async def test_list_pages_with_department(db_session: AsyncSession):
    """带部门信息的页面列表查询不抛异常。"""
    svc = TrainingLedgerPageService(db_session)
    await _make_page(db_session, employee_name="部门测试员")
    pages_with_dept = await svc.list_pages_with_department()
    assert len(pages_with_dept) >= 1


# ═══════════════════════════════════════════════════════════════
# API 层
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_api_get_training_ledger_pages(client):
    """GET /api/v1/hr/training-ledgers/pages 返回 200。"""
    resp = await client.get("/api/v1/hr/training-ledgers/pages")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body


@pytest.mark.asyncio
async def test_api_create_training_ledger_page(client):
    """POST 创建台账页面，返回 201。"""
    emp_no = _rand("APIPAGE")
    resp = await client.post("/api/v1/hr/training-ledgers/pages", json={
        "employee_number": emp_no,
        "employee_name": "API页面测试员",
    })
    assert resp.status_code == 201
    assert resp.json()["data"]["employee_name"] == "API页面测试员"
