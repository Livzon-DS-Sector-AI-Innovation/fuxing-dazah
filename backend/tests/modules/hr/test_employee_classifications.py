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

        from app.modules.hr.models import Employee, EmployeeTag, TrainingRosterProfile
        name = f"查看人员{uuid4().hex[:4]}"
        emp_no = f"SOP{uuid4().hex[:6].upper()}"
        db_session.add(Employee(
            employee_number=emp_no, name="员工甲", department="甲部门",
            position="操作工", status="在职", hire_date=_date.today(),
        ))
        # 分类人员口径 = 培训人员名单（脱敏独立数据集）
        db_session.add(TrainingRosterProfile(
            employee_number=emp_no, name="员工甲", department="甲部门",
            position="操作工", status="在职",
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

    @pytest.mark.asyncio
    async def test_rename_classification_moves_employee_tags(self, db_session, client):
        """分类改名：同名标签一并改名，成员不失联。"""
        from sqlalchemy import text

        from app.modules.hr.models import EmployeeTag
        old, new = f"旧名{uuid4().hex[:4]}", f"新名{uuid4().hex[:4]}"
        res = await client.post("/api/v1/hr/employee-classifications", json={"name": old})
        cid = res.json()["data"]["id"]
        emp_no = f"RN{uuid4().hex[:6].upper()}"
        db_session.add(EmployeeTag(employee_number=emp_no, tag_name=old, created_by="HR测试员"))
        await db_session.flush()

        res2 = await client.put(f"/api/v1/hr/employee-classifications/{cid}", json={"name": new})
        assert res2.status_code == 200, res2.text
        assert res2.json()["data"]["name"] == new

        active = (await db_session.execute(
            text("SELECT tag_name FROM hr.employee_tags WHERE employee_number = :en AND is_deleted = false"),
            {"en": emp_no},
        )).scalars().all()
        assert active == [new]
        names = [c["name"] for c in (await client.get("/api/v1/hr/employee-classifications")).json()["data"]]
        assert new in names and old not in names

    @pytest.mark.asyncio
    async def test_rename_onto_existing_tag_keeps_one_active_row(self, db_session, client):
        """改成部分人已有的残留标签名（该名不在分类清单里）：不撞活跃行唯一索引，
        这些人在新名下只留一条有效标签。"""
        from sqlalchemy import text

        from app.modules.hr.models import EmployeeTag
        suffix = uuid4().hex[:4]
        src, dst = f"源分类{suffix}", f"残留名{suffix}"
        src_id = (await client.post("/api/v1/hr/employee-classifications", json={"name": src})).json()["data"]["id"]
        both, only_src = f"RB{suffix}", f"RO{suffix}"
        db_session.add_all([
            EmployeeTag(employee_number=both, tag_name=src, created_by="HR测试员"),
            EmployeeTag(employee_number=both, tag_name=dst, created_by="HR测试员"),
            EmployeeTag(employee_number=only_src, tag_name=src, created_by="HR测试员"),
        ])
        await db_session.flush()

        res = await client.put(f"/api/v1/hr/employee-classifications/{src_id}", json={"name": dst})
        assert res.status_code == 200, res.text

        rows = (await db_session.execute(
            text("SELECT employee_number, count(*) FROM hr.employee_tags "
                 "WHERE tag_name = :tn AND is_deleted = false GROUP BY employee_number"),
            {"tn": dst},
        )).all()
        assert dict(rows) == {both: 1, only_src: 1}

    @pytest.mark.asyncio
    async def test_rename_rejects_duplicate_and_blank(self, db_session, client):
        suffix = uuid4().hex[:4]
        name, other = f"改名分类{suffix}", f"已存在分类{suffix}"
        cid = (await client.post("/api/v1/hr/employee-classifications", json={"name": name})).json()["data"]["id"]
        await client.post("/api/v1/hr/employee-classifications", json={"name": other})

        dup = await client.put(f"/api/v1/hr/employee-classifications/{cid}", json={"name": other})
        assert dup.status_code == 400, dup.text
        blank = await client.put(f"/api/v1/hr/employee-classifications/{cid}", json={"name": "  "})
        assert blank.status_code == 400, blank.text
        names = [c["name"] for c in (await client.get("/api/v1/hr/employee-classifications")).json()["data"]]
        assert name in names

    @pytest.mark.asyncio
    async def test_creator_falls_back_to_employee_no_when_name_blank(self, db_session, client, test_user):
        """登录用户没有名字时，创建人回退到工号。

        身份用户模型上只有 employee_no、没有 employee_number：兜底的字段名写错时，
        用户名为空会直接 AttributeError（接口 500），平时只是被「有名字」短路掩盖。
        """
        from sqlalchemy import text

        test_user.name = ""
        name = f"无名用户分类{uuid4().hex[:4]}"
        res = await client.post("/api/v1/hr/employee-classifications", json={"name": name})
        assert res.status_code == 201, res.text

        rows = (await db_session.execute(
            text("SELECT created_by FROM hr.employee_classifications "
                 "WHERE name = :n AND is_deleted = false"),
            {"n": name},
        )).scalars().all()
        assert rows == [test_user.employee_no]
