"""候选人胜任度多维分析报告测试。"""

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr import models as m
from app.modules.hr.service import CandidateAnalysisService

_FAKE_RESULT = {
    "dimensions": [
        {"name": "学历专业匹配度", "score": 85, "star": 4, "assessment": "专业对口"},
        {"name": "英语能力匹配度", "score": 80, "star": 4, "assessment": "六级"},
    ],
    "strengths": ["本地人稳定", "学习能力强"],
    "risks": ["药品注册全流程经验有限"],
    "total_score": 85,
    "recommend_level": "强烈推荐",
    "interview_suggestions": ["安排英语文献翻译测试"],
    "training_suggestions": ["资深人员带教3个月"],
    "summary": "综合素质优秀的候选人。",
}


async def _create_fixture(db_session):
    job = m.JobRequirement(position_name="注册专员", department="注册部", requirements="需要CET6与注册经验")
    db_session.add(job)
    await db_session.flush()
    candidate = m.Candidate(
        name="薛凯琳", job_requirement_id=job.id, education="硕士",
        school="华侨大学", major="生物与医药", work_years=2,
        current_company="某公司", phone=f"13{uuid.uuid4().hex[:9]}",
        status="面试中",
    )
    db_session.add(candidate)
    await db_session.flush()
    interview = m.Interview(
        candidate_id=candidate.id, job_requirement_id=job.id,
        interview_type="初试", transcript_text="面试逐字稿……",
    )
    db_session.add(interview)
    await db_session.flush()
    return candidate, interview


class TestCandidateAnalysis:
    async def test_generate_report_and_linkage(self, db_session: AsyncSession, monkeypatch):
        monkeypatch.setattr(
            "app.modules.hr.ai_service.AiChatService.call_json",
            AsyncMock(return_value=_FAKE_RESULT),
        )
        candidate, interview = await _create_fixture(db_session)
        service = CandidateAnalysisService(db_session)

        report = await service.generate(candidate.id, interview.id)
        assert report.total_score == 85
        assert report.recommend_level == "强烈推荐"
        assert len(report.dimensions) == 2
        # 联动1：面试建议写入面试备注
        iv = await db_session.get(m.Interview, interview.id)
        assert "英语文献翻译测试" in (iv.notes or "")
        # 联动2：候选人档案 match_report 回写面试摘要段（带定位标题头）
        c = await db_session.get(m.Candidate, candidate.id)
        assert c.match_report == "【面试胜任度摘要】\n综合素质优秀的候选人。"

    async def test_regenerate_soft_deletes_old(self, db_session: AsyncSession, monkeypatch):
        monkeypatch.setattr(
            "app.modules.hr.ai_service.AiChatService.call_json",
            AsyncMock(return_value=_FAKE_RESULT),
        )
        candidate, interview = await _create_fixture(db_session)
        service = CandidateAnalysisService(db_session)
        first = await service.generate(candidate.id, interview.id)
        second = await service.generate(candidate.id, interview.id)
        assert first.id != second.id
        reports = await service.list_by_candidate(candidate.id)
        assert len(reports) == 1
        assert reports[0].id == second.id

    async def test_generate_requires_interview_text(self, db_session: AsyncSession):
        candidate, interview = await _create_fixture(db_session)
        interview.transcript_text = None
        interview.notes = None
        await db_session.flush()
        service = CandidateAnalysisService(db_session)
        with pytest.raises(ValueError, match="面试记录"):
            await service.generate(candidate.id, interview.id)

    async def test_summary_appends_after_screening_report(self, db_session: AsyncSession, monkeypatch):
        """面试摘要追加在初筛匹配报告之后，不覆盖初筛内容。"""
        monkeypatch.setattr(
            "app.modules.hr.ai_service.AiChatService.call_json",
            AsyncMock(return_value=_FAKE_RESULT),
        )
        candidate, interview = await _create_fixture(db_session)
        candidate.match_report = "【候选人匹配度报告】应聘岗位：注册专员\n📋 推荐等级：推荐"
        await db_session.flush()

        await CandidateAnalysisService(db_session).generate(candidate.id, interview.id)
        c = await db_session.get(m.Candidate, candidate.id)
        assert c.match_report.startswith("【候选人匹配度报告】应聘岗位：注册专员")
        assert "【面试胜任度摘要】\n综合素质优秀的候选人。" in c.match_report

    async def test_regenerate_summary_not_duplicated(self, db_session: AsyncSession, monkeypatch):
        """重复生成报告：摘要段替换不叠加，match_report 只有一段摘要。"""
        monkeypatch.setattr(
            "app.modules.hr.ai_service.AiChatService.call_json",
            AsyncMock(return_value=_FAKE_RESULT),
        )
        candidate, interview = await _create_fixture(db_session)
        service = CandidateAnalysisService(db_session)
        await service.generate(candidate.id, interview.id)
        await service.generate(candidate.id, interview.id)

        c = await db_session.get(m.Candidate, candidate.id)
        assert c.match_report.count("【面试胜任度摘要】") == 1
        assert c.match_report == "【面试胜任度摘要】\n综合素质优秀的候选人。"

    async def test_rescreen_keeps_interview_summary(self, db_session: AsyncSession):
        """反向：已生成面试摘要的候选人再跑 AI 初筛，摘要段保留拼接。"""
        from app.modules.hr.resume_screening_service import _merge_match_report

        merged = _merge_match_report(
            "【面试胜任度摘要】\n综合素质优秀，建议推进复试。",
            "【候选人匹配度报告】应聘岗位：注册专员",
        )
        assert merged.startswith("【候选人匹配度报告】应聘岗位：注册专员")
        assert "【面试胜任度摘要】\n综合素质优秀，建议推进复试。" in merged
        # 无摘要段的（未生成过面试报告）保持原样整篇替换
        assert _merge_match_report(
            None, "【候选人匹配度报告】新报告",
        ) == "【候选人匹配度报告】新报告"
