"""员工自定义分类清单（下拉选项模式）接口测试"""

from uuid import uuid4

import pytest


class TestEmployeeClassifications:
    @pytest.mark.asyncio
    async def test_create_and_list_classification(self, db_session, client):
        """新增分类后，清单列表应包含该分类"""
        name = f"新员工{uuid4().hex[:4]}"
        res = await client.post("/api/v1/hr/employee-classifications", json={"name": name})
        assert res.status_code == 201, res.text
        assert res.json()["data"]["name"] == name

        res2 = await client.get("/api/v1/hr/employee-classifications")
        assert res2.status_code == 200, res2.text
        names = [c["name"] for c in res2.json()["data"]]
        assert name in names

    @pytest.mark.asyncio
    async def test_delete_classification_removes_employee_tags(self, db_session, client):
        """删除分类时，该分类下所有员工的标签一并解除"""
        from sqlalchemy import text

        from app.modules.hr.models import EmployeeTag
        tag_name = f"待删分类{uuid4().hex[:4]}"
        db_session.add(EmployeeTag(employee_number="SOP001", tag_name=tag_name, created_by="HR测试员"))
        await db_session.flush()
        res = await client.post("/api/v1/hr/employee-classifications", json={"name": tag_name})
        assert res.status_code == 201, res.text
        cid = res.json()["data"]["id"]

        res2 = await client.delete(f"/api/v1/hr/employee-classifications/{cid}")
        assert res2.status_code == 200, res2.text

        remain = (await db_session.execute(
            text("SELECT count(*) FROM hr.employee_tags WHERE tag_name = :tn AND is_deleted = false"),
            {"tn": tag_name},
        )).scalar()
        assert remain == 0

        res3 = await client.get("/api/v1/hr/employee-classifications")
        names = [c["name"] for c in res3.json()["data"]]
        assert tag_name not in names

    @pytest.mark.asyncio
    async def test_duplicate_classification_rejected(self, db_session, client):
        name = f"重复分类{uuid4().hex[:4]}"
        await client.post("/api/v1/hr/employee-classifications", json={"name": name})
        res = await client.post("/api/v1/hr/employee-classifications", json={"name": name})
        assert res.status_code == 400, res.text

    @pytest.mark.asyncio
    async def test_classification_members(self, db_session, client):
        """点击分类可查看分类下收纳的具体人员"""
        from datetime import date as _date

        from app.modules.hr.models import Employee, EmployeeTag
        name = f"查看人员{uuid4().hex[:4]}"
        emp_no = f"SOP{uuid4().hex[:6].upper()}"
        db_session.add(Employee(
            employee_number=emp_no, name="员工甲", department="甲部门",
            position="操作工", status="在职", hire_date=_date.today(),
        ))
        db_session.add(EmployeeTag(employee_number=emp_no, tag_name=name, created_by="HR测试员"))
        await db_session.flush()
        res = await client.post("/api/v1/hr/employee-classifications", json={"name": name})
        assert res.status_code == 201, res.text
        cid = res.json()["data"]["id"]

        res2 = await client.get(f"/api/v1/hr/employee-classifications/{cid}/members")
        assert res2.status_code == 200, res2.text
        members = res2.json()["data"]
        assert len(members) == 1
        assert members[0]["name"] == "员工甲"
        assert members[0]["employee_number"] == emp_no

        # 批量移除该分类下的人员
        res3 = await client.post(f"/api/v1/hr/employee-classifications/{cid}/remove-members",
                                 json={"employee_numbers": [emp_no]})
        assert res3.status_code == 200, res3.text
        assert res3.json()["data"]["removed"] == 1
        res4 = await client.get(f"/api/v1/hr/employee-classifications/{cid}/members")
        assert res4.json()["data"] == []
