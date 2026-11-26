"""SOP 登记的考核方式（阅读并理解/问答/笔试）与材料包组卷口径测试。

组卷口径：通知+签到+评估为固定三件；考核记录按考核方式加——
阅读并理解不加、问答→问答实操记录表、笔试→试卷（题库按文件编号匹配，有题才含）；
不再生成培训登记表。考核方式未填时按培训方式取默认（R=阅读并理解，T=问答）。
"""

import io
import json
import zipfile
from uuid import uuid4

import pytest
from sqlalchemy import text


def _rand() -> str:
    return uuid4().hex[:8]


def _zip_names(content: bytes) -> set[str]:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        return set(zf.namelist())


class TestEffectiveAssessment:
    def test_explicit_value_wins(self):
        from app.modules.hr.sop_training_routes import _effective_assessment

        assert _effective_assessment("笔试", "R") == "笔试"

    def test_default_by_method(self):
        from app.modules.hr.sop_training_routes import _effective_assessment

        assert _effective_assessment(None, "R") == "阅读并理解"
        assert _effective_assessment(None, "T") == "问答"

    def test_no_method_falls_back_to_reading(self):
        from app.modules.hr.sop_training_routes import _effective_assessment

        assert _effective_assessment(None, None) == "阅读并理解"


class TestAssessmentMethodCrud:
    @pytest.mark.asyncio
    async def test_create_persists_and_validates(self, db_session, client):
        fname = f"考核方式记录{_rand()}"
        res = await client.post("/api/v1/hr/sop-training-records", json={
            "year": "2026", "file_name": fname,
            "method": "T", "assessment_method": "笔试",
            "involved_departments": ["甲部门"], "initiator_department": "甲部门",
        })
        assert res.status_code == 201, res.text
        rid = res.json()["data"]["id"]
        row = (await db_session.execute(
            text("SELECT assessment_method FROM hr.sop_training_records WHERE id = :rid"),
            {"rid": rid},
        )).scalar()
        assert row == "笔试"

        # 非法值 400
        res_bad = await client.post("/api/v1/hr/sop-training-records", json={
            "year": "2026", "file_name": f"非法考核{_rand()}", "assessment_method": "面试",
        })
        assert res_bad.status_code == 400

    @pytest.mark.asyncio
    async def test_update_changes_and_clears(self, db_session, client):
        fname = f"考核修改记录{_rand()}"
        res = await client.post("/api/v1/hr/sop-training-records", json={
            "year": "2026", "file_name": fname, "method": "R",
        })
        assert res.status_code == 201, res.text
        rid = res.json()["data"]["id"]

        res2 = await client.put(f"/api/v1/hr/sop-training-records/{rid}", json={"assessment_method": "问答"})
        assert res2.status_code == 200, res2.text
        val = (await db_session.execute(
            text("SELECT assessment_method FROM hr.sop_training_records WHERE id = :rid"),
            {"rid": rid},
        )).scalar()
        assert val == "问答"

        # 显式置空允许（空=按培训方式取默认）
        res3 = await client.put(f"/api/v1/hr/sop-training-records/{rid}", json={"assessment_method": None})
        assert res3.status_code == 200, res3.text
        val = (await db_session.execute(
            text("SELECT assessment_method FROM hr.sop_training_records WHERE id = :rid"),
            {"rid": rid},
        )).scalar()
        assert val is None


async def _insert_record(db_session, *, method: str | None, assessment: str | None, file_no: str | None = None):
    from app.modules.hr.models import SopTrainingRecord

    rec = SopTrainingRecord(
        year="2026", file_name=f"组卷{_rand()}", file_no=file_no,
        method=method, assessment_method=assessment,
        involved_departments=json.dumps(["甲部门"]), status="已提交",
        initiator_department="甲部门",
    )
    db_session.add(rec)
    await db_session.flush()
    return rec


class TestRecordMaterialsComposition:
    @pytest.mark.asyncio
    async def test_reading_understanding_three_docs_only(self, db_session, client):
        rec = await _insert_record(db_session, method="R", assessment="阅读并理解")
        res = await client.post(f"/api/v1/hr/sop-training-records/{rec.id}/materials")
        assert res.status_code == 200, res.text
        names = _zip_names(res.content)
        assert names == {"培训通知.docx", "培训签到表.docx", "培训效果评估表.docx"}

    @pytest.mark.asyncio
    async def test_empty_assessment_defaults_by_method(self, db_session, client):
        # 历史数据：考核方式为空、培训方式 T → 默认问答 → 打包问答实操记录表
        rec = await _insert_record(db_session, method="T", assessment=None)
        res = await client.post(f"/api/v1/hr/sop-training-records/{rec.id}/materials")
        assert res.status_code == 200, res.text
        names = _zip_names(res.content)
        assert "问答实操记录表.docx" in names
        assert "培训登记表.docx" not in names
        assert "培训试卷.docx" not in names

    @pytest.mark.asyncio
    async def test_written_exam_packs_paper_when_questions_exist(self, db_session, client):
        from app.modules.hr.models import QuestionBank

        file_no = f"SOP-EXAM-{_rand()}"
        db_session.add(QuestionBank(
            file_no=file_no, question=f"{file_no} 的适用范围是什么？", answer="见文件第 1 章",
            score=10, source="手工录入",
        ))
        await db_session.flush()
        rec = await _insert_record(db_session, method="T", assessment="笔试", file_no=file_no)
        res = await client.post(f"/api/v1/hr/sop-training-records/{rec.id}/materials")
        assert res.status_code == 200, res.text
        assert "培训试卷.docx" in _zip_names(res.content)

    @pytest.mark.asyncio
    async def test_written_exam_without_questions_skips_paper(self, db_session, client):
        rec = await _insert_record(db_session, method="T", assessment="笔试", file_no=f"SOP-NONE-{_rand()}")
        res = await client.post(f"/api/v1/hr/sop-training-records/{rec.id}/materials")
        assert res.status_code == 200, res.text
        names = _zip_names(res.content)
        assert "培训试卷.docx" not in names
        assert names == {"培训通知.docx", "培训签到表.docx", "培训效果评估表.docx"}


class TestBatchMaterialsComposition:
    @pytest.mark.asyncio
    async def test_batch_follows_record_assessment(self, db_session, client):
        from app.modules.hr.models import SopTrainingEntry

        rec = await _insert_record(db_session, method="T", assessment="问答")
        entry = SopTrainingEntry(
            record_id=str(rec.id), department="甲部门",
            personnel=json.dumps([{"name": "张三", "employee_number": f"T{_rand()}"}]),
        )
        db_session.add(entry)
        await db_session.flush()

        res = await client.post(
            "/api/v1/hr/sop-training-entries/batch-materials",
            json={"ids": [str(entry.id)]},
        )
        assert res.status_code == 200, res.text
        names = _zip_names(res.content)
        assert "问答实操记录表.docx" in names
        assert "培训登记表.docx" not in names
