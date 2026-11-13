"""面试排期增强回归测试。

对应改动：起止钟点字段、同面试官同日时段冲突检测（409 + force_conflict）、
日历创建成功置「已安排」、全部轮次完成后候选人自动推进「已面试」。
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.models import Candidate, CandidateStatusLog, JobRequirement
from tests.modules.hr.conftest import _rand


def _mk_jd(db: AsyncSession) -> JobRequirement:
    jd = JobRequirement(
        id=uuid4(),
        position_name=_rand("岗位"), department=_rand("部门"),
        headcount=2, owner="岗位负责人", duties="岗位职责说明",
    )
    db.add(jd)
    return jd


def _mk_candidate(db: AsyncSession, jd: JobRequirement, *, status: str = "面试中") -> Candidate:
    c = Candidate(id=uuid4(), name=_rand("候选"), status=status, job_requirement_id=jd.id)
    db.add(c)
    return c


async def _create_iv(
    client: AsyncClient, candidate_id, *,
    interviewer: str = "赵六", day: str = "2026-12-01",
    start: str = "10:00", end: str = "11:00", **extra,
):
    payload = {
        "candidate_id": str(candidate_id),
        "interview_type": "初试",
        "interviewer": interviewer,
        "interview_date": day,
        "start_time": start,
        "end_time": end,
        **extra,
    }
    return await client.post("/api/v1/hr/interviews", json=payload)


# ─── 时间粒度：字段存取与起止校验 ───


async def test_create_with_time_roundtrip(client: AsyncClient, db_session: AsyncSession):
    jd = _mk_jd(db_session)
    c = _mk_candidate(db_session, jd)
    await db_session.flush()

    resp = await _create_iv(client, c.id, start="14:30", end="15:30")
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["start_time"] == "14:30:00"
    assert data["end_time"] == "15:30:00"
    assert data["interview_date"] == "2026-12-01"


async def test_end_not_after_start_rejected(client: AsyncClient, db_session: AsyncSession):
    jd = _mk_jd(db_session)
    c = _mk_candidate(db_session, jd)
    await db_session.flush()

    resp = await _create_iv(client, c.id, start="10:00", end="10:00")
    assert resp.status_code == 400
    assert "结束时间" in resp.json()["message"]


# ─── 冲突检测：同面试官同日时段重叠 ───


async def test_conflict_rejected_then_force_ok(client: AsyncClient, db_session: AsyncSession):
    jd = _mk_jd(db_session)
    c = _mk_candidate(db_session, jd)
    await db_session.flush()

    assert (await _create_iv(client, c.id, interviewer="钱七")).status_code == 201

    # 同面试官时段重叠 → 409，报文含冲突详情
    resp = await _create_iv(client, c.id, interviewer="钱七", start="10:30", end="11:30")
    assert resp.status_code == 409
    assert "冲突" in resp.json()["message"]

    # 二次确认后 force_conflict 强制保存
    resp = await _create_iv(client, c.id, interviewer="钱七", start="10:30", end="11:30", force_conflict=True)
    assert resp.status_code == 201


async def test_conflict_scoped_to_interviewer_and_time(client: AsyncClient, db_session: AsyncSession):
    jd = _mk_jd(db_session)
    c = _mk_candidate(db_session, jd)
    await db_session.flush()

    assert (await _create_iv(client, c.id, interviewer="钱七")).status_code == 201
    # 不同面试官同时段不冲突
    assert (await _create_iv(client, c.id, interviewer="孙八")).status_code == 201
    # 同面试官不重叠时段（端点相接不算冲突）
    assert (await _create_iv(client, c.id, interviewer="钱七", start="11:00", end="12:00")).status_code == 201
    # 同面试官不同日期
    assert (await _create_iv(client, c.id, interviewer="钱七", day="2026-12-02")).status_code == 201


async def test_conflict_ignores_cancelled(client: AsyncClient, db_session: AsyncSession):
    jd = _mk_jd(db_session)
    c = _mk_candidate(db_session, jd)
    await db_session.flush()

    r1 = await _create_iv(client, c.id, interviewer="钱七")
    iv_id = r1.json()["data"]["id"]
    assert (await client.delete(f"/api/v1/hr/interviews/{iv_id}")).status_code == 200

    # 已取消的面试不占时段
    resp = await _create_iv(client, c.id, interviewer="钱七", start="10:30", end="11:30")
    assert resp.status_code == 201


# ─── 日历联动：成功置已安排、失败可提示 ───


async def test_calendar_success_sets_scheduled(client: AsyncClient, db_session: AsyncSession):
    jd = _mk_jd(db_session)
    c = _mk_candidate(db_session, jd)
    await db_session.flush()

    with patch(
        "app.modules.hr.feishu_calendar.FeishuCalendarService.create_interview_event",
        new=AsyncMock(return_value="evt_test_123"),
    ):
        resp = await _create_iv(client, c.id, interviewer="钱七", create_calendar_event=True)
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["calendar_event_id"] == "evt_test_123"
    assert data["status"] == "已安排"
    assert data["calendar_sync_error"] is None


async def test_calendar_failure_keeps_pending_with_hint(client: AsyncClient, db_session: AsyncSession):
    jd = _mk_jd(db_session)
    c = _mk_candidate(db_session, jd)
    await db_session.flush()

    with patch(
        "app.modules.hr.feishu_calendar.FeishuCalendarService.create_interview_event",
        new=AsyncMock(side_effect=RuntimeError("飞书不可用")),
    ):
        resp = await _create_iv(client, c.id, interviewer="钱七", create_calendar_event=True)
    assert resp.status_code == 201  # 面试保存不被日历故障阻塞
    data = resp.json()["data"]
    assert data["calendar_event_id"] is None
    assert data["status"] == "待安排"
    assert "飞书日程创建失败" in data["calendar_sync_error"]


# ─── 状态联动：全部轮次完成 → 候选人自动「已面试」 ───


async def test_last_completion_auto_transitions_candidate(client: AsyncClient, db_session: AsyncSession):
    jd = _mk_jd(db_session)
    c = _mk_candidate(db_session, jd, status="面试中")
    await db_session.flush()

    iv1 = (await _create_iv(client, c.id, interviewer="钱七", start="09:00", end="10:00")).json()["data"]["id"]
    iv2 = (await _create_iv(client, c.id, interviewer="孙八", interview_type="复试")).json()["data"]["id"]

    # 完成第一轮：还有复试未完成，候选人保持「面试中」
    resp = await client.put(f"/api/v1/hr/interviews/{iv1}", json={"status": "已完成"})
    assert resp.status_code == 200
    await db_session.flush()
    logs = (await db_session.execute(
        select(CandidateStatusLog).where(CandidateStatusLog.candidate_id == c.id)
    )).scalars().all()
    assert not any(log.to_status == "已面试" for log in logs)

    # 完成最后一轮：候选人自动推进「已面试」并留状态日志
    resp = await client.put(f"/api/v1/hr/interviews/{iv2}", json={"status": "已完成"})
    assert resp.status_code == 200
    await db_session.flush()
    await db_session.refresh(c)
    assert c.status == "已面试"
    logs = (await db_session.execute(
        select(CandidateStatusLog).where(CandidateStatusLog.candidate_id == c.id)
    )).scalars().all()
    assert any(log.to_status == "已面试" and "自动" in (log.remark or "") for log in logs)


async def test_completion_skipped_when_candidate_not_interviewing(
    client: AsyncClient, db_session: AsyncSession,
):
    """候选人不在「面试中」时，完成面试不强制改候选人状态。"""
    jd = _mk_jd(db_session)
    c = _mk_candidate(db_session, jd, status="待筛选")
    await db_session.flush()

    iv = (await _create_iv(client, c.id, interviewer="钱七")).json()["data"]["id"]
    resp = await client.put(f"/api/v1/hr/interviews/{iv}", json={"status": "已完成"})
    assert resp.status_code == 200
    await db_session.flush()
    await db_session.refresh(c)
    assert c.status == "待筛选"


# ─── AI 评估统一：evaluation 端点读胜任度报告 ───


async def test_evaluation_endpoint_reads_analysis_report(client: AsyncClient, db_session: AsyncSession):
    """GET /evaluation 统一返回胜任度报告；未生成时 data=None（不再永远 null 的读错位）。"""
    jd = _mk_jd(db_session)
    c = _mk_candidate(db_session, jd)
    await db_session.flush()

    iv_id = (await _create_iv(client, c.id, interviewer="钱七")).json()["data"]["id"]
    resp = await client.get(f"/api/v1/hr/interviews/{iv_id}/evaluation")
    assert resp.status_code == 200
    assert resp.json()["data"] is None

    # evaluate 无面试记录 → 400（与报告生成共用校验文案）
    resp = await client.post(f"/api/v1/hr/interviews/{iv_id}/evaluate")
    assert resp.status_code == 400
    assert "面试记录" in resp.json()["message"]


# ─── 状态机：流转白名单 + 状态日志 ───


async def test_status_transition_whitelist(client: AsyncClient, db_session: AsyncSession):
    from app.modules.hr.models import InterviewStatusLog

    jd = _mk_jd(db_session)
    c = _mk_candidate(db_session, jd, status="已面试")
    await db_session.flush()
    iv_id = (await _create_iv(client, c.id, interviewer="钱七")).json()["data"]["id"]

    # 非法：已完成 → 已安排（终态不可回退）
    r = await client.put(f"/api/v1/hr/interviews/{iv_id}", json={"status": "已安排"})
    assert r.status_code == 200  # 待安排 → 已安排 合法
    r = await client.put(f"/api/v1/hr/interviews/{iv_id}", json={"status": "已完成"})
    assert r.status_code == 200  # 已安排 → 已完成 合法
    r = await client.put(f"/api/v1/hr/interviews/{iv_id}", json={"status": "已安排"})
    assert r.status_code == 400
    assert "不允许" in r.json()["message"]
    # 终态不可取消
    assert (await client.delete(f"/api/v1/hr/interviews/{iv_id}")).status_code == 400

    # 状态日志完整记录流转链
    await db_session.flush()
    logs = (await db_session.execute(
        select(InterviewStatusLog)
        .where(InterviewStatusLog.interview_id == iv_id)
        .order_by(InterviewStatusLog.created_at)
    )).scalars().all()
    chain = [(log.from_status, log.to_status) for log in logs]
    assert (None, "待安排") in chain  # 创建日志
    assert ("待安排", "已安排") in chain
    assert ("已安排", "已完成") in chain


# ─── 面试总览：跨候选人筛选 ───


async def test_overview_filters_and_pagination(client: AsyncClient, db_session: AsyncSession):
    jd = _mk_jd(db_session)
    c1 = _mk_candidate(db_session, jd)
    c2 = _mk_candidate(db_session, jd)
    await db_session.flush()

    # 用随机面试官名过滤——测试库即开发库，全局 count 会混入真实数据
    iv_a, iv_b = _rand("总览面试官"), _rand("总览面试官")
    await _create_iv(client, c1.id, interviewer=iv_a, day="2026-12-01", start="09:00", end="10:00")
    await _create_iv(client, c2.id, interviewer=iv_b, day="2026-12-02", start="14:00", end="15:00")
    await _create_iv(client, c2.id, interviewer=iv_a, day="2026-12-03")

    # 按面试官（模糊，唯一名只命中自己）
    resp = await client.get("/api/v1/hr/interviews", params={"interviewer": iv_a})
    assert resp.status_code == 200
    assert resp.json()["meta"]["total"] == 2
    names = {item["candidate_name"] for item in resp.json()["data"]}
    assert names == {c1.name, c2.name}
    # join 带出的岗位字段存在（测试候选人未填 position，值为空即可）
    assert all("candidate_position" in item for item in resp.json()["data"])

    # 共同前缀 + 日期范围（含边界）
    resp = await client.get("/api/v1/hr/interviews", params={
        "interviewer": "总览面试官",
        "date_from": "2026-12-01", "date_to": "2026-12-02",
    })
    assert resp.json()["meta"]["total"] == 2

    # 分页（共同前缀命中全部 3 场）
    resp = await client.get("/api/v1/hr/interviews", params={
        "interviewer": "总览面试官", "page": 1, "page_size": 2,
    })
    assert len(resp.json()["data"]) == 2
    assert resp.json()["meta"]["total"] == 3


# ─── 人工面试评价 ───


async def test_feedback_upsert_and_get(client: AsyncClient, db_session: AsyncSession):
    from app.modules.hr.models import InterviewFeedback

    jd = _mk_jd(db_session)
    c = _mk_candidate(db_session, jd)
    await db_session.flush()
    iv_id = (await _create_iv(client, c.id, interviewer="钱七")).json()["data"]["id"]

    payload = {
        "evaluator": "钱七",
        "dimensions": [
            {"name": "专业能力", "score": 4, "comment": "基础扎实"},
            {"name": "沟通表达", "score": 5},
        ],
        "overall_comment": "整体表现良好",
        "result": "通过",
    }
    resp = await client.post(f"/api/v1/hr/interviews/{iv_id}/feedback", json=payload)
    assert resp.status_code == 200
    assert resp.json()["data"]["result"] == "通过"

    # 重复提交 = 覆盖更新，不产生第二条
    payload["result"] = "待定"
    resp = await client.post(f"/api/v1/hr/interviews/{iv_id}/feedback", json=payload)
    assert resp.status_code == 200
    await db_session.flush()
    rows = (await db_session.execute(
        select(InterviewFeedback).where(InterviewFeedback.interview_id == iv_id)
    )).scalars().all()
    assert len(rows) == 1 and rows[0].result == "待定"

    resp = await client.get(f"/api/v1/hr/interviews/{iv_id}/feedback")
    assert resp.json()["data"]["result"] == "待定"
    assert resp.json()["data"]["dimensions"][0]["name"] == "专业能力"

    # 结论枚举校验
    resp = await client.post(
        f"/api/v1/hr/interviews/{iv_id}/feedback",
        json={"evaluator": "钱七", "result": "优秀"},
    )
    assert resp.status_code == 400


# ─── 取消语义：状态置「已取消」且记录保留 ───


async def test_cancel_keeps_record_with_status(client: AsyncClient, db_session: AsyncSession):
    from app.modules.hr.models import Interview

    jd = _mk_jd(db_session)
    c = _mk_candidate(db_session, jd)
    await db_session.flush()

    iv_id = (await _create_iv(client, c.id, interviewer="钱七")).json()["data"]["id"]
    assert (await client.delete(f"/api/v1/hr/interviews/{iv_id}")).status_code == 200

    await db_session.flush()
    iv = (await db_session.execute(select(Interview).where(Interview.id == iv_id))).scalar_one()
    assert iv.status == "已取消"
    assert iv.is_deleted is False  # 记录保留，仅状态流转
    assert iv.calendar_event_id is None
