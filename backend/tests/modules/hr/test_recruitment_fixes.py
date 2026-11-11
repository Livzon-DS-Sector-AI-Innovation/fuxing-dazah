"""招聘板块审计修复回归测试。

对应修复：.xls 导入 500、parse-resume 资源限制与报文泄露、统计口径
（事件流转化率/入职事件周期）、push-review 状态机、入职审批 reviewer、
状态日志 operator、AI 报告去重触发与 session bug、Offer 前置校验、
已入职候选人删除防护、日历补建、model_version 脱钩、手机号归一。
"""

from datetime import date, timedelta
from io import BytesIO
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from httpx import AsyncClient
from openpyxl import Workbook
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.feishu_calendar import FeishuCalendarService
from app.modules.hr.models import Candidate, Interview, JobRequirement
from tests.modules.hr.conftest import _rand


def _mk_jd(db: AsyncSession, *, owner: str | None = "岗位负责人") -> JobRequirement:
    jd = JobRequirement(
        id=uuid4(),
        position_name=_rand("岗位"), department=_rand("部门"),
        headcount=2, owner=owner, duties="岗位职责说明",
    )
    db.add(jd)
    return jd


def _mk_candidate(db: AsyncSession, jd: JobRequirement, *, status: str = "待筛选") -> Candidate:
    c = Candidate(id=uuid4(), name=_rand("候选"), status=status, job_requirement_id=jd.id)
    db.add(c)
    return c


def _xlsx_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["姓名", "手机", "邮箱"])
    ws.append([_rand("导入"), "13800001111", "a@b.com"])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ─── 批量导入：.xls 拒绝 + 损坏文件 400 ───


async def test_upload_rejects_xls_with_400(client: AsyncClient):
    """旧格式 .xls 走 openpyxl 会抛非 ValueError 异常（曾必 500），现在入口直接 400。"""
    res = await client.post(
        "/api/v1/hr/candidates/upload",
        files={"file": ("candidates.xls", b"dummy", "application/vnd.ms-excel")},
    )
    assert res.status_code == 400, res.text
    assert ".xlsx" in res.json()["message"]


async def test_upload_corrupt_xlsx_400(client: AsyncClient):
    """扩展名是 .xlsx 但内容损坏 → 400 而不是 500。"""
    res = await client.post(
        "/api/v1/hr/candidates/upload",
        files={"file": ("candidates.xlsx", b"not an excel file", "application/octet-stream")},
    )
    assert res.status_code == 400, res.text


# ─── 简历解析：大小限制 + 报文不泄露内部异常 ───


async def test_parse_resume_size_limit(client: AsyncClient):
    res = await client.post(
        "/api/v1/hr/candidates/parse-resume",
        files={"resume": ("big.pdf", b"x" * (10 * 1024 * 1024 + 1), "application/pdf")},
    )
    assert res.status_code == 400
    assert "10MB" in res.json()["message"]


async def test_parse_resume_bad_pdf_no_internal_leak(client: AsyncClient):
    """畸形 PDF → 400 固定文案，不携带解析器内部异常细节。"""
    res = await client.post(
        "/api/v1/hr/candidates/parse-resume",
        files={"resume": ("broken.pdf", b"%PDF-1.4 garbage", "application/pdf")},
    )
    assert res.status_code == 400
    message = res.json()["message"]
    assert "损坏" in message or "加密" in message
    assert "pdfminer" not in message.lower()
    assert "Traceback" not in message


# ─── push-review：状态机校验 ───


async def test_push_review_rejects_late_stage_status(db_session: AsyncSession, client: AsyncClient):
    """「已面试」不可直接回推部门审核（旧逻辑只挡已录用/已入职/已拒绝）。"""
    jd = _mk_jd(db_session)
    c = _mk_candidate(db_session, jd, status="已面试")
    await db_session.flush()

    res = await client.post(
        f"/api/v1/hr/candidates/{c.id}/push-review", json={"pushed_by": "HR"},
    )
    assert res.status_code == 400
    assert "已面试" in res.json()["message"]

    # 「已筛选」→ 推送合法（与前端按钮展示条件一致）
    c2 = _mk_candidate(db_session, jd, status="已筛选")
    await db_session.flush()
    ok = await client.post(
        f"/api/v1/hr/candidates/{c2.id}/push-review", json={"pushed_by": "HR"},
    )
    assert ok.status_code == 200, ok.text


# ─── 入职审批：显式 reviewer 生效 ───


async def test_push_onboarding_respects_explicit_reviewer(
    db_session: AsyncSession, client: AsyncClient,
):
    """payload.reviewer 优先于 JD.owner（旧逻辑静默忽略该参数）。"""
    jd = _mk_jd(db_session, owner="王老板")
    c = _mk_candidate(db_session, jd, status="已录用")
    await db_session.flush()

    res = await client.post(
        f"/api/v1/hr/candidates/{c.id}/push-onboarding-review",
        json={"pushed_by": "HR", "reviewer": "李审批"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["data"]["reviewer"] == "李审批"

    # 未指定时回落 JD.owner
    c2 = _mk_candidate(db_session, jd, status="已录用")
    await db_session.flush()
    res2 = await client.post(
        f"/api/v1/hr/candidates/{c2.id}/push-onboarding-review",
        json={"pushed_by": "HR"},
    )
    assert res2.status_code == 200
    assert res2.json()["data"]["reviewer"] == "王老板"


# ─── 状态日志：operator 审计 ───


async def test_status_log_operator_recorded(db_session: AsyncSession, client: AsyncClient, test_user):
    """创建与流转的状态日志记录操作人（此前恒为 NULL）。"""
    jd = _mk_jd(db_session)
    await db_session.flush()
    created = await client.post("/api/v1/hr/candidates", json={
        "name": _rand("审计"), "job_requirement_id": str(jd.id),
    })
    cid = created.json()["data"]["id"]

    await client.put(f"/api/v1/hr/candidates/{cid}/status", json={"status": "已筛选"})

    logs = (await client.get(f"/api/v1/hr/candidates/{cid}/status-logs")).json()["data"]
    assert len(logs) == 2
    assert logs[0]["operator"] == test_user.name  # 创建
    assert logs[1]["operator"] == test_user.name  # 流转
    assert logs[1]["from_status"] == "待筛选"
    assert logs[1]["to_status"] == "已筛选"


async def test_onboard_writes_hired_status_log(db_session: AsyncSession, test_user):
    """onboard 显式补记「已入职」状态日志（供入职统计/周期计算取事件时间）。"""
    from app.modules.hr.service import CandidateService

    jd = _mk_jd(db_session)
    c = _mk_candidate(db_session, jd, status="待入职审批")
    await db_session.flush()

    service = CandidateService(db_session)
    await service.onboard(c.id, operator=test_user.name)

    logs = await service.get_status_logs(c.id)
    hired_logs = [lg for lg in logs if lg.to_status == "已入职"]
    assert len(hired_logs) == 1
    assert hired_logs[0].from_status == "待入职审批"
    assert hired_logs[0].operator == test_user.name
    assert "工号" in (hired_logs[0].remark or "")


# ─── 删除防护 ───


async def test_delete_onboarded_candidate_rejected(db_session: AsyncSession, client: AsyncClient):
    jd = _mk_jd(db_session)
    c = _mk_candidate(db_session, jd, status="已入职")
    await db_session.flush()

    res = await client.delete(f"/api/v1/hr/candidates/{c.id}")
    assert res.status_code == 400
    assert "已入职" in res.json()["message"]


# ─── Offer：前置状态与邮箱校验 ───


async def test_send_offer_requires_late_stage(db_session: AsyncSession, client: AsyncClient):
    jd = _mk_jd(db_session)
    c = _mk_candidate(db_session, jd, status="待筛选")
    await db_session.flush()

    res = await client.post(
        f"/api/v1/hr/candidates/{c.id}/send-offer",
        data={"candidate_email": "someone@example.com", "candidate_name": "张三"},
    )
    assert res.status_code == 400
    assert "待筛选" in res.json()["message"]


async def test_send_offer_rejects_bad_email(db_session: AsyncSession, client: AsyncClient):
    jd = _mk_jd(db_session)
    c = _mk_candidate(db_session, jd, status="已录用")
    await db_session.flush()

    res = await client.post(
        f"/api/v1/hr/candidates/{c.id}/send-offer",
        data={"candidate_email": "not-an-email", "candidate_name": "张三"},
    )
    assert res.status_code == 400
    assert "邮箱" in res.json()["message"]


# ─── 统计口径：事件流转化率 ≤100%，周期基于入职事件 ───


async def test_stats_conversion_rates_bounded(db_session: AsyncSession, client: AsyncClient):
    """走完完整链路的候选人：转化率为「曾到达」口径，任何相邻阶段不超 100%。"""
    from app.modules.hr.service import CandidateService

    jd = _mk_jd(db_session)
    c = _mk_candidate(db_session, jd)
    await db_session.flush()

    service = CandidateService(db_session)
    # 按状态机合法链路推进（已筛选→待部门审核→面试中→…→已录用）
    for status in ("已筛选", "待部门审核", "面试中", "已面试", "录用中", "已录用"):
        await service.transition_status(c.id, status)
    # 写一个早期创建时间：周期应按「已入职事件 - created_at」而不是被编辑刷新的 updated_at
    from sqlalchemy import update
    await db_session.execute(
        update(Candidate).where(Candidate.id == c.id).values(created_at=date.today() - timedelta(days=30))
    )
    await db_session.flush()

    res = await client.get("/api/v1/hr/recruitment/stats")
    assert res.status_code == 200, res.text
    data = res.json()["data"]

    rates = data["conversion_rates"]
    assert len(rates) == 8  # 9 个线性阶段 → 8 对
    assert rates[0]["from"] == "待筛选" and rates[-1]["to"] == "已入职"
    for r in rates:
        assert 0 <= r["rate"] <= 100.0, f"转化率越界: {r}"

    # 周期为非负数（入职事件晚于创建时间）
    assert data["avg_cycle_days"] is None or data["avg_cycle_days"] >= 0


# ─── 面试更新：AI 报告仅在内容变化时生成 ───


async def test_update_interview_skips_ai_when_content_unchanged(
    db_session: AsyncSession, client: AsyncClient,
):
    """只改状态不触发 AI 重生成；逐字稿变化才触发（含 session 属性修复）。"""
    jd = _mk_jd(db_session)
    c = _mk_candidate(db_session, jd)
    await db_session.flush()

    iv = Interview(
        candidate_id=c.id, interview_type="初试", interview_date=date.today(),
        interviewer="面试官", status="已安排", transcript_text="第一版逐字稿",
    )
    db_session.add(iv)
    await db_session.flush()

    with patch(
        "app.modules.hr.service.CandidateAnalysisService.generate",
        new=AsyncMock(return_value=None),
    ) as mock_generate:
        # 仅改状态 → 不触发
        res = await client.put(f"/api/v1/hr/interviews/{iv.id}", json={"status": "已完成"})
        assert res.status_code == 200, res.text
        mock_generate.assert_not_called()

        # 逐字稿变化 → 触发（session 属性修复后才能走到这里）
        res2 = await client.put(
            f"/api/v1/hr/interviews/{iv.id}", json={"transcript_text": "第二版逐字稿"},
        )
        assert res2.status_code == 200, res2.text
        mock_generate.assert_awaited_once()


# ─── 日历补建 ───


async def test_update_interview_rebuilds_missing_calendar(
    db_session: AsyncSession, client: AsyncClient,
):
    """此前创建日历失败的面试（event_id 为空）：显式勾选 create_calendar_event 补建。"""
    jd = _mk_jd(db_session)
    c = _mk_candidate(db_session, jd)
    await db_session.flush()

    iv = Interview(
        candidate_id=c.id, interview_type="初试", interview_date=date.today(),
        status="已安排",
    )
    db_session.add(iv)
    await db_session.flush()
    assert iv.calendar_event_id is None

    with patch.object(
        FeishuCalendarService, "create_interview_event",
        new=AsyncMock(return_value="evt_new_123"),
    ):
        res = await client.put(f"/api/v1/hr/interviews/{iv.id}", json={
            "create_calendar_event": True,
            "interview_date": date.today().isoformat(),
        })
    assert res.status_code == 200, res.text
    await db_session.flush()
    await db_session.refresh(iv)
    assert iv.calendar_event_id == "evt_new_123"


# ─── model_version 与配置脱钩 ───


async def test_analysis_report_uses_configured_model(db_session: AsyncSession):
    from app.modules.hr.config import HR_AI_MODEL
    from app.modules.hr.service import CandidateAnalysisService

    jd = _mk_jd(db_session)
    c = _mk_candidate(db_session, jd)
    iv = Interview(
        candidate_id=c.id, interview_type="初试", status="已完成",
        transcript_text="面试逐字稿内容",
    )
    db_session.add_all([c, iv])
    await db_session.flush()

    fake = {
        "dimensions": [{"name": "专业知识", "score": 8, "comment": "扎实"}],
        "strengths": ["基础好"], "risks": [], "total_score": 80,
        "recommend_level": "推荐", "interview_suggestions": ["追问项目细节"],
        "training_suggestions": [], "summary": "总体匹配",
    }
    with patch(
        "app.modules.hr.ai_service.AiChatService.call_json",
        new=AsyncMock(return_value=fake),
    ):
        report = await CandidateAnalysisService(db_session).generate(c.id, iv.id)
    assert report.model_version == HR_AI_MODEL


# ─── JD duties 回传（前端编辑回填依赖） ───


async def test_job_requirement_response_includes_duties(db_session: AsyncSession, client: AsyncClient):
    jd = _mk_jd(db_session)
    await db_session.flush()

    res = await client.get("/api/v1/hr/job-requirements")
    assert res.status_code == 200, res.text
    mine = [j for j in res.json()["data"] if j["id"] == str(jd.id)]
    assert mine and mine[0]["duties"] == "岗位职责说明"


# ─── 手机号归一（Excel 数字单元格） ───


def test_normalize_phone_strips_float_suffix():
    from app.modules.hr.service import CandidateService

    assert CandidateService._normalize_phone(13800001111.0) == "13800001111"
    assert CandidateService._normalize_phone(13800001111) == "13800001111"
    assert CandidateService._normalize_phone(" 13800001111 ") == "13800001111"
    assert CandidateService._normalize_phone("138-0000-1111") == "138-0000-1111"
