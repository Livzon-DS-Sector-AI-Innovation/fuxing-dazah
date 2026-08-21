"""内训师本部门数据范围测试：受限用户仅可查看和修改本部门数据"""

import pytest


@pytest.mark.asyncio
async def test_trainer_write_restricted_to_own_department(db_session, client, test_user):
    """新增/更新/删除内训师仅限本部门（scoped_departments 内）。"""
    from app.main import app
    from app.modules.hr.deps import HrAccessContext, get_hr_scope
    from app.modules.hr.models import HrTrainer

    async def _scoped():
        return HrAccessContext(
            user=test_user,
            data_scope="department",
            department="甲部门",
            employee_number=test_user.employee_no,
            scoped_departments=frozenset({"甲部门"}),
        )

    app.dependency_overrides[get_hr_scope] = _scoped
    try:
        other = HrTrainer(name="乙部培训师", department="乙部门")
        db_session.add(other)
        await db_session.flush()

        # 新增其他部门 → 403
        res = await client.post("/api/v1/hr/trainers", json={"name": "新培训师", "department": "乙部门"})
        assert res.status_code == 403, res.text

        # 新增本部门（部门留空自动填授权部门）→ 201
        res2 = await client.post("/api/v1/hr/trainers", json={"name": "本部门培训师"})
        assert res2.status_code == 201, res2.text
        assert res2.json()["data"]["department"] == "甲部门"

        # 更新其他部门 → 403
        res3 = await client.put(f"/api/v1/hr/trainers/{other.id}", json={"name": "改名", "department": "乙部门"})
        assert res3.status_code == 403, res3.text

        # 删除其他部门 → 403
        res4 = await client.delete(f"/api/v1/hr/trainers/{other.id}")
        assert res4.status_code == 403, res4.text

        # 清空台账（受限用户）→ 403
        res5 = await client.delete("/api/v1/hr/trainers")
        assert res5.status_code == 403, res5.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_trainer_list_restricted_to_own_department(db_session, client, test_user):
    """列表仅返回本部门内训师。"""
    from app.main import app
    from app.modules.hr.deps import HrAccessContext, get_hr_scope
    from app.modules.hr.models import HrTrainer

    db_session.add(HrTrainer(name="甲部培训师", department="甲部门"))
    db_session.add(HrTrainer(name="乙部培训师", department="乙部门"))
    await db_session.flush()

    async def _scoped():
        return HrAccessContext(
            user=test_user,
            data_scope="department",
            department="甲部门",
            employee_number=test_user.employee_no,
            scoped_departments=frozenset({"甲部门"}),
        )

    app.dependency_overrides[get_hr_scope] = _scoped
    try:
        res = await client.get("/api/v1/hr/trainers?page=1&page_size=50")
        assert res.status_code == 200, res.text
        names = [t["name"] for t in res.json()["data"]]
        assert "甲部培训师" in names
        assert "乙部培训师" not in names
    finally:
        app.dependency_overrides.clear()
