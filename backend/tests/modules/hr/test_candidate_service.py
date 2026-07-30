"""候选人服务测试：push/decide 状态校验 + onboard 入职"""

from uuid import uuid4

import pytest

from app.modules.hr.repository import CandidateRepository
from app.modules.hr.service import CandidateReviewService, CandidateService


class TestCandidatePushReview:
    @pytest.mark.asyncio
    async def test_push_rejects_employed_candidate(self, db_session):
        """已录用候选人不可推送审核"""
        from app.modules.hr.models import Candidate, JobRequirement

        jd = JobRequirement(id=uuid4(), position_name="测试", department="测试", headcount=1, owner="审核人")
        db_session.add(jd)
        await db_session.flush()

        c = Candidate(id=uuid4(), name="测试已录用", status="已录用", job_requirement_id=jd.id)
        db_session.add(c)
        await db_session.flush()

        service = CandidateReviewService(db_session)
        with pytest.raises(ValueError) as exc:
            await service.push(c.id, pushed_by="HR")
        assert "已录用" in str(exc.value)

    @pytest.mark.asyncio
    async def test_push_rejects_onboarded_candidate(self, db_session):
        """已入职候选人不可推送审核"""
        from app.modules.hr.models import Candidate, JobRequirement

        jd = JobRequirement(id=uuid4(), position_name="测试", department="测试", headcount=1, owner="审核人")
        db_session.add(jd)
        await db_session.flush()

        c = Candidate(id=uuid4(), name="测试已入职", status="已入职", job_requirement_id=jd.id)
        db_session.add(c)
        await db_session.flush()

        service = CandidateReviewService(db_session)
        with pytest.raises(ValueError) as exc:
            await service.push(c.id, pushed_by="HR")
        assert "已入职" in str(exc.value)

    @pytest.mark.asyncio
    async def test_push_rejects_rejected_candidate(self, db_session):
        """已拒绝候选人不可推送审核"""
        from app.modules.hr.models import Candidate, JobRequirement

        jd = JobRequirement(id=uuid4(), position_name="测试", department="测试", headcount=1, owner="审核人")
        db_session.add(jd)
        await db_session.flush()

        c = Candidate(id=uuid4(), name="测试已拒绝", status="已拒绝", job_requirement_id=jd.id)
        db_session.add(c)
        await db_session.flush()

        service = CandidateReviewService(db_session)
        with pytest.raises(ValueError) as exc:
            await service.push(c.id, pushed_by="HR")
        assert "已拒绝" in str(exc.value)


class TestCandidateDecideReview:
    @pytest.mark.asyncio
    async def test_decide_checks_candidate_status_consistency(self, db_session):
        """审核决定时校验候选人仍在审核流程中"""
        from app.modules.hr.models import Candidate, CandidateReview, JobRequirement

        jd = JobRequirement(
            id=uuid4(), position_name="测试岗位", department="测试部门",
            headcount=1, owner="审核人",
        )
        db_session.add(jd)
        await db_session.flush()

        c = Candidate(
            id=uuid4(), name="测试候选人", status="待部门审核",
            job_requirement_id=jd.id,
        )
        db_session.add(c)
        await db_session.flush()

        rv = CandidateReview(
            id=uuid4(), candidate_id=c.id, job_requirement_id=jd.id,
            pushed_by="HR", reviewer="审核人", status="待审核",
        )
        db_session.add(rv)
        await db_session.flush()

        # 手动改成已录用，模拟并发冲突
        c2 = await db_session.get(Candidate, c.id)
        c2.status = "已录用"
        await db_session.flush()

        service = CandidateReviewService(db_session)
        with pytest.raises(ValueError) as exc:
            await service.decide(rv.id, decision="已同意")
        assert "已录用" in str(exc.value)


class TestCandidateOnboard:
    @pytest.mark.asyncio
    async def test_onboard_rejects_non_employed(self, db_session):
        """非已录用状态不可入职"""
        from app.modules.hr.models import Candidate

        c = Candidate(id=uuid4(), name="测试", status="面试中")
        db_session.add(c)
        await db_session.flush()

        service = CandidateService(db_session)
        with pytest.raises(ValueError) as exc:
            await service.onboard(c.id)
        assert "已录用" in str(exc.value)

    @pytest.mark.asyncio
    async def test_onboard_generates_employee_number(self, db_session):
        """入职生成 ZP 前缀工号"""
        from app.modules.hr.models import Candidate, JobRequirement

        jd = JobRequirement(id=uuid4(), position_name="测试", department="测试", headcount=1)
        db_session.add(jd)
        await db_session.flush()

        c = Candidate(
            id=uuid4(), name="测试入职", status="已录用",
            department="技术部", position="工程师",
            job_requirement_id=jd.id,
        )
        db_session.add(c)
        await db_session.flush()

        service = CandidateService(db_session)
        _, onboarding, emp_no = await service.onboard(c.id)

        assert emp_no.startswith("ZP")
        assert len(emp_no) == 12  # ZP(2) + YYMMDD(6) + randomHex(4)
        assert onboarding.employee_number == emp_no
        assert onboarding.department == "技术部"
        assert onboarding.position == "工程师"
        assert onboarding.source == "recruitment"
