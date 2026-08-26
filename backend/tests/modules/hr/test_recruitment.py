"""招聘模块测试：岗位需求 / 候选人 / 面试 / AI 评估 / 推送审核 / 入职"""

import uuid
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.models import (
    Candidate,
    CandidateAiEvaluation,
    CandidateReview,
    CandidateStatusLog,
    Interview,
    JobRequirement,
    OnboardingRecord,
)
from tests.modules.hr.conftest import _rand


# ═══════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════

async def _create_job(db: AsyncSession, **kw) -> JobRequirement:
    j = JobRequirement(
        position_name=kw.get("position_name", f"测试岗位-{_rand()}"),
        department=kw.get("department", f"测试部门-{_rand()}"),
        headcount=kw.get("headcount", 3),
        requirements=kw.get("requirements", "本科以上，3年经验"),
        owner=kw.get("owner", "张三"),
    )
    db.add(j)
    await db.flush()
    await db.refresh(j)
    return j


async def _create_candidate(db: AsyncSession, job_id: uuid.UUID, **kw) -> Candidate:
    c = Candidate(
        name=kw.get("name", f"候选人-{_rand()}"),
        phone=kw.get("phone", "13800001111"),
        email=kw.get("email", f"{_rand()}@test.com"),
        position=kw.get("position", "QA工程师"),
        department=kw.get("department", "质量部"),
        school=kw.get("school", "福州大学"),
        education=kw.get("education", "本科"),
        major=kw.get("major", "药学"),
        status=kw.get("status", "待筛选"),
        job_requirement_id=job_id,
        candidate_type="职能",
    )
    db.add(c)
    await db.flush()
    await db.refresh(c)
    return c


# ═══════════════════════════════════════════════════
# 岗位需求
# ═══════════════════════════════════════════════════

class TestJobRequirement:
    async def test_create(self, client: AsyncClient):
        resp = await client.post("/api/v1/hr/job-requirements", json={
            "position_name": "QA工程师",
            "department": "质量部",
            "headcount": 2,
            "requirements": "3年GMP经验",
        })
        assert resp.status_code == 201
        assert resp.json()["data"]["position_name"] == "QA工程师"

    async def test_list_and_update(self, client: AsyncClient):
        # create
        resp = await client.post("/api/v1/hr/job-requirements", json={
            "position_name": "生产主管", "department": "生产部", "headcount": 1,
        })
        jid = resp.json()["data"]["id"]

        # list
        resp = await client.get("/api/v1/hr/job-requirements")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) >= 1

        # update
        resp = await client.put(f"/api/v1/hr/job-requirements/{jid}", json={"headcount": 5})
        assert resp.json()["data"]["headcount"] == 5

    async def test_delete(self, client: AsyncClient):
        resp = await client.post("/api/v1/hr/job-requirements", json={
            "position_name": "临时岗位", "department": "临时部门",
        })
        jid = resp.json()["data"]["id"]
        resp = await client.delete(f"/api/v1/hr/job-requirements/{jid}")
        assert resp.status_code == 200

    async def test_comparison_empty(self, client: AsyncClient):
        resp = await client.post("/api/v1/hr/job-requirements", json={
            "position_name": "对比测试", "department": "对比部门",
        })
        jid = resp.json()["data"]["id"]
        resp = await client.get(f"/api/v1/hr/job-requirements/{jid}/candidates/comparison")
        assert resp.status_code == 200
        assert resp.json()["data"] == []


# ═══════════════════════════════════════════════════
# 候选人 CRUD + 状态流转
# ═══════════════════════════════════════════════════

class TestCandidate:
    async def test_create_and_get(self, client: AsyncClient, db_session: AsyncSession):
        job = await _create_job(db_session)
        resp = await client.post("/api/v1/hr/candidates", json={
            "name": "张三", "phone": "13800001111", "position": "QA工程师",
            "department": "质量部", "job_requirement_id": str(job.id),
        })
        assert resp.status_code == 201
        cid = resp.json()["data"]["id"]

        resp = await client.get(f"/api/v1/hr/candidates/{cid}")
        assert resp.json()["data"]["name"] == "张三"

    async def test_list_by_job(self, client: AsyncClient, db_session: AsyncSession):
        job = await _create_job(db_session)
        await _create_candidate(db_session, job.id, name="Alice")
        await _create_candidate(db_session, job.id, name="Bob")

        resp = await client.get(f"/api/v1/hr/candidates?job_requirement_id={job.id}")
        assert len(resp.json()["data"]) >= 2

    async def test_update_and_delete(self, client: AsyncClient, db_session: AsyncSession):
        job = await _create_job(db_session)
        c = await _create_candidate(db_session, job.id)

        resp = await client.put(f"/api/v1/hr/candidates/{c.id}", json={"recommendation_level": "强烈推荐"})
        assert resp.json()["data"]["recommendation_level"] == "强烈推荐"

        resp = await client.delete(f"/api/v1/hr/candidates/{c.id}")
        assert resp.status_code == 200

    async def test_status_transition_valid(self, client: AsyncClient, db_session: AsyncSession):
        job = await _create_job(db_session)
        c = await _create_candidate(db_session, job.id, status="待筛选")

        # 合法流转
        resp = await client.put(f"/api/v1/hr/candidates/{c.id}/status", json={"status": "已筛选"})
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "已筛选"

        # 非法流转：跳级
        resp = await client.put(f"/api/v1/hr/candidates/{c.id}/status", json={"status": "已录用"})
        assert resp.status_code == 400

    async def test_status_logs(self, client: AsyncClient, db_session: AsyncSession):
        job = await _create_job(db_session)
        c = await _create_candidate(db_session, job.id, status="待筛选")
        await client.put(f"/api/v1/hr/candidates/{c.id}/status", json={"status": "已筛选"})

        resp = await client.get(f"/api/v1/hr/candidates/{c.id}/status-logs")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) >= 1  # 至少有一条流转记录

    async def test_pending_review_list(self, client: AsyncClient, db_session: AsyncSession):
        job = await _create_job(db_session, owner="李四")
        c = await _create_candidate(db_session, job.id, status="待部门审核")
        # 创建审核记录
        db_session.add(CandidateReview(
            candidate_id=c.id, job_requirement_id=job.id,
            pushed_by="HR", reviewer="李四", status="待审核",
        ))
        await db_session.flush()

        resp = await client.get("/api/v1/hr/candidates/pending-review")
        assert resp.status_code == 200
        assert any(r["candidate"]["id"] == str(c.id) for r in resp.json()["data"])

    async def test_push_review_missing_owner(self, client: AsyncClient, db_session: AsyncSession):
        """岗位未设置负责人时推送应报错"""
        job = await _create_job(db_session, owner=None)
        c = await _create_candidate(db_session, job.id, status="已筛选")

        resp = await client.post(f"/api/v1/hr/candidates/{c.id}/push-review", json={
            "pushed_by": "HR", "push_note": "看看",
        })
        assert resp.status_code == 400

    async def test_decide_review(self, client: AsyncClient, db_session: AsyncSession):
        job = await _create_job(db_session, owner="王五")
        c = await _create_candidate(db_session, job.id, status="待部门审核")
        rv = CandidateReview(
            candidate_id=c.id, job_requirement_id=job.id,
            pushed_by="HR", reviewer="王五", status="待审核",
        )
        db_session.add(rv)
        await db_session.flush()

        resp = await client.post(f"/api/v1/hr/candidates/{c.id}/decide-review", json={
            "review_id": str(rv.id), "decision": "已同意",
        })
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "已同意"


# ═══════════════════════════════════════════════════
# 面试管理 + AI 评估
# ═══════════════════════════════════════════════════

class TestInterview:
    async def test_create_and_list(self, client: AsyncClient, db_session: AsyncSession):
        job = await _create_job(db_session)
        c = await _create_candidate(db_session, job.id)

        resp = await client.post("/api/v1/hr/interviews", json={
            "candidate_id": str(c.id), "job_requirement_id": str(job.id),
            "interview_type": "初试", "interviewer": "赵六",
        })
        assert resp.status_code == 201
        iv_id = resp.json()["data"]["id"]

        resp = await client.get(f"/api/v1/hr/candidates/{c.id}/interviews")
        assert len(resp.json()["data"]) == 1

    async def test_update_transcript(self, client: AsyncClient, db_session: AsyncSession):
        job = await _create_job(db_session)
        c = await _create_candidate(db_session, job.id)

        resp = await client.post("/api/v1/hr/interviews", json={
            "candidate_id": str(c.id), "interview_type": "复试",
        })
        iv_id = resp.json()["data"]["id"]

        resp = await client.put(f"/api/v1/hr/interviews/{iv_id}", json={
            "transcript_text": "面试官：请自我介绍。候选人：我叫张三...",
        })
        assert resp.status_code == 200

    async def test_delete(self, client: AsyncClient, db_session: AsyncSession):
        job = await _create_job(db_session)
        c = await _create_candidate(db_session, job.id)
        resp = await client.post("/api/v1/hr/interviews", json={"candidate_id": str(c.id)})
        iv_id = resp.json()["data"]["id"]

        resp = await client.delete(f"/api/v1/hr/interviews/{iv_id}")
        assert resp.status_code == 200

    async def test_evaluate_without_transcript(self, client: AsyncClient, db_session: AsyncSession):
        """无逐字稿时评估应报错"""
        job = await _create_job(db_session)
        c = await _create_candidate(db_session, job.id)
        resp = await client.post("/api/v1/hr/interviews", json={"candidate_id": str(c.id)})
        iv_id = resp.json()["data"]["id"]

        resp = await client.post(f"/api/v1/hr/interviews/{iv_id}/evaluate")
        assert resp.status_code == 400  # 无逐字稿


# ═══════════════════════════════════════════════════
# 一键入职
# ═══════════════════════════════════════════════════

class TestOnboard:
    async def test_onboard_success(self, client: AsyncClient, db_session: AsyncSession):
        job = await _create_job(db_session)
        c = await _create_candidate(db_session, job.id, status="待入职审批",
                                     offer_status="已接受", phone="13900001111")

        resp = await client.post(f"/api/v1/hr/candidates/{c.id}/onboard")
        assert resp.status_code == 200
        emp_no = resp.json()["data"]["employee_number"]
        assert emp_no.startswith("ZP")

        # 检查入职记录已创建
        from sqlalchemy import select
        r = await db_session.execute(select(OnboardingRecord).where(
            OnboardingRecord.employee_number == emp_no))
        assert r.scalar_one_or_none() is not None

    async def test_onboard_wrong_status(self, client: AsyncClient, db_session: AsyncSession):
        """状态非「已录用」时应拒绝入职"""
        job = await _create_job(db_session)
        c = await _create_candidate(db_session, job.id, status="面试中")

        resp = await client.post(f"/api/v1/hr/candidates/{c.id}/onboard")
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════
# 数据管理
# ═══════════════════════════════════════════════════

class TestDataManagement:
    async def test_list_tables(self, client: AsyncClient):
        resp = await client.get("/api/v1/hr/data-management/tables")
        assert resp.status_code == 200
        tables = resp.json()["data"]
        assert len(tables) > 0
        # 验证基础表存在
        table_names = [t["table"] for t in tables]
        assert "employees" in table_names
        assert "candidates" in table_names
        assert "job_requirements" in table_names

    async def test_list_excludes_positions(self, client: AsyncClient):
        resp = await client.get("/api/v1/hr/data-management/tables")
        table_names = [t["table"] for t in resp.json()["data"]]
        assert "positions" not in table_names
        assert "alembic_version" not in table_names

    async def test_clear_protected_table(self, client: AsyncClient):
        """尝试清空受保护的表应被拒绝"""
        resp = await client.post("/api/v1/hr/data-management/clear", json=["positions"])
        assert resp.status_code == 400

    async def test_clear_and_recount(self, client: AsyncClient, db_session: AsyncSession):
        """清空 candidates 表后行数归零"""
        job = await _create_job(db_session)
        await _create_candidate(db_session, job.id, name="测试数据")

        # 确认有数据
        resp = await client.get("/api/v1/hr/data-management/tables")
        cand_item = next(t for t in resp.json()["data"] if t["table"] == "candidates")
        assert cand_item["count"] >= 1

        # 清空
        resp = await client.post("/api/v1/hr/data-management/clear", json=["candidates"])
        assert resp.status_code == 200

        # 验证归零
        resp = await client.get("/api/v1/hr/data-management/tables")
        cand_item = next(t for t in resp.json()["data"] if t["table"] == "candidates")
        assert cand_item["count"] == 0


# ═══════════════════════════════════════════════════
# 候选人对比
# ═══════════════════════════════════════════════════

class TestComparison:
    async def test_comparison_with_evaluations(self, client: AsyncClient, db_session: AsyncSession):
        """有AI评估的候选人对比应返回评分数据"""
        job = await _create_job(db_session)
        c1 = await _create_candidate(db_session, job.id, name="张三", status="已面试")
        c2 = await _create_candidate(db_session, job.id, name="李四", status="已面试")

        # 添加 AI 评估
        for c, score in [(c1, 8.5), (c2, 7.0)]:
            db_session.add(CandidateAiEvaluation(
                candidate_id=c.id, job_requirement_id=job.id,
                overall_score=score, jd_match_score=score,
            ))
        await db_session.flush()

        resp = await client.get(f"/api/v1/hr/job-requirements/{job.id}/candidates/comparison")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 2
        # 按评分降序排列
        assert data[0]["evaluation"]["overall_score"] >= data[1]["evaluation"]["overall_score"]


# ═══════════════════════════════════════════════════
# 招聘统计
# ═══════════════════════════════════════════════════

class TestRecruitmentStats:
    async def test_stats(self, client: AsyncClient, db_session: AsyncSession):
        job = await _create_job(db_session)
        await _create_candidate(db_session, job.id, status="待筛选")

        resp = await client.get("/api/v1/hr/recruitment/stats")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total_candidates"] >= 1
        assert len(data["funnel"]) == 10  # 10 种状态（含待入职审批/已入职）
