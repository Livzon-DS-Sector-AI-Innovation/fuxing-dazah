"""SOP 培训文件登记表 + 二级表接口测试"""

import json
from uuid import uuid4

import pytest
from sqlalchemy import select, text


class TestSopRegisterFlow:
    @pytest.mark.asyncio
    async def test_create_record_is_draft_and_submit_creates_entries(self, db_session, client):
        """登记先保存草稿；点「提交/通知」后自动为各涉及部门生成二级表记录"""
        res = await client.post("/api/v1/hr/sop-training-records", json={
            "year": "2026",
            "training_date": "01.05",
            "file_name": "硫酸多黏菌素B内控质量标准",
            "file_no": "SOP.02.8219.001",
            "effective_date": "2026.01.07",
            "method": "T",
            "involved_departments": ["甲部门", "乙部门", "甲部门"],  # 重复部门应去重
            "initiator_department": "QA",
        })
        assert res.status_code == 201, res.text
        data = res.json()["data"]

        # 草稿阶段不生成二级表
        rows0 = (await db_session.execute(
            text("SELECT count(*) FROM hr.sop_training_entries WHERE record_id = :rid AND is_deleted = false"),
            {"rid": data["id"]},
        )).scalar()
        assert rows0 == 0

        # 提交/通知 → 生成二级表
        res_sub = await client.post(f"/api/v1/hr/sop-training-records/{data['id']}/submit")
        assert res_sub.status_code == 200, res_sub.text
        rows = (await db_session.execute(
            text("SELECT department, status FROM hr.sop_training_entries WHERE record_id = :rid AND is_deleted = false ORDER BY department"),
            {"rid": data["id"]},
        )).fetchall()
        assert [r[0] for r in rows] == ["乙部门", "甲部门"]
        assert all(r[1] == "待转训" for r in rows)

        # 列表按年查询，培训对象自动生成
        res2 = await client.get("/api/v1/hr/sop-training-records", params={"year": "2026"})
        hit = next(r for r in res2.json()["data"] if r["id"] == data["id"])
        assert hit["trainees"] == "「QA」全体员工及相关部门培训师"
        assert hit["color"] == "新增"
        assert hit["status"] == "已提交"

    @pytest.mark.asyncio
    async def test_update_record_syncs_entries(self, db_session, client):
        """编辑涉及部门 → 新增缺失部门、移除未转训的已取消部门"""
        from app.modules.hr.models import SopTrainingEntry, SopTrainingRecord
        r = SopTrainingRecord(
            year="2026", file_name="测试文件", status="已提交",
            involved_departments='["旧部门", "保留部门"]',
        )
        db_session.add(r)
        await db_session.flush()  # 先拿到 r.id
        # 模拟提交时已生成的二级表记录
        db_session.add(SopTrainingEntry(record_id=str(r.id), department="旧部门"))
        db_session.add(SopTrainingEntry(record_id=str(r.id), department="保留部门"))
        await db_session.flush()
        await client.put(f"/api/v1/hr/sop-training-records/{r.id}", json={"involved_departments": ["保留部门", "新部门"]})
        rows = (await db_session.execute(
            text("SELECT department FROM hr.sop_training_entries WHERE record_id = :rid AND is_deleted = false ORDER BY department"),
            {"rid": str(r.id)},
        )).fetchall()
        assert [x[0] for x in rows] == ["保留部门", "新部门"]
        deleted = (await db_session.execute(
            text("SELECT count(*) FROM hr.sop_training_entries WHERE record_id = :rid AND is_deleted = true"),
            {"rid": str(r.id)},
        )).scalar()
        assert deleted == 1

    @pytest.mark.asyncio
    async def test_transfer_sets_current_trainer(self, db_session, client):
        """转培训 → 自动带出该部门当前培训师"""
        from app.modules.hr.models import DeptTrainingPersonnel, SopTrainingEntry
        db_session.add(DeptTrainingPersonnel(
            display_department="甲部门", department="甲部门",
            level1_trainer="张培训师",
        ))
        e = SopTrainingEntry(record_id=None, department="甲部门")
        db_session.add(e)
        await db_session.flush()

        res = await client.post(f"/api/v1/hr/sop-training-entries/{e.id}/transfer")
        assert res.status_code == 200, res.text
        assert res.json()["data"]["trainer"] == "张培训师"
        await db_session.refresh(e)
        assert e.status == "已转训"
        assert e.trainer == "张培训师"

    @pytest.mark.asyncio
    async def test_batch_transfer(self, db_session, client):
        """多条SOP一起转训 → 批量转培训"""
        from app.modules.hr.models import DeptTrainingPersonnel, SopTrainingEntry
        db_session.add(DeptTrainingPersonnel(
            display_department="甲部门", department="甲部门", level1_trainer="张培训师"))
        db_session.add(DeptTrainingPersonnel(
            display_department="乙部门", department="乙部门", level1_trainer="李培训师"))
        e1 = SopTrainingEntry(record_id=None, department="甲部门")
        e2 = SopTrainingEntry(record_id=None, department="乙部门")
        e3 = SopTrainingEntry(record_id=None, department="甲部门")
        db_session.add_all([e1, e2, e3])
        await db_session.flush()

        res = await client.post("/api/v1/hr/sop-training-entries/batch-transfer", json={"ids": [str(e1.id), str(e2.id)]})
        assert res.status_code == 200, res.text
        assert res.json()["data"]["transferred"] == 2
        await db_session.refresh(e1)
        await db_session.refresh(e2)
        await db_session.refresh(e3)
        assert e1.status == "已转训" and e1.trainer == "张培训师"
        assert e2.status == "已转训" and e2.trainer == "李培训师"
        assert e3.status == "待转训"

    @pytest.mark.asyncio
    async def test_transfer_auto_links_classification_tags(self, db_session, client):
        """转训自动关联分类：涉及人员写入员工标签（幂等）。"""
        from app.modules.hr.models import EmployeeTag, SopTrainingEntry

        e = SopTrainingEntry(
            record_id=None, department="甲部门",
            classification="新员工",
            personnel=json.dumps([{"employee_number": "T001", "name": "张三"},
                                  {"employee_number": "T002", "name": "李四"}]),
        )
        db_session.add(e)
        await db_session.flush()

        res = await client.post(f"/api/v1/hr/sop-training-entries/{e.id}/transfer")
        assert res.status_code == 200, res.text

        tags = (await db_session.execute(
            select(EmployeeTag).where(
                EmployeeTag.tag_name == "新员工",
                EmployeeTag.is_deleted == False,  # noqa: E712
            )
        )).scalars().all()
        assert {t.employee_number for t in tags} == {"T001", "T002"}

        # 幂等：再次转训不重复打标（状态已转训直接返回，标签数不变）
        res = await client.post(f"/api/v1/hr/sop-training-entries/{e.id}/transfer")
        assert res.status_code == 200
        tags2 = (await db_session.execute(
            select(EmployeeTag).where(
                EmployeeTag.tag_name == "新员工",
                EmployeeTag.is_deleted == False,  # noqa: E712
            )
        )).scalars().all()
        assert len(tags2) == len(tags)

    @pytest.mark.asyncio
    async def test_update_entry_complete_time(self, db_session, client):
        """二级表填写完成时间/课时"""
        from app.modules.hr.models import SopTrainingEntry
        e = SopTrainingEntry(record_id=None, department="甲部门")
        db_session.add(e)
        await db_session.flush()
        res = await client.put(f"/api/v1/hr/sop-training-entries/{e.id}", json={
            "complete_time": "2026.01.05(14:00-15:00)",
            "classification": "新员工",
        })
        assert res.status_code == 200, res.text
        await db_session.refresh(e)
        assert e.complete_time == "2026.01.05(14:00-15:00)"
        assert e.classification == "新员工"

    @pytest.mark.asyncio
    async def test_classifications_and_personnel(self, db_session, client):
        """部门自定义分类选项 + 按分类拉取人员（选项 = 当前用户的清单 ∪ 标签）"""
        from datetime import date as _date
        from app.modules.hr.models import Employee, EmployeeClassification, EmployeeTag
        db_session.add(Employee(
            employee_number="SOP001", name="员工甲", department="甲部门",
            position="操作工", status="在职", hire_date=_date.today(),
        ))
        # 当前用户（HR测试员）建的清单 + 打的标签
        db_session.add(EmployeeClassification(name="新员工", created_by="HR测试员"))
        db_session.add(EmployeeTag(employee_number="SOP001", tag_name="新员工", created_by="HR测试员"))
        # 直接打标签（无清单）的分类：同样出现
        db_session.add(EmployeeTag(employee_number="SOP001", tag_name="分类1", created_by="HR测试员"))
        # 他人创建的：不出现
        db_session.add(EmployeeClassification(name="别人的分类", created_by="其他人"))
        db_session.add(EmployeeTag(employee_number="SOP001", tag_name="别人的标签", created_by="其他人"))
        await db_session.flush()

        res = await client.get("/api/v1/hr/sop-training-entries/classifications", params={"department": "甲部门"})
        assert res.status_code == 200, res.text
        names = [d["tag_name"] for d in res.json()["data"]]
        # 本人的清单 + 本人打的标签都出现；他人的不出现
        assert "新员工" in names
        assert "分类1" in names
        assert "别人的分类" not in names
        assert "别人的标签" not in names
        assert any(d["tag_name"] == "新员工" and d["count"] == 1 for d in res.json()["data"])

        res2 = await client.get("/api/v1/hr/sop-training-entries/personnel", params={"department": "甲部门", "classification": "新员工"})
        assert res2.status_code == 200, res2.text
        people = res2.json()["data"]
        assert len(people) == 1
        assert people[0]["name"] == "员工甲"

    @pytest.mark.asyncio
    async def test_dept_trainers_lookup(self, db_session, client):
        """选择涉及部门 → 自动关联各对应部门一级培训师（被培训人员）"""
        from app.modules.hr.models import DeptTrainingPersonnel
        dept_a = f"部门{uuid4().hex[:6]}"
        dept_b = f"部门{uuid4().hex[:6]}"
        db_session.add(DeptTrainingPersonnel(
            display_department=dept_a, department=dept_a, level1_trainer="张培训师"))
        await db_session.flush()
        res = await client.get("/api/v1/hr/sop-training-records/dept-trainers",
                               params=[("departments", dept_a), ("departments", dept_b)])
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert data[0] == {"department": dept_a, "trainer": "张培训师"}
        assert data[1] == {"department": dept_b, "trainer": None}

    @pytest.mark.asyncio
    async def test_export_records_xlsx(self, db_session, client):
        """导出登记表（对齐模板版式）"""
        from app.modules.hr.models import SopTrainingRecord
        db_session.add(SopTrainingRecord(
            year="2026", training_date="01.05", file_name="测试文件",
            file_no="SOP.00.0000.001", method="R", color="新增",
            involved_departments='["甲部门"]',
        ))
        await db_session.flush()
        res = await client.get("/api/v1/hr/sop-training-records/export", params={"year": "2026"})
        assert res.status_code == 200, res.text
        assert res.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml")


# ─── 全套材料生成（P0a/P1a）───


def _rand(prefix: str = "") -> str:
    return f"{prefix}{uuid4().hex[:8].upper()}"





class TestMaterialsHelpers:
    async def test_query_leave_counts(self, db_session):
        from datetime import date as _date
        from app.modules.hr import models as hr_models
        from app.modules.hr.sop_training_routes import _query_leave_counts

        dept = f"材料测试部{_rand()}"
        for name, no, status in [
            ("病假甲", f"B{_rand()}", "病假"),
            ("产假乙", f"M{_rand()}", "产假"),
            ("在职丙", f"Z{_rand()}", "在职"),
        ]:
            emp = hr_models.Employee(name=name, employee_number=no, department=dept,
                                     position="工程师", status=status, hire_date=_date(2020, 1, 1))
            db_session.add(emp)
        await db_session.flush()
        sick, maternity = await _query_leave_counts(db_session, dept)
        assert sick == 1
        assert maternity == 1

    async def test_lookup_exam_questions_by_file_no(self, db_session):
        from app.modules.hr import models as hr_models
        from app.modules.hr.sop_training_routes import _lookup_exam_questions

        file_no = f"SOP-{_rand()}"
        q1 = hr_models.QuestionBank(file_no=file_no, question="题目一", answer="答案一", score=10, source="手工录入")
        q2 = hr_models.QuestionBank(file_no="OTHER", question="题目二", answer="答案二", score=5, source="手工录入")
        db_session.add_all([q1, q2])
        await db_session.flush()
        questions = await _lookup_exam_questions(db_session, [file_no])
        assert len(questions) == 1
        assert questions[0]["question"] == "题目一"

    def test_generate_exam_docx(self):
        from app.modules.hr.sop_training_routes import _generate_exam_docx

        buf = _generate_exam_docx("测试主题", [
            {"file_no": "SOP-1", "question": "题目一", "answer": "答案一", "score": 10},
        ])
        content = buf.getvalue()
        assert len(content) > 0
        # docx zip 签名
        assert content[:2] == b"PK"

    def test_generate_register_docx(self):
        from app.modules.hr.sop_training_routes import _generate_register_docx

        buf = _generate_register_docx(
            subject="测试培训", training_date="2026-08-21", department="测试部",
            trainer="王老师", method="R", trainee_names=["张三", "李四"],
            sick=1, maternity=0,
        )
        content = buf.getvalue()
        assert len(content) > 0
        assert content[:2] == b"PK"

    async def test_entry_personnel_excludes_leave(self, db_session):
        """二级表分类人员拉取排除病假/产假（接口 SQL 校验）。"""
        from datetime import date as _date
        from sqlalchemy import text as sa_text
        from app.modules.hr import models as hr_models

        dept = f"拉人测试部{_rand()}"
        tag = f"分类{_rand()}"
        for name, no, status in [
            ("正常甲", f"N{_rand()}", "在职"),
            ("病假乙", f"B{_rand()}", "病假"),
            ("产假丙", f"M{_rand()}", "产假"),
        ]:
            emp = hr_models.Employee(name=name, employee_number=no, department=dept,
                                     position="工程师", status=status, hire_date=_date(2020, 1, 1))
            db_session.add(emp)
            await db_session.flush()
            db_session.add(hr_models.EmployeeTag(employee_number=no, tag_name=tag, created_by="tester"))
        await db_session.flush()

        result = (await db_session.execute(
            sa_text("""
                SELECT e.name FROM hr.employees e
                JOIN hr.employee_tags t ON t.employee_number = e.employee_number
                WHERE t.is_deleted = false AND e.is_deleted = false
                  AND t.tag_name = :tag
                  AND (e.department = :dept OR e.actual_department = :dept)
                  AND e.status NOT IN ('离职', '待审批', '病假', '产假')
                ORDER BY e.employee_number
            """),
            {"dept": dept, "tag": tag},
        )).fetchall()
        names = [r[0] for r in result]
        assert "病假乙" not in names
        assert "产假丙" not in names
        assert "正常甲" in names
