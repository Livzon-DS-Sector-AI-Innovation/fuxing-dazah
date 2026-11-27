"""招聘数据隔离回归测试（用人部门视角）。

对应收敛规则：
- 候选人/岗位需求列表按授权部门过滤（候选人部门列 + 所属岗位部门两条路径），
  并集上"本人任审核人"的候选人
- 候选人详情/简历预览越界 403，审核人（含历史审核人）可访问（飞书卡片深链）
- 候选人对比仅限本部门岗位
- 招聘统计与 AI 筛简历收紧为 hr:recruitment:manage
- pending-review 显式 reviewer 参数仅管理权限可用；无名用户 fail-closed
- push-review 落库 pushed_by 用真实登录人（前端占位 'HR' 不再入库，
  否则审核结果飞书通知按 "HR" 找不到 open_id 被静默跳过）
"""

from unittest.mock import patch
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.modules.hr.deps import HrAccessContext, get_hr_scope
from app.modules.hr.models import Candidate, CandidateReview, JobRequirement
from app.platform.identity.models import User
from tests.modules.hr.conftest import _rand


def _mk_jd(db: AsyncSession, department: str, *, owner: str | None = None) -> JobRequirement:
    jd = JobRequirement(
        id=uuid4(), position_name=_rand("岗位"), department=department,
        headcount=2, owner=owner,
    )
    db.add(jd)
    return jd


def _mk_candidate(db: AsyncSession, jd: JobRequirement, *, status: str = "待筛选",
                  department: str | None = None) -> Candidate:
    c = Candidate(
        id=uuid4(), name=_rand("候选"), status=status,
        job_requirement_id=jd.id, department=department,
    )
    db.add(c)
    return c


def _scoped_client(test_user: User, departments: frozenset[str]) -> None:
    """在当前测试内把 get_hr_scope 覆写为授权部门范围（client 夹具 teardown 会统一清理）。"""

    async def _override() -> HrAccessContext:
        return HrAccessContext(
            user=test_user,
            data_scope="department",
            department=next(iter(departments)),
            employee_number=test_user.employee_no,
            scoped_departments=departments,
        )

    app.dependency_overrides[get_hr_scope] = _override


async def test_list_candidates_scoped_to_own_department(
    db_session: AsyncSession, client: AsyncClient, test_user: User,
):
    """授权部门A用户：只看到部门A岗位下的候选人（含部门列直接匹配），部门B不可见。"""
    dept_a, dept_b = _rand("隔离部门A"), _rand("隔离部门B")
    jd_a, jd_b = _mk_jd(db_session, dept_a), _mk_jd(db_session, dept_b)
    c_a = _mk_candidate(db_session, jd_a)  # department=None → 走岗位部门子查询
    c_a2 = _mk_candidate(db_session, jd_a, department=dept_a)  # 走候选人部门列
    c_b = _mk_candidate(db_session, jd_b)
    await db_session.flush()
    _scoped_client(test_user, frozenset({dept_a}))

    res = await client.get("/api/v1/hr/candidates", params={"page_size": 100})
    assert res.status_code == 200, res.text
    names = {row["name"] for row in res.json()["data"]}
    assert c_a.name in names and c_a2.name in names
    assert c_b.name not in names


async def test_list_candidates_includes_reviewed(
    db_session: AsyncSession, client: AsyncClient, test_user: User,
):
    """本人任审核人的候选人（即使属其他部门）对部门范围用户可见。"""
    dept_b = _rand("隔离部门B")
    jd_b = _mk_jd(db_session, dept_b)
    c_b = _mk_candidate(db_session, jd_b)
    db_session.add(CandidateReview(
        candidate_id=c_b.id, job_requirement_id=jd_b.id,
        pushed_by="某人事", reviewer=test_user.name, status="已同意",
    ))
    await db_session.flush()
    _scoped_client(test_user, frozenset({_rand("隔离部门A")}))

    res = await client.get("/api/v1/hr/candidates", params={"page_size": 100})
    assert res.status_code == 200
    names = {row["name"] for row in res.json()["data"]}
    assert c_b.name in names


async def test_candidate_detail_scope_and_reviewer_access(
    db_session: AsyncSession, client: AsyncClient, test_user: User,
):
    """越界详情 403；成为审核人（含历史审核）后可访问（飞书卡片深链场景）。"""
    dept_a, dept_b = _rand("隔离部门A"), _rand("隔离部门B")
    jd_b = _mk_jd(db_session, dept_b)
    c_b = _mk_candidate(db_session, jd_b)
    await db_session.flush()
    _scoped_client(test_user, frozenset({dept_a}))

    blocked = await client.get(f"/api/v1/hr/candidates/{c_b.id}")
    assert blocked.status_code == 403

    db_session.add(CandidateReview(
        candidate_id=c_b.id, job_requirement_id=jd_b.id,
        pushed_by="某人事", reviewer=test_user.name, status="已同意",
    ))
    await db_session.flush()
    ok = await client.get(f"/api/v1/hr/candidates/{c_b.id}")
    assert ok.status_code == 200, ok.text


async def test_resume_preview_blocked_outside_scope(
    db_session: AsyncSession, client: AsyncClient, test_user: User,
):
    dept_a, dept_b = _rand("隔离部门A"), _rand("隔离部门B")
    jd_b = _mk_jd(db_session, dept_b)
    c_b = _mk_candidate(db_session, jd_b)
    await db_session.flush()
    _scoped_client(test_user, frozenset({dept_a}))

    res = await client.get(f"/api/v1/hr/candidates/{c_b.id}/resume-preview")
    assert res.status_code == 403


async def test_job_requirements_scoped(
    db_session: AsyncSession, client: AsyncClient, test_user: User,
):
    dept_a, dept_b = _rand("隔离部门A"), _rand("隔离部门B")
    jd_a, jd_b = _mk_jd(db_session, dept_a), _mk_jd(db_session, dept_b)
    await db_session.flush()
    _scoped_client(test_user, frozenset({dept_a}))

    res = await client.get("/api/v1/hr/job-requirements")
    assert res.status_code == 200
    ids = {row["id"] for row in res.json()["data"]}
    assert str(jd_a.id) in ids
    assert str(jd_b.id) not in ids


async def test_comparison_scope(
    db_session: AsyncSession, client: AsyncClient, test_user: User,
):
    dept_a, dept_b = _rand("隔离部门A"), _rand("隔离部门B")
    jd_a, jd_b = _mk_jd(db_session, dept_a), _mk_jd(db_session, dept_b)
    _mk_candidate(db_session, jd_a)
    await db_session.flush()
    _scoped_client(test_user, frozenset({dept_a}))

    denied = await client.get(f"/api/v1/hr/job-requirements/{jd_b.id}/candidates/comparison")
    assert denied.status_code == 403
    ok = await client.get(f"/api/v1/hr/job-requirements/{jd_a.id}/candidates/comparison")
    assert ok.status_code == 200, ok.text


async def test_stats_and_screening_require_manage(client: AsyncClient):
    """招聘统计 / AI 筛简历是 HR 专属工具：read-only 用户 403。"""

    async def _read_only(user_id: str, db: object) -> set[str]:
        return {"hr:recruitment:read"}

    with patch("app.platform.permission.deps.get_user_permissions", new=_read_only):
        stats = await client.get("/api/v1/hr/recruitment/stats")
        assert stats.status_code == 403
        screening = await client.get("/api/v1/hr/resume-screening")
        assert screening.status_code == 403


async def test_pending_review_reviewer_param_requires_manage(
    db_session: AsyncSession, client: AsyncClient, test_user: User,
):
    """显式 reviewer 参数仅管理权限可代查；read-only 用户只能看到自己的待审。"""
    jd = _mk_jd(db_session, _rand("部门"), owner="王负责人")
    c = _mk_candidate(db_session, jd, status="待部门审核")
    db_session.add(CandidateReview(
        candidate_id=c.id, job_requirement_id=jd.id,
        pushed_by="某人事", reviewer="王负责人", status="待审核",
    ))
    await db_session.flush()

    # 默认（全权限）：显式 reviewer 可代查
    as_manager = await client.get(
        "/api/v1/hr/candidates/pending-review", params={"reviewer": "王负责人"},
    )
    assert as_manager.status_code == 200
    assert len(as_manager.json()["data"]) == 1

    async def _read_only(user_id: str, db: object) -> set[str]:
        return {"hr:recruitment:read"}

    with patch("app.platform.permission.deps.get_user_permissions", new=_read_only):
        as_reader = await client.get(
            "/api/v1/hr/candidates/pending-review", params={"reviewer": "王负责人"},
        )
        assert as_reader.status_code == 200
        # reviewer 参数被忽略，回落到本人（HR测试员）→ 空
        assert as_reader.json()["data"] == []


async def test_push_review_records_real_pusher(
    db_session: AsyncSession, client: AsyncClient, test_user: User,
):
    """前端占位 pushed_by='HR' 时落库真实登录人，保证审核结果通知能找到推送人。"""
    jd = _mk_jd(db_session, _rand("部门"), owner="王负责人")
    c = _mk_candidate(db_session, jd, status="已筛选")
    await db_session.flush()

    res = await client.post(
        f"/api/v1/hr/candidates/{c.id}/push-review", json={"pushed_by": "HR"},
    )
    assert res.status_code == 200, res.text
    rv = (await db_session.execute(
        select(CandidateReview).where(CandidateReview.candidate_id == c.id)
    )).scalar_one()
    assert rv.pushed_by == test_user.name
