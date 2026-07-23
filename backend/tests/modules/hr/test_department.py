"""部门管理 — 业务规则测试。

覆盖部门的 CRUD、编码唯一性、软删除后可重建等核心规则。
断言以业务规则为准，走 service 层（真实 DB 回滚）。
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateException, NotFoundException
from app.modules.hr.schemas import DepartmentCreate, DepartmentUpdate
from app.modules.hr.service import DepartmentService

from tests.modules.hr.conftest import _rand


# ── 辅助函数 ──

async def _make_dept(db: AsyncSession, *, code: str | None = None, name: str = "测试部门") -> object:
    """经 service 创建一个部门并返回。"""
    svc = DepartmentService(db)
    data = DepartmentCreate(
        name=name,
        code=code or _rand("DEPT"),
    )
    return await svc.create_department(data)


# ═══════════════════════════════════════════════════════════════
# 创建
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_department(db_session: AsyncSession):
    """正常创建部门。"""
    dept = await _make_dept(db_session, name="人力资源部")
    assert dept.id is not None
    assert dept.name == "人力资源部"
    assert dept.code.startswith("DEPT")


@pytest.mark.asyncio
async def test_create_department_duplicate_code_raises(db_session: AsyncSession):
    """同编码重复创建应抛 DuplicateException。"""
    code = _rand("HR")
    await _make_dept(db_session, code=code)
    with pytest.raises(DuplicateException):
        await _make_dept(db_session, code=code)


# ═══════════════════════════════════════════════════════════════
# 查询
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_department(db_session: AsyncSession):
    """按 ID 查询部门。"""
    dept = await _make_dept(db_session)
    svc = DepartmentService(db_session)
    found = await svc.get_department(dept.id)
    assert found.id == dept.id
    assert found.name == dept.name


@pytest.mark.asyncio
async def test_get_department_not_found_raises(db_session: AsyncSession):
    """查询不存在的部门应抛 NotFoundException。"""
    import uuid
    svc = DepartmentService(db_session)
    with pytest.raises(NotFoundException):
        await svc.get_department(uuid.uuid4())


@pytest.mark.asyncio
async def test_list_departments(db_session: AsyncSession):
    """按关键字搜索可找到刚创建的部门。"""
    svc = DepartmentService(db_session)
    code = _rand("SEARCH")
    dept = await _make_dept(db_session, code=code, name="搜索测试部")
    departments, total = await svc.list_departments(keyword="搜索测试部")
    assert total >= 1
    ids = [d.id for d in departments]
    assert dept.id in ids


# ═══════════════════════════════════════════════════════════════
# 更新
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_update_department(db_session: AsyncSession):
    """正常更新部门名称。"""
    dept = await _make_dept(db_session, name="旧名称")
    svc = DepartmentService(db_session)
    data = DepartmentUpdate(name="新名称")
    updated = await svc.update_department(dept.id, data)
    assert updated.name == "新名称"


@pytest.mark.asyncio
async def test_update_nonexistent_department_raises(db_session: AsyncSession):
    """更新不存在的部门应抛 NotFoundException。"""
    import uuid
    svc = DepartmentService(db_session)
    with pytest.raises(NotFoundException):
        await svc.update_department(uuid.uuid4(), DepartmentUpdate(name="??"))


# ═══════════════════════════════════════════════════════════════
# 删除
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_delete_department(db_session: AsyncSession):
    """删除后查询应抛 NotFoundException。"""
    dept = await _make_dept(db_session)
    svc = DepartmentService(db_session)
    await svc.delete_department(dept.id)
    with pytest.raises(NotFoundException):
        await svc.get_department(dept.id)


@pytest.mark.asyncio
async def test_delete_then_recreate_same_code(db_session: AsyncSession):
    """删除后同编码可重建（唯一约束不限制已删除记录）。"""
    code = _rand("RECREATE")
    first = await _make_dept(db_session, code=code)
    svc = DepartmentService(db_session)
    await svc.delete_department(first.id)

    # 重建同编码部门
    second = await _make_dept(db_session, code=code)
    assert second.id != first.id
    assert second.code == code


# ═══════════════════════════════════════════════════════════════
# API 层 — HTTP 语义验证
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_api_get_departments(client):
    """GET /api/v1/hr/departments 返回 200。"""
    resp = await client.get("/api/v1/hr/departments")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body


@pytest.mark.asyncio
async def test_api_create_and_get_department(client):
    """POST 创建 → GET 详情 完整链路。"""
    code = _rand("API")
    resp = await client.post("/api/v1/hr/departments", json={
        "name": "API测试部",
        "code": code,
    })
    assert resp.status_code == 201
    dept_id = resp.json()["data"]["id"]

    resp2 = await client.get(f"/api/v1/hr/departments/{dept_id}")
    assert resp2.status_code == 200
    assert resp2.json()["data"]["name"] == "API测试部"


@pytest.mark.asyncio
async def test_api_delete_department(client):
    """DELETE 后 GET 返回 404。"""
    code = _rand("DEL")
    resp = await client.post("/api/v1/hr/departments", json={
        "name": "待删除部门",
        "code": code,
    })
    dept_id = resp.json()["data"]["id"]

    await client.delete(f"/api/v1/hr/departments/{dept_id}")
    resp2 = await client.get(f"/api/v1/hr/departments/{dept_id}")
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_api_duplicate_code_returns_409(client):
    """同编码创建两次，第二次返回 409。"""
    code = _rand("DUP")
    payload = {"name": "部门A", "code": code}
    await client.post("/api/v1/hr/departments", json=payload)
    resp = await client.post("/api/v1/hr/departments", json=payload)
    assert resp.status_code == 409
