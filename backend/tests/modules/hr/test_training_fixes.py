"""培训板块审计修复的回归测试（先失败后修复）。"""

import json
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.modules.hr.deps import HrAccessContext


def _ctx(data_scope: str, scoped: set[str] | None = None) -> HrAccessContext:
    from tests.modules.hr.conftest import _ALL_HR_PERMS  # noqa: F401
    class _U:
        name = "测试员"
        employee_no = "TEST001"
    return HrAccessContext(
        user=_U(),  # type: ignore[arg-type]
        data_scope=data_scope,
        department=next(iter(scoped)) if scoped else None,
        employee_number="TEST001",
        scoped_departments=frozenset(scoped or set()),
    )


class TestDocumentGenerators:
    def test_notification_uses_issue_date(self):
        from io import BytesIO

        from docx import Document

        from app.modules.hr.notification_document_generator import (
            TrainingNotificationInput,
            generate_training_notification,
        )

        buf = generate_training_notification(TrainingNotificationInput(
            department="甲部门", training_date=date(2026, 11, 11),
            issue_date=date(2026, 11, 5), subject="测试培训",
        ))
        doc = Document(BytesIO(buf.getvalue()))
        assert "2026年11月05日" in doc.paragraphs[1].text

    def test_registration_empty_records_removes_loop_markers(self):
        from io import BytesIO

        from docx import Document

        from app.modules.hr.training_registration_generator import (
            generate_training_registration_sync,
        )

        buf = generate_training_registration_sync([])
        doc = Document(BytesIO(buf.getvalue()))
        body = "\n".join(p.text for p in doc.paragraphs)
        assert "{#台账}" not in body and "{/台账}" not in body

    def test_signin_multi_page_header_uses_word_page_fields(self):
        from io import BytesIO

        from docx import Document

        from app.modules.hr.schemas import TrainingSignInSheetInput
        from app.modules.hr.signin_document_generator import (
            generate_training_sign_in_sheet,
        )

        names = [f"员工{i:02d}" for i in range(30)]
        buf = generate_training_sign_in_sheet(TrainingSignInSheetInput(
            training_date=date(2026, 11, 11), department="生产部", topic="测试",
            employee_names=names,
            employee_departments={n: "生产部" for n in names},
        ))
        doc = Document(BytesIO(buf.getvalue()))
        xml = doc.sections[0].header._element.xml
        assert 'w:instr=" PAGE "' in xml and 'w:instr=" NUMPAGES "' in xml


class TestTrainingEvaluationEndpoint:
    @pytest.mark.asyncio
    async def test_basic_payload_does_not_500(self, client):
        res = await client.post("/api/v1/hr/training-evaluation", json={"subject": "测试培训"})
        assert res.status_code == 200, res.text


class TestSopBatchMaterials:
    @pytest.mark.asyncio
    async def test_batch_materials_uses_record_method(self, db_session, client):
        from app.modules.hr.models import SopTrainingEntry, SopTrainingRecord

        rec = SopTrainingRecord(
            year="2026", file_name="测试文件", file_no="SOP-T-001",
            method="T", involved_departments='["甲部门"]', status="已提交",
        )
        db_session.add(rec)
        await db_session.flush()
        entry = SopTrainingEntry(
            record_id=str(rec.id), department="甲部门",
            personnel=json.dumps([{"name": "张三", "employee_number": "T001"}]),
        )
        db_session.add(entry)
        await db_session.flush()

        res = await client.post(
            "/api/v1/hr/sop-training-entries/batch-materials",
            json={"ids": [str(entry.id)]},
        )
        assert res.status_code == 200, res.text
        assert res.headers["content-type"] == "application/zip"


class TestQaCorrectness:
    @pytest.mark.asyncio
    async def test_low_total_paper_derives_grade_lines(self, client):
        res = await client.post("/api/v1/hr/qa-assessments", json={
            "subject": "低分试卷", "department": "甲部门",
            "questions": [{"question": f"题{i}", "answer": "答", "score": 10} for i in range(4)],
            "question_count": 4, "trainee_names": ["张三"],
        })
        assert res.status_code == 201, res.text
        aid = res.json()["data"]["id"]
        detail = await client.get(f"/api/v1/hr/qa-assessments/{aid}")
        a = detail.json()["data"]["assessment"]
        assert a["full_score"] == 40
        assert a["excellent_line"] == 36
        assert a["pass_line"] == 32

    @pytest.mark.asyncio
    async def test_same_name_scores_kept_separately(self, db_session, client):
        from app.modules.hr.models import QaAssessment, TrainingRosterProfile

        for no in ("1001", "1002"):
            db_session.add(TrainingRosterProfile(
                employee_number=no, name="张三", department="甲部门",
                position="操作工", status="在职",
            ))
        aid = uuid4()
        db_session.add(QaAssessment(
            id=aid, subject="同名测试", department="甲部门", full_score=100,
            excellent_line=90, pass_line=80, question_count=4,
            questions=[{"question": f"题{i}", "answer": "答", "score": 25} for i in range(4)],
            trainee_names=["张三"],
        ))
        await db_session.flush()

        res = await client.put(f"/api/v1/hr/qa-assessments/{aid}/scores", json={
            "assessed_date": "2026-11-11",
            "scores": [
                {"employee_name": "张三", "employee_number": "1001", "wrong_questions": []},
                {"employee_name": "张三", "employee_number": "1002", "wrong_questions": [1]},
            ],
        })
        assert res.status_code == 200, res.text
        rows = (await db_session.execute(
            text("SELECT employee_number, total_score FROM hr.qa_assessment_scores "
                 "WHERE assessment_id = :aid AND is_deleted = false ORDER BY employee_number"),
            {"aid": aid},
        )).fetchall()
        assert [r[0] for r in rows] == ["1001", "1002"]
        assert [r[1] for r in rows] == [100, 75]

    @pytest.mark.asyncio
    async def test_random_scores_low_total_paper_writes_rows(self, db_session, client):
        from app.modules.hr.models import QaAssessment, TrainingRosterProfile

        for no, name in (("3001", "甲"), ("3002", "乙")):
            db_session.add(TrainingRosterProfile(
                employee_number=no, name=name, department="甲部门",
                position="操作工", status="在职",
            ))
        aid = uuid4()
        db_session.add(QaAssessment(
            id=aid, subject="随机测试", department="甲部门", full_score=40,
            excellent_line=90, pass_line=80, question_count=4,
            questions=[{"question": f"题{i}", "answer": "答", "score": 10} for i in range(4)],
            trainee_names=["甲", "乙"],
        ))
        await db_session.flush()

        res = await client.post(
            f"/api/v1/hr/qa-assessments/{aid}/random-scores",
            params={"excellent_ratio": 0.5},
        )
        assert res.status_code == 200, res.text
        assert res.json()["data"]["generated"] == 2
        rows = (await db_session.execute(
            text("SELECT employee_number, total_score FROM hr.qa_assessment_scores "
                 "WHERE assessment_id = :aid AND is_deleted = false ORDER BY employee_number"),
            {"aid": aid},
        )).fetchall()
        assert [r[0] for r in rows] == ["3001", "3002"]

    @pytest.mark.asyncio
    async def test_scores_without_employee_number_resolve_in_department(self, db_session, client):
        from app.modules.hr.models import QaAssessment, TrainingRosterProfile

        for no, dept in (("4001", "甲部门"), ("4002", "乙部门")):
            db_session.add(TrainingRosterProfile(
                employee_number=no, name="丙", department=dept,
                position="操作工", status="在职",
            ))
        aid = uuid4()
        db_session.add(QaAssessment(
            id=aid, subject="无工号测试", department="甲部门", full_score=100,
            excellent_line=90, pass_line=80, question_count=1,
            questions=[{"question": "题", "answer": "答", "score": 100}],
            trainee_names=["丙"],
        ))
        await db_session.flush()

        res = await client.put(f"/api/v1/hr/qa-assessments/{aid}/scores", json={
            "scores": [{"employee_name": "丙", "wrong_questions": []}],
        })
        assert res.status_code == 200, res.text
        ledger_no = (await db_session.execute(
            text("SELECT employee_number FROM hr.training_ledgers "
                 "WHERE training_subject = '无工号测试' AND is_deleted = false"),
        )).scalar()
        assert ledger_no == "4001"  # 只匹配本场次部门，不串到乙部门同名

    @pytest.mark.asyncio
    async def test_sync_ledger_updates_existing_result(self, db_session, client):
        from app.modules.hr.models import QaAssessment, QaAssessmentScore

        aid = uuid4()
        db_session.add(QaAssessment(
            id=aid, subject="同步测试", department="甲部门", training_date=date(2026, 11, 11),
            full_score=100, excellent_line=90, pass_line=80, question_count=1,
            questions=[{"question": "题", "answer": "答", "score": 100}],
            trainee_names=["张三"],
        ))
        db_session.add(QaAssessmentScore(
            assessment_id=aid, employee_name="张三", employee_number="2001",
            total_score=95, grade="优秀", assessed_date=date(2026, 11, 11),
        ))
        await db_session.execute(
            text("INSERT INTO hr.training_ledgers "
                 "(id, employee_number, training_date, training_subject, assessment_result, source_type) "
                 "VALUES (gen_random_uuid(), '2001', :d, '同步测试', '80', 'qa_assessment')"),
            {"d": date(2026, 11, 11)},
        )
        await db_session.flush()

        res = await client.post(f"/api/v1/hr/qa-assessments/{aid}/sync-ledger")
        assert res.status_code == 200, res.text
        val = (await db_session.execute(
            text("SELECT assessment_result FROM hr.training_ledgers "
                 "WHERE employee_number='2001' AND training_subject='同步测试' AND is_deleted=false"),
        )).scalar()
        assert val == "95"


class TestTrainingLedgerScope:
    @pytest.mark.asyncio
    async def test_batch_scores_restricted_uses_roster_department(self, db_session):
        from app.modules.hr.api import (
            BatchScoreRequest,
            BatchScoreUpdate,
            batch_update_scores,
        )
        from app.modules.hr.models import TrainingLedger, TrainingRosterProfile

        no = f"E{uuid4().hex[:8]}"
        db_session.add(TrainingRosterProfile(
            employee_number=no, name="李四", department="甲部门",
            position="操作工", status="在职",
        ))
        ledger = TrainingLedger(
            employee_number=no, training_date=date(2026, 11, 11),
            training_subject="范围测试", assessment_result="70",
        )
        db_session.add(ledger)
        await db_session.flush()

        res = await batch_update_scores(
            BatchScoreRequest(records=[BatchScoreUpdate(id=str(ledger.id), assessment_result="88")]),
            session=db_session, hr_scope=_ctx("department", {"甲部门"}),
        )
        assert json.loads(res.body)["data"]["updated"] == 1
        await db_session.refresh(ledger)
        assert ledger.assessment_result == "88"

    def test_ledger_update_schema_rejects_extra(self):
        from pydantic import ValidationError

        from app.modules.hr.schemas import TrainingLedgerUpdate

        with pytest.raises(ValidationError):
            TrainingLedgerUpdate.model_validate({"remarks": "ok", "is_deleted": True})


class TestPermissionResourceMapping:
    def test_sop_entry_get_maps_to_training_resource(self):
        from app.modules.hr.deps import _resource_for_path
        assert _resource_for_path("/api/v1/hr/sop-training-entries/personnel", "GET") == "training"
        assert _resource_for_path("/api/v1/hr/sop-training-entries", "GET") == "training"

    def test_training_roster_get_maps_to_training_resource(self):
        from app.modules.hr.deps import _resource_for_path
        assert _resource_for_path("/api/v1/hr/employee-sync/training-roster", "GET") == "training"


class TestRosterGuards:
    @pytest.mark.asyncio
    async def test_soft_delete_missing_aborts_on_empty_remote(self, db_session):
        from app.modules.hr.employee_sync.service import EmployeeSyncService
        from app.modules.hr.models import Employee

        number = f"E{uuid4().hex[:8]}"
        emp = Employee(
            name="待删", employee_number=number, department="甲部门",
            position="操作工", status="在职", hire_date=date(2020, 1, 1),
            feishu_record_id=f"rec_{number}",
        )
        db_session.add(emp)
        await db_session.flush()

        service = EmployeeSyncService(db_session)
        deleted = await service._soft_delete_missing(set(), set())
        assert deleted == 0
        await db_session.refresh(emp)
        assert emp.is_deleted is False

    @pytest.mark.asyncio
    async def test_roster_edit_rejects_new_out_of_scope_department(self, db_session):
        from app.modules.hr.employee_sync.service import EmployeeSyncService
        from app.modules.hr.models import TrainingRosterProfile

        number = f"E{uuid4().hex[:8]}"
        db_session.add(TrainingRosterProfile(
            employee_number=number, name="王五", department="甲部门",
            position="操作工", status="在职",
        ))
        await db_session.flush()

        service = EmployeeSyncService(db_session)
        with pytest.raises(PermissionError):
            await service.update_roster_entry(
                number, {"department": "乙部门"}, scoped_departments={"甲部门"},
            )

    @pytest.mark.asyncio
    async def test_list_plans_empty_departments_is_fail_closed(self, db_session):
        from app.modules.hr.models import AnnualTrainingPlan
        from app.modules.hr.repository import AnnualTrainingPlanRepository

        dept = f"部门{uuid4().hex[:6]}"
        plan = AnnualTrainingPlan(year=2026, department=dept, status="草稿")
        db_session.add(plan)
        await db_session.flush()

        plans, total = await AnnualTrainingPlanRepository(db_session).list_plans(departments=set())
        assert total == 0
        assert all(str(p.id) != str(plan.id) for p in plans)


class TestIdCardExpiry:
    def test_stays_string_for_varchar_column(self):
        from app.modules.hr.employee_sync.mapping import convert_source_fields
        data = convert_source_fields({"身份证有效期": "2035-01-01"}, reset_missing=False)
        assert data["id_card_expiry"] == "2035-01-01"


class TestImportFixes:
    @staticmethod
    def _xlsx(headers, rows):
        from io import BytesIO

        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.append(headers)
        for r in rows:
            ws.append(r)
        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

    @pytest.mark.asyncio
    async def test_upload_trainers_keeps_existing_date_on_bad_cell(self, db_session):
        from app.modules.hr.models import HrTrainer
        from app.modules.hr.service import EmployeeService

        trainer = HrTrainer(
            name="内训师甲", department="甲部门",
            certification_date=date(2024, 1, 15),
        )
        db_session.add(trainer)
        await db_session.flush()

        content = self._xlsx(
            ["姓名", "部门", "认证日期"],
            [["内训师甲", "甲部门", "—"]],
        )
        result = await EmployeeService(db_session).upload_trainers(content)
        assert result["updated"] == 1
        await db_session.refresh(trainer)
        assert trainer.certification_date == date(2024, 1, 15)

    @pytest.mark.asyncio
    async def test_upload_sop_catalog_does_not_overwrite_other_department(self, db_session):
        from app.modules.hr.models import SopCatalog
        from app.modules.hr.service import EmployeeService

        db_session.add(SopCatalog(
            sop_number="SOP-X", file_name="文件X", department="甲部门",
        ))
        await db_session.flush()

        content = self._xlsx(
            ["SOP编号", "文件名称", "部门"],
            [["SOP-X", "文件X", "乙部门"], ["SOP-Y", "文件Y", "丙部门"]],
        )
        result = await EmployeeService(db_session).upload_sop_catalog(
            content, allowed_departments={"乙部门"},
        )
        assert result["created"] == 1
        rows = (await db_session.execute(
            text("SELECT department FROM hr.sop_catalog "
                 "WHERE file_name IN ('文件X','文件Y') AND is_deleted = false"),
        )).fetchall()
        assert {r[0] for r in rows} == {"甲部门", "乙部门"}

    @pytest.mark.asyncio
    async def test_upload_annual_plan_reupload_without_month_not_duplicated(self, db_session):
        from app.modules.hr.service import EmployeeService

        dept = f"部门{uuid4().hex[:6]}"
        content = self._xlsx(
            ["年度", "部门", "培训内容"],
            [["2026", dept, "GMP培训"]],
        )
        svc = EmployeeService(db_session)
        first = await svc.upload_annual_plan(content)
        second = await svc.upload_annual_plan(content)
        assert first["created"] == 1
        assert second["created"] == 0 and second["updated"] == 1
        count = (await db_session.execute(
            text("SELECT count(*) FROM hr.annual_training_plan_items i "
                 "JOIN hr.annual_training_plans p ON i.plan_id = p.id "
                 "WHERE p.department = :d AND p.is_deleted = false AND i.is_deleted = false"),
            {"d": dept},
        )).scalar()
        assert count == 1


class TestLedgerCreateScope:
    @pytest.mark.asyncio
    async def test_restricted_user_cannot_create_other_department_ledger(self, db_session):
        from app.core.exceptions import ForbiddenException
        from app.modules.hr.api import create_training_ledger
        from app.modules.hr.models import TrainingRosterProfile
        from app.modules.hr.schemas import TrainingLedgerCreate
        from app.modules.hr.service import TrainingLedgerService

        no = f"E{uuid4().hex[:8]}"
        db_session.add(TrainingRosterProfile(
            employee_number=no, name="赵六", department="乙部门",
            position="操作工", status="在职",
        ))
        await db_session.flush()
        payload = TrainingLedgerCreate(
            employee_number=no, training_date=date(2026, 11, 11),
            training_subject="越权测试",
        )
        with pytest.raises(ForbiddenException):
            await create_training_ledger(
                payload, service=TrainingLedgerService(db_session),
                session=db_session, hr_scope=_ctx("department", {"甲部门"}),
            )

    @pytest.mark.asyncio
    async def test_self_only_can_create_own_ledger(self, db_session):
        from app.modules.hr.api import create_training_ledger
        from app.modules.hr.models import TrainingRosterProfile
        from app.modules.hr.schemas import TrainingLedgerCreate
        from app.modules.hr.service import TrainingLedgerService

        no = "TEST001"
        db_session.add(TrainingRosterProfile(
            employee_number=no, name="测试员", department="甲部门",
            position="操作工", status="在职",
        ))
        await db_session.flush()
        payload = TrainingLedgerCreate(
            employee_number=no, training_date=date(2026, 11, 11),
            training_subject="本人台账",
        )
        res = await create_training_ledger(
            payload, service=TrainingLedgerService(db_session),
            session=db_session, hr_scope=_ctx("self_only"),
        )
        assert res.status_code == 201


class TestLeaveCountScope:
    @pytest.mark.asyncio
    async def test_uncategorized_actual_department_counted(self, db_session):
        from app.modules.hr.api import _query_leave_counts
        from app.modules.hr.models import TrainingRosterProfile

        db_session.add_all([
            TrainingRosterProfile(
                employee_number="5001", name="病假甲", department="甲部门",
                position="操作工", status="病假",
            ),
            TrainingRosterProfile(
                employee_number="5002", name="产假甲", department="未分类",
                actual_department="甲部门", position="操作工", status="产假",
            ),
        ])
        await db_session.flush()
        sick, maternity = await _query_leave_counts(db_session, "甲部门")
        assert (sick, maternity) == (1, 1)


class TestScoreParsing:
    def test_text_grades_are_counted(self):
        from app.modules.hr.api import _parse_score
        assert _parse_score("优秀") == 90
        assert _parse_score("合格") == 80
        assert _parse_score("不合格") == 0
        assert _parse_score("85") == 85


class TestOffboardingRosterStatus:
    @pytest.mark.asyncio
    async def test_offboarding_and_restore_sync_roster_status(self, db_session):
        from app.modules.hr.models import Employee, TrainingRosterProfile
        from app.modules.hr.schemas import OffboardingRecordCreate
        from app.modules.hr.service import OffboardingRecordService

        no = f"E{uuid4().hex[:8]}"
        emp = Employee(
            name="钱七", employee_number=no, department="甲部门",
            position="操作工", status="在职", hire_date=date(2020, 1, 1),
        )
        db_session.add(emp)
        await db_session.flush()
        profile = TrainingRosterProfile(
            employee_number=no, name="钱七", department="甲部门",
            position="操作工", status="在职",
        )
        db_session.add(profile)
        await db_session.flush()

        svc = OffboardingRecordService(db_session)
        rec = await svc.create_record(OffboardingRecordCreate(
            employee_id=emp.id, offboarding_date=date(2026, 11, 11),
        ))
        await db_session.refresh(profile)
        assert profile.status == "离职"

        await svc.delete_record(rec.id)
        await db_session.refresh(profile)
        assert profile.status == "在职"
