"""班组管理 — 业务规则测试。

覆盖班组的 CRUD、部门外键校验等核心规则。
走 service 层（真实 DB 回滚）。
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.modules.hr.schemas import DepartmentCreate, TeamCreate, TeamUpdate
from app.modules.hr.service import DepartmentService, TeamService

from tests.modules.hr.conftest import _rand


# ── 辅助函数 ──

async def _make_department(db: AsyncSession, *, code: str | None = None, name: str = "测试部门") -> object:
    """经 service 创建一个部门并返回，供班组关联使用。"""
    svc = DepartmentService(db)
    data = DepartmentCreate(name=name, code=code or _rand("DEPT"))
    return await svc.create_department(data)


async def _make_team(
    db: AsyncSession,
    *,
    name: str = "测试班组",
    department_id: uuid.UUID | None = None,
) -> object:
    """经 service 创建一个班组并返回。"""
    if department_id is None:
        dept = await _make_department(db)
        department_id = dept.id
    svc = TeamService(db)
    data = TeamCreate(name=name, department_id=department_id)
    return await svc.create_team(data)


# ═══════════════════════════════════════════════════════════════
# 创建
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_team(db_session: AsyncSession):
    """正常创建班组。"""
    team = await _make_team(db_session, name="包装A班")
    assert team.id is not None
    assert team.name == "包装A班"


@pytest.mark.asyncio
async def test_create_team_nonexistent_department_raises(db_session: AsyncSession):
    """关联不存在的部门应抛 NotFoundException。"""
    svc = TeamService(db_session)
    data = TeamCreate(name="孤立班组", department_id=uuid.uuid4())
    with pytest.raises(NotFoundException):
        await svc.create_team(data)


# ═══════════════════════════════════════════════════════════════
# 查询
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_team(db_session: AsyncSession):
    """按 ID 查询班组。"""
    team = await _make_team(db_session, name="质检班")
    svc = TeamService(db_session)
    found = await svc.get_team(team.id)
    assert found.id == team.id
    assert found.name == "质检班"


@pytest.mark.asyncio
async def test_get_team_not_found_raises(db_session: AsyncSession):
    """查询不存在的班组应抛 NotFoundException。"""
    svc = TeamService(db_session)
    with pytest.raises(NotFoundException):
        await svc.get_team(uuid.uuid4())


@pytest.mark.asyncio
async def test_list_teams(db_session: AsyncSession):
    """列表查询可找到刚创建的班组。"""
    svc = TeamService(db_session)
    dept = await _make_department(db_session, name="过滤测试部")
    team = await _make_team(db_session, name="过滤班组", department_id=dept.id)

    teams, total = await svc.list_teams(department_id=dept.id)
    assert total >= 1
    ids = [t.id for t in teams]
    assert team.id in ids


# ═══════════════════════════════════════════════════════════════
# 更新
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_update_team(db_session: AsyncSession):
    """正常更新班组名称。"""
    team = await _make_team(db_session, name="旧班名")
    svc = TeamService(db_session)
    data = TeamUpdate(name="新班名")
    updated = await svc.update_team(team.id, data)
    assert updated.name == "新班名"


@pytest.mark.asyncio
async def test_update_team_change_department(db_session: AsyncSession):
    """班组更换到另一个存在的部门。"""
    dept_a = await _make_department(db_session, name="部门A")
    dept_b = await _make_department(db_session, name="部门B")
    team = await _make_team(db_session, name="迁移班组", department_id=dept_a.id)

    svc = TeamService(db_session)
    data = TeamUpdate(department_id=dept_b.id)
    updated = await svc.update_team(team.id, data)
    assert updated.department_id == dept_b.id


@pytest.mark.asyncio
async def test_update_team_nonexistent_department_raises(db_session: AsyncSession):
    """班组更换到不存在的部门应抛 NotFoundException。"""
    team = await _make_team(db_session)
    svc = TeamService(db_session)
    data = TeamUpdate(department_id=uuid.uuid4())
    with pytest.raises(NotFoundException):
        await svc.update_team(team.id, data)


@pytest.mark.asyncio
async def test_update_nonexistent_team_raises(db_session: AsyncSession):
    """更新不存在的班组应抛 NotFoundException。"""
    svc = TeamService(db_session)
    with pytest.raises(NotFoundException):
        await svc.update_team(uuid.uuid4(), TeamUpdate(name="不存在"))


# ═══════════════════════════════════════════════════════════════
# 删除
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_delete_team(db_session: AsyncSession):
    """删除后查询应抛 NotFoundException。"""
    team = await _make_team(db_session)
    svc = TeamService(db_session)
    await svc.delete_team(team.id)
    with pytest.raises(NotFoundException):
        await svc.get_team(team.id)


# ═══════════════════════════════════════════════════════════════
# API 层
# ═══════════════════════════════════════════════════════════════
# 注：POST/PUT/DELETE 端点的 TeamResponse 序列化存在 MissingGreenlet bug，
# 暂只覆盖 GET 列表端点，等 API bug 修复后再补 POST/GET/DELETE 测试。

@pytest.mark.asyncio
async def test_api_get_teams(client):
    """GET /api/v1/hr/teams 返回 200 和 data。"""
    resp = await client.get("/api/v1/hr/teams")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
