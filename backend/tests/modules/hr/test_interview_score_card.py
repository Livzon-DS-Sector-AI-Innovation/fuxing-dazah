"""面试官评分卡测试：推送端点（发卡+记录）、提交回调（防代填/校验/upsert 评价/通知 HR）。

回调内部经 app.core.database.async_session_factory 开独立会话并真 commit，
数据需真实落库可见 → 用独立 session 建数据 + teardown 物理清理（test_user 模式）。
"""

import uuid
from unittest.mock import patch

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.interview_score_service import handle_score_submit
from app.modules.hr.models import Candidate, Interview, InterviewFeedback, JobRequirement
from tests.modules.hr.conftest import _rand, _test_session_factory


def _seed(db: AsyncSession) -> tuple[Interview, Candidate]:
    """建一条已完成的初试（含推送记录）+ 候选人，返回 (面试, 候选人)。"""
    jd = JobRequirement(id=uuid.uuid4(), position_name=_rand("岗位"), department=_rand("部门"), headcount=1)
    c = Candidate(id=uuid.uuid4(), name=_rand("候选"), status="已面试", job_requirement_id=jd.id)
    iv = Interview(
        id=uuid.uuid4(), candidate_id=c.id, job_requirement_id=jd.id,
        interview_type="初试", interviewer="钱八", status="已完成",
        score_push_open_id="ou_interviewer",
    )
    db.add_all([jd, c, iv])
    return iv, c


# ─── 推送端点：发卡 + 推送记录落面试行 ───


async def test_push_score_sends_card_and_records(client, db_session):
    jd = JobRequirement(id=uuid.uuid4(), position_name=_rand("岗位"), department=_rand("部门"), headcount=1)
    c = Candidate(id=uuid.uuid4(), name=_rand("候选"), status="已面试", job_requirement_id=jd.id)
    iv = Interview(id=uuid.uuid4(), candidate_id=c.id, interview_type="初试", interviewer="钱八", status="已完成")
    db_session.add_all([jd, c, iv])
    await db_session.flush()

    sent: dict = {}

    async def fake_send(open_id, card):
        sent["open_id"] = open_id
        sent["card"] = card
        return True

    async def fake_lookup(name):
        return "ou_interviewer"

    with (
        patch("app.modules.hr.interview_score_service._send_card", side_effect=fake_send),
        patch("app.modules.hr.interview_score_service._resolve_open_id_by_name", side_effect=fake_lookup),
    ):
        resp = await client.post(f"/api/v1/hr/interviews/{iv.id}/push-score")

    assert resp.status_code == 200
    assert sent["open_id"] == "ou_interviewer"
    # 提交按钮 value：action + interview_id + hr_name（发起人随卡下发，回调后据此通知）
    btn = sent["card"]["body"]["elements"][1]["elements"][-1]
    assert btn["value"]["action"] == "interview_score_submit"
    assert btn["value"]["interview_id"] == str(iv.id)
    assert btn["value"]["hr_name"] == "HR测试员"  # client fixture 的登录身份
    await db_session.refresh(iv)
    assert iv.score_push_open_id == "ou_interviewer"
    assert iv.score_pushed_at is not None


async def test_push_score_requires_interviewer(client, db_session):
    jd = JobRequirement(id=uuid.uuid4(), position_name=_rand("岗位"), department=_rand("部门"), headcount=1)
    c = Candidate(id=uuid.uuid4(), name=_rand("候选"), status="已面试", job_requirement_id=jd.id)
    iv = Interview(id=uuid.uuid4(), candidate_id=c.id, interview_type="初试", interviewer=None, status="已完成")
    db_session.add_all([jd, c, iv])
    await db_session.flush()

    resp = await client.post(f"/api/v1/hr/interviews/{iv.id}/push-score")
    assert resp.status_code == 400
    assert "未指定面试官" in resp.json()["message"]


# ─── 提交回调：upsert 人工评价 + 通知 HR / 防代填 ───


async def _run_callback(iv: Interview, form_value: dict, *, open_id: str = "ou_interviewer", hr_name: str = "HR测试员") -> tuple[dict, list]:
    notices: list = []

    async def fake_send(open_id_, card):
        notices.append((open_id_, card))
        return True

    async def fake_lookup(name):
        return {"钱八": "ou_interviewer", "HR测试员": "ou_hr"}.get(name)

    payload = {
        "_form_value": form_value,
        "_open_id": open_id,
        "interview_id": str(iv.id),
        "hr_name": hr_name,
    }
    with (
        patch("app.core.database.async_session_factory", _test_session_factory),
        patch("app.modules.hr.interview_score_service._send_card", side_effect=fake_send),
        patch("app.modules.hr.interview_score_service._resolve_open_id_by_name", side_effect=fake_lookup),
    ):
        result = await handle_score_submit(payload, "wx_user")
    return result, notices


async def test_submit_callback_upserts_feedback_and_notifies_hr():
    # 回调走独立会话真 commit：数据必须真实落库，teardown 物理清理
    async with _test_session_factory() as session:
        iv, c = _seed(session)
        await session.commit()
        try:
            result, notices = await _run_callback(iv, {
                "score_professional": "4", "score_communication": "5",
                "result": "通过", "comment": "基础扎实",
            })
            assert result == {"toast": {"type": "success", "content": "评分已提交，已同步人事"}}

            # 评价已写入（面试官名 + 结论 + 维度）
            fb = (await session.execute(
                InterviewFeedback.__table__.select().where(InterviewFeedback.interview_id == iv.id)
            )).mappings().one()
            assert fb["evaluator"] == "钱八"
            assert fb["result"] == "通过"
            dims = fb["dimensions"]
            assert {d["name"]: d["score"] for d in dims} == {"专业能力": 4, "沟通表达": 5}

            # HR 收到通知卡（open_id 反查），含结论与分数
            assert notices and notices[0][0] == "ou_hr"
            assert "通过" in str(notices[0][1])
        finally:
            await _cleanup(session, iv.id, c.id)


async def test_submit_callback_rejects_wrong_account():
    async with _test_session_factory() as session:
        iv, c = _seed(session)
        await session.commit()
        try:
            result, _ = await _run_callback(iv, {"result": "通过"}, open_id="ou_someone_else")
            assert result["toast"]["type"] == "error"
            assert "收到评分卡片" in result["toast"]["content"]
        finally:
            await _cleanup(session, iv.id, c.id)


async def test_submit_callback_rejects_bad_score():
    async with _test_session_factory() as session:
        iv, c = _seed(session)
        await session.commit()
        try:
            result, _ = await _run_callback(iv, {"score_professional": "9", "result": "通过"})
            assert result["toast"]["type"] == "error"
            assert "1-5" in result["toast"]["content"]
        finally:
            await _cleanup(session, iv.id, c.id)


async def _cleanup(session: AsyncSession, interview_id, candidate_id) -> None:
    """物理清理回调真 commit 的数据（含级联的 feedback / 岗位 / 候选人）。"""
    await session.execute(delete(InterviewFeedback).where(InterviewFeedback.interview_id == interview_id))
    iv = (await session.execute(
        Interview.__table__.select().where(Interview.id == interview_id)
    )).mappings().first()
    jd_id = iv["job_requirement_id"] if iv else None
    await session.execute(delete(Interview).where(Interview.id == interview_id))
    await session.execute(delete(Candidate).where(Candidate.id == candidate_id))
    if jd_id:
        await session.execute(delete(JobRequirement).where(JobRequirement.id == jd_id))
    await session.commit()
