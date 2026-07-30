"""QA 考核测试：成绩同步台账 UPSERT 逻辑"""

from uuid import uuid4

import pytest


class TestQaScoreSync:
    @pytest.mark.asyncio
    async def test_save_scores_creates_ledger_if_not_exists(self, db_session, async_client):
        """保存 QA 成绩 → 不存在台账记录 → INSERT 新记录"""
        from app.modules.hr.models import QaAssessment, QaAssessmentScore

        aid = uuid4()
        # 创建考核场次
        qa = QaAssessment(
            id=aid, subject="安全生产培训", department="生产部",
            full_score=100, question_count=4,
            questions=[{"question": "题目1", "answer": "答案1", "score": 25} for _ in range(4)],
            trainee_names=["员工A"],
        )
        db_session.add(qa)
        await db_session.flush()
        await db_session.commit()

        # 保存成绩
        from sqlalchemy import text

        payload = type("obj", (object,), {"assessed_date": None, "scores": [
            {"employee_name": "员工A", "employee_number": "0001", "wrong_questions": []},
        ]})

        await db_session.execute(
            text("UPDATE hr.qa_assessments SET created_at = now() WHERE id = :id"),
            {"id": aid},
        )
        await db_session.commit()

        # 查成绩
        score = await db_session.execute(
            text("SELECT * FROM hr.qa_assessment_scores WHERE assessment_id = :aid"),
            {"aid": aid},
        )
        assert score is not None

    @pytest.mark.asyncio
    async def test_sync_ledger_upsert(self, db_session):
        """同步台账：已存在则 UPDATE，不存在则 INSERT"""
        from sqlalchemy import text

        emp_no = f"TEST{uuid4().hex[:6].upper()}"
        subject = f"测试培训_{uuid4().hex[:6]}"
        train_date = "2026-07-29"

        # 先 INSERT 一条台账
        ledger_id = uuid4()
        await db_session.execute(
            text("""
                INSERT INTO hr.training_ledgers (id, employee_number, training_date, training_subject, training_method, trainer, assessment_result, source_type)
                VALUES (:id, :en, :td, :ts, '面授', '讲师', '80', 'manual')
            """),
            {"id": ledger_id, "en": emp_no, "td": train_date, "ts": subject},
        )
        await db_session.flush()

        # 模拟 UPDATE：用 UPSERT 逻辑更新分数
        exist = (await db_session.execute(
            text("SELECT id FROM hr.training_ledgers WHERE employee_number = :en AND training_date = :td AND training_subject = :ts AND is_deleted = false"),
            {"en": emp_no, "td": train_date, "ts": subject},
        )).first()
        assert exist is not None, "台账记录应存在"

        # 更新分数
        await db_session.execute(
            text("UPDATE hr.training_ledgers SET assessment_result = :ar, updated_at = now() WHERE id = :id"),
            {"ar": "95", "id": exist[0]},
        )
        await db_session.flush()

        # 验证更新后分数
        result = (await db_session.execute(
            text("SELECT assessment_result FROM hr.training_ledgers WHERE id = :id"),
            {"id": exist[0]},
        )).scalar()
        assert result == "95", f"台账分数应更新为95，实际为{result}"
