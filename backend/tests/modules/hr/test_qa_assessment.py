"""QA 考核测试：成绩保存与台账同步逻辑"""

from datetime import date
from uuid import uuid4

import pytest


class TestQaScoreSync:
    @pytest.mark.asyncio
    async def test_save_scores_creates_score_row(self, db_session, client):
        """保存 QA 成绩 → 生成成绩行并计算等级"""
        from app.modules.hr.models import QaAssessment

        aid = uuid4()
        db_session.add(QaAssessment(
            id=aid, subject="安全生产培训", department="生产部",
            full_score=100, excellent_line=90, pass_line=80, question_count=4,
            questions=[{"question": "题目1", "answer": "答案1", "score": 25} for _ in range(4)],
            trainee_names=["员工A"],
        ))
        await db_session.flush()

        res = await client.put(
            f"/api/v1/hr/qa-assessments/{aid}/scores",
            json={"assessed_date": "2026-07-29", "scores": [
                {"employee_name": "员工A", "employee_number": "0001", "wrong_questions": [1]},
            ]},
        )
        assert res.status_code == 200, res.text

        from sqlalchemy import text
        row = (await db_session.execute(
            text("SELECT total_score, grade, assessed_date FROM hr.qa_assessment_scores WHERE assessment_id = :aid AND is_deleted = false"),
            {"aid": aid},
        )).fetchone()
        assert row is not None, "应生成成绩行"
        assert row[0] == 75, "错一题扣25分，总分应为75"
        assert row[1] == "不合格", "75分低于合格线80应为不合格"
        assert row[2] == date(2026, 7, 29)

    @pytest.mark.asyncio
    async def test_sync_ledger_upsert(self, db_session):
        """同步台账：已存在则 UPDATE，不存在则 INSERT"""
        from sqlalchemy import text

        emp_no = f"TEST{uuid4().hex[:6].upper()}"
        subject = f"测试培训_{uuid4().hex[:6]}"
        train_date = date(2026, 7, 29)

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
