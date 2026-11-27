"""SOP 全套材料·评估表统计预填测试

覆盖 _evaluation_stats_kwargs 换算/校验（不合格恒 0、事假自动算、比率换算）
与 materials 接口带 evaluation_stats 参数的接入行为。
"""

import pytest
from fastapi import HTTPException

from app.modules.hr.sop_training_routes import _evaluation_stats_kwargs


def _stats(actual=20, exam=20, excellent=7, qualified=13):
    return {
        "actual_count": actual,
        "exam_count": exam,
        "excellent_count": excellent,
        "qualified_count": qualified,
    }


class TestEvaluationStatsKwargs:
    def test_normal_conversion(self):
        """正常统计：事假自动补齐、比率换算、不合格恒 0"""
        kwargs = _evaluation_stats_kwargs(_stats(), expected=22, sick=1, maternity=1)
        assert kwargs["actual_count"] == 20
        assert kwargs["exam_count"] == 20
        assert kwargs["excellent_count"] == 7
        assert kwargs["qualified_count"] == 13
        assert kwargs["unqualified_count"] == 0
        # 事假 = 22 - 20 - 1 - 1 = 0
        assert kwargs["personal_leave"] == 0
        assert kwargs["participation_rate"] == "91%"
        assert kwargs["pass_rate"] == "100%"

    def test_personal_leave_counts_missing_people(self):
        """实到不足且无病产假时，差额记事假"""
        kwargs = _evaluation_stats_kwargs(_stats(actual=18, exam=18, excellent=6, qualified=12), expected=20, sick=0, maternity=0)
        assert kwargs["personal_leave"] == 2
        assert kwargs["participation_rate"] == "90%"

    def test_partial_absence_never_negative(self):
        """实到 + 病产假超过应到时事假不为负（数据自洽由前端保证，这里兜底 0）"""
        kwargs = _evaluation_stats_kwargs(_stats(), expected=21, sick=1, maternity=1)
        assert kwargs["personal_leave"] == 0

    def test_zero_exam_pass_rate_none(self):
        """参加考核 0 人时合格率留空"""
        kwargs = _evaluation_stats_kwargs(_stats(exam=0, excellent=0, qualified=0, actual=0), expected=5, sick=0, maternity=0)
        assert kwargs["pass_rate"] is None

    def test_empty_roster_returns_empty(self):
        """名单为空（expected=0）时不预填，返回空 kwargs"""
        assert _evaluation_stats_kwargs(_stats(), expected=0, sick=0, maternity=0) == {}

    def test_rejects_unequal_split(self):
        """优秀+合格 ≠ 参加考核 → 400（不合格恒 0 的硬约束）"""
        with pytest.raises(HTTPException) as exc:
            _evaluation_stats_kwargs(_stats(excellent=7, qualified=12), expected=22, sick=0, maternity=0)
        assert exc.value.status_code == 400

    def test_rejects_negative(self):
        with pytest.raises(HTTPException) as exc:
            _evaluation_stats_kwargs(_stats(actual=-1), expected=22, sick=0, maternity=0)
        assert exc.value.status_code == 400

    def test_rejects_non_numeric(self):
        with pytest.raises(HTTPException) as exc:
            _evaluation_stats_kwargs(_stats(actual="abc"), expected=22, sick=0, maternity=0)
        assert exc.value.status_code == 400

    def test_rejects_actual_over_expected(self):
        with pytest.raises(HTTPException) as exc:
            _evaluation_stats_kwargs(_stats(actual=23), expected=22, sick=0, maternity=0)
        assert exc.value.status_code == 400

    def test_rejects_exam_over_actual(self):
        with pytest.raises(HTTPException) as exc:
            _evaluation_stats_kwargs(_stats(exam=21, excellent=8, qualified=13), expected=22, sick=0, maternity=0)
        assert exc.value.status_code == 400


class TestMaterialsWithStats:
    @pytest.mark.asyncio
    async def test_materials_accepts_evaluation_stats(self, db_session, client):
        """materials 接口带合法 evaluation_stats 不报错（人员名单为空时统计被静默跳过）"""
        from app.modules.hr.models import SopTrainingRecord

        r = SopTrainingRecord(
            year="2026", file_name="统计预填测试文件", status="已提交",
            involved_departments='["甲部门"]', initiator_department="QA",
        )
        db_session.add(r)
        await db_session.flush()

        res = await client.post(
            f"/api/v1/hr/sop-training-records/{r.id}/materials",
            json={"evaluation_stats": _stats()},
        )
        assert res.status_code == 200, res.text

    @pytest.mark.asyncio
    async def test_materials_rejects_invalid_stats(self, db_session, client):
        """优秀+合格 ≠ 参加考核的统计 → 400（名单为空也先校验）"""
        from app.modules.hr.models import SopTrainingRecord

        r = SopTrainingRecord(
            year="2026", file_name="统计校验测试文件", status="已提交",
            involved_departments='["甲部门"]', initiator_department="QA",
        )
        db_session.add(r)
        await db_session.flush()

        res = await client.post(
            f"/api/v1/hr/sop-training-records/{r.id}/materials",
            json={"evaluation_stats": _stats(excellent=7, qualified=12)},
        )
        assert res.status_code == 400
        assert "优秀" in res.json()["message"]

    @pytest.mark.asyncio
    async def test_materials_without_body_still_works(self, db_session, client):
        """不带 body（旧调用方式）仍然可用"""
        from app.modules.hr.models import SopTrainingRecord

        r = SopTrainingRecord(
            year="2026", file_name="无body兼容测试文件", status="已提交",
            involved_departments='["甲部门"]', initiator_department="QA",
        )
        db_session.add(r)
        await db_session.flush()

        res = await client.post(f"/api/v1/hr/sop-training-records/{r.id}/materials")
        assert res.status_code == 200, res.text

    @pytest.mark.asyncio
    async def test_preview_record_materials(self, db_session, client):
        """单条 preview：返回应到/病产假基数（空名单时为 0）"""
        from app.modules.hr.models import SopTrainingRecord

        r = SopTrainingRecord(
            year="2026", file_name="预览测试文件", status="已提交",
            involved_departments='["甲部门"]', initiator_department="QA",
        )
        db_session.add(r)
        await db_session.flush()

        res = await client.get(f"/api/v1/hr/sop-training-records/{r.id}/materials-preview")
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert set(data.keys()) == {"expected_count", "sick_leave", "maternity_leave"}
        assert isinstance(data["expected_count"], int)

    @pytest.mark.asyncio
    async def test_preview_batch_materials_requires_ids(self, client):
        """批量 preview 缺 ids → 400"""
        res = await client.post("/api/v1/hr/sop-training-entries/materials-preview", json={})
        assert res.status_code == 400
