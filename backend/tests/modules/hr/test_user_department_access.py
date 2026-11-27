"""多部门访问授权（/user-department-access）与培训管理员候选（/training-admins）。"""

from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.models import DeptTrainingPersonnel
from app.platform.identity.models import User
from tests.modules.hr.conftest import _rand


async def test_grant_list_and_revoke(db_session: AsyncSession, client: AsyncClient, test_user):
    """授权增删查全流程：列表带用户名关联；重复授权 400；移除后 404。"""
    dept = _rand("授权部")
    created = await client.post("/api/v1/hr/user-department-access", json={
        "user_id": str(test_user.id), "department": dept,
    })
    assert created.status_code == 201, created.text

    # 同用户同部门重复授权 → 400
    dup = await client.post("/api/v1/hr/user-department-access", json={
        "user_id": str(test_user.id), "department": dept,
    })
    assert dup.status_code == 400

    lst = await client.get("/api/v1/hr/user-department-access")
    assert lst.status_code == 200, lst.text
    mine = [
        r for r in lst.json()["data"]
        if r["user_id"] == str(test_user.id) and r["department"] == dept
    ]
    assert len(mine) == 1
    assert mine[0]["user_name"] == test_user.name

    removed = await client.delete(f"/api/v1/hr/user-department-access/{mine[0]['id']}")
    assert removed.status_code == 200
    # 再次移除 → 404
    assert (await client.delete(
        f"/api/v1/hr/user-department-access/{mine[0]['id']}",
    )).status_code == 404


async def test_revoke_unknown_mapping_404(client: AsyncClient):
    res = await client.delete(f"/api/v1/hr/user-department-access/{uuid4()}")
    assert res.status_code == 404


async def test_training_admins_matched_from_personnel_table(
    db_session: AsyncSession, client: AsyncClient, test_user,
):
    """候选 = identity.users 中名字出现在部门培训人员表 training_admin 文本里的用户。"""
    dept = _rand("培训管理部")
    admin = User(name=_rand("管理员张"), employee_no=_rand("ADM"))
    outsider = User(name=_rand("无关李"), employee_no=_rand("OUT"))
    db_session.add_all([admin, outsider])
    db_session.add(DeptTrainingPersonnel(
        display_department=dept, department=dept,
        training_admin=admin.name, department_head=admin.name,
    ))
    await db_session.flush()

    res = await client.get("/api/v1/hr/training-admins")
    assert res.status_code == 200, res.text
    names = {u["name"] for u in res.json()["data"]}
    assert admin.name in names
    assert outsider.name not in names
    # 未出现在 training_admin 中的测试用户也不在候选里
    assert test_user.name not in names
