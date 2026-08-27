"""职称评审 service 单元测试（v2 投票制多级评审）。"""

import uuid
from datetime import date
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr import models as hr_models
from app.modules.hr.title_review import models as m
from app.modules.hr.title_review.schemas import (
    TitleReviewActivityCreate,
    TitleReviewActivityUpdate,
    TitleReviewCommitteeMemberIn,
    TitleReviewDeptCommitteeIn,
    TitleReviewJudgeAssignIn,
    TitleReviewJudgeAssignItemIn,
)
from app.modules.hr.title_review.service import (
    TitleReviewService,
    decide_by_votes,
)


def _rand(prefix: str = "") -> str:
    suffix = uuid.uuid4().hex[:8].upper()
    return f"{prefix}{suffix}"


def _activity_create(**overrides) -> TitleReviewActivityCreate:
    payload = {"name": f"测试活动{_rand()}"}
    payload.update(overrides)
    return TitleReviewActivityCreate(**payload)


async def _create_employee(
    db_session: AsyncSession, name: str, employee_no: str, department: str = "测试部"
) -> hr_models.Employee:
    emp = hr_models.Employee(
        name=name,
        employee_number=employee_no,
        department=department,
        position="工程师",
        status="在职",
        hire_date=date(2020, 1, 1),
    )
    db_session.add(emp)
    await db_session.flush()
    return emp


# ─── 票数判定（纯函数） ───


class TestDecideByVotes:
    def test_two_thirds_pass(self):
        assert decide_by_votes(2, 1, 2 / 3) is True  # 恰好 2/3

    def test_two_thirds_fail(self):
        assert decide_by_votes(1, 1, 2 / 3) is False

    def test_all_agree(self):
        assert decide_by_votes(3, 0, 2 / 3) is True

    def test_no_votes(self):
        assert decide_by_votes(0, 0, 2 / 3) is False

    def test_abstain_not_counted(self):
        # 弃权不影响判定：同意2反对1弃权3 → 2/3 通过
        assert decide_by_votes(2, 1, 2 / 3) is True


# ─── 活动 / 职级组 / 评价项 ───


class TestActivity:
    async def test_create_with_defaults(self, db_session: AsyncSession):
        service = TitleReviewService(db_session)
        activity = await service.create_activity(_activity_create())
        assert activity.status == m.ACTIVITY_DRAFT
        levels = await service.get_levels(activity.id)
        dims = await service.get_dimensions(activity.id)
        assert len(levels) == 10  # 制度 10 档（技术员→专家 5 档 + 初级工→高级技师 5 档，技术助理已取消）
        assert len(dims) == 7
        assert {lv.sequence for lv in levels} == {m.SEQUENCE_TECH, m.SEQUENCE_SKILL}

    async def test_delete_activity_cascades_soft_delete(
        self, db_session: AsyncSession, monkeypatch
    ):
        """删除活动不限状态/申报数量，级联软删申报与职级组/评价项。"""
        from sqlalchemy import select as sa_select

        monkeypatch.setattr(
            TitleReviewService, "_load_employee_profile", AsyncMock(return_value=None)
        )
        service = TitleReviewService(db_session)
        activity = await service.create_activity(
            _activity_create(feishu_app_token="app1", apply_table_id="tbl1")
        )
        employee_no = f"E{_rand()}"
        await _create_employee(db_session, "李四", employee_no)
        application = await service.sync_apply_record_added(
            activity.id,
            "rec1",
            {
                "姓名": "李四",
                "工号": employee_no,
                "申报序列": "技术职级",
                "申报职级": "工程师",
            },
        )
        assert application is not None
        activity.status = m.ACTIVITY_REVIEWING  # 非 draft 也可删除
        await db_session.flush()
        await service.delete_activity(activity.id)
        assert activity.is_deleted is True
        apps = (await db_session.execute(
            sa_select(m.TitleReviewApplication).where(
                m.TitleReviewApplication.activity_id == activity.id
            )
        )).scalars().all()
        assert apps and all(a.is_deleted for a in apps)
        levels = (await db_session.execute(
            sa_select(m.TitleReviewLevel).where(
                m.TitleReviewLevel.activity_id == activity.id
            )
        )).scalars().all()
        assert levels and all(lv.is_deleted for lv in levels)

    async def test_update_levels_only_draft(self, db_session: AsyncSession):
        service = TitleReviewService(db_session)
        activity = await service.create_activity(_activity_create())
        activity.feishu_app_token = "app1"
        activity.apply_table_id = "tbl1"
        activity.vote_table_id = "tbl2"
        await db_session.flush()
        await service.open_activity(activity.id)
        with pytest.raises(HTTPException, match="仅配置中"):
            await service.update_activity(activity.id, TitleReviewActivityUpdate(levels=[]))

    async def test_open_requires_bound_tables(self, db_session: AsyncSession):
        service = TitleReviewService(db_session)
        activity = await service.create_activity(_activity_create())
        with pytest.raises(HTTPException, match="绑定飞书表格"):
            await service.open_activity(activity.id)

    async def test_full_status_flow(self, db_session: AsyncSession):
        service = TitleReviewService(db_session)
        activity = await service.create_activity(_activity_create())
        activity.feishu_app_token = "app1"
        activity.apply_table_id = "tbl1"
        activity.vote_table_id = "tbl2"
        await db_session.flush()
        activity = await service.open_activity(activity.id)
        assert activity.status == m.ACTIVITY_OPEN
        activity = await service.start_review(activity.id)
        assert activity.status == m.ACTIVITY_REVIEWING
        activity = await service.close_activity(activity.id)
        assert activity.status == m.ACTIVITY_CLOSED


# ─── 部门评审组 ───


class TestCommittee:
    async def test_upsert_idempotent(self, db_session: AsyncSession, monkeypatch):
        monkeypatch.setattr(
            "app.modules.hr.title_review.notify.send_judge_reminder", AsyncMock(return_value=True)
        )
        service = TitleReviewService(db_session)
        emp2 = await _create_employee(db_session, "小组成员", f"C{_rand()}")
        data = TitleReviewDeptCommitteeIn(
            department="测试部",
            committee_members=[TitleReviewCommitteeMemberIn(employee_id=emp2.id, name=emp2.name, employee_no=emp2.employee_number)],
        )
        c1 = await service.upsert_committee(data)
        # 同部门再次保存 → 更新而非新建
        data.committee_members = []
        c2 = await service.upsert_committee(data)
        assert c1.id == c2.id
        committees = await service.list_committees()
        # 只统计本测试部门（测试库与开发库共用，可能存在其他部门评审组）
        assert len([c for c in committees if c.department == "测试部"]) == 1
        assert c2.committee_members is None

    async def test_default_members(self, db_session: AsyncSession, monkeypatch):
        monkeypatch.setattr(
            "app.modules.hr.title_review.notify.send_judge_reminder", AsyncMock(return_value=True)
        )
        service = TitleReviewService(db_session)
        activity = await service.create_activity(_activity_create())
        emp = await _create_employee(db_session, "申报人", f"A{_rand()}")
        member = await _create_employee(db_session, "评委1", f"J{_rand()}")
        await service.upsert_committee(
            TitleReviewDeptCommitteeIn(
                department="测试部",
                committee_members=[TitleReviewCommitteeMemberIn(employee_id=member.id, name=member.name, employee_no=member.employee_number)],
            )
        )
        application = m.TitleReviewApplication(
            activity_id=activity.id,
            employee_id=emp.id,
            employee_no=emp.employee_number,
            name=emp.name,
            department="测试部",
            status=m.APPLICATION_VOTING,
            feishu_record_id="rec1",
        )
        await service.application_repo.create(application)
        members = await service.default_committee_members(application.id)
        assert len(members) == 1
        assert members[0]["employee_id"] == str(member.id)

    async def test_upsert_committee_backfills_judges(self, db_session: AsyncSession, monkeypatch):
        """评审组保存后，自动为评审期该部门投票中的申报补齐评委。"""
        monkeypatch.setattr(
            "app.modules.hr.title_review.notify.send_judge_reminder", AsyncMock(return_value=True)
        )
        service = TitleReviewService(db_session)
        activity = await service.create_activity(_activity_create())
        activity.feishu_app_token = "app1"
        activity.apply_table_id = "tbl1"
        activity.vote_table_id = "tbl2"
        await db_session.flush()
        await service.open_activity(activity.id)
        await service.start_review(activity.id)
        emp = await _create_employee(db_session, "申报人2", f"A{_rand()}")
        member = await _create_employee(db_session, "评委甲", f"J{_rand()}")
        application = m.TitleReviewApplication(
            activity_id=activity.id,
            employee_id=emp.id,
            employee_no=emp.employee_number,
            name=emp.name,
            department="测试部",
            status=m.APPLICATION_VOTING,
            feishu_record_id="rec1",
        )
        await service.application_repo.create(application)
        assert await service.judge_repo.list_by_application(application.id) == []

        await service.upsert_committee(
            TitleReviewDeptCommitteeIn(
                department="测试部",
                committee_members=[TitleReviewCommitteeMemberIn(employee_id=member.id, name=member.name, employee_no=member.employee_number)],
            )
        )
        judges = await service.judge_repo.list_by_application(application.id)
        assert len(judges) == 1
        assert judges[0].judge_name == "评委甲"


# ─── 多级流程 + 评委 + 判定 ───


class TestFlowAndVotes:
    @pytest.fixture
    async def setup(self, db_session: AsyncSession, monkeypatch):
        """活动 + 申报(voting) + 2 位评委（投票表行已写）。"""
        monkeypatch.setattr(
            "app.modules.hr.title_review.bitable_client.batch_create_records",
            AsyncMock(return_value=["vrow-1", "vrow-2"]),
        )
        monkeypatch.setattr(
            "app.modules.hr.title_review.bitable_client.update_record", AsyncMock()
        )
        monkeypatch.setattr(
            "app.modules.hr.title_review.notify.send_result_card", AsyncMock(return_value=True)
        )
        monkeypatch.setattr(
            "app.modules.hr.title_review.notify.send_judge_reminder", AsyncMock(return_value=True)
        )
        service = TitleReviewService(db_session)
        activity = await service.create_activity(_activity_create())
        activity.feishu_app_token = "app1"
        activity.apply_table_id = "tbl1"
        activity.vote_table_id = "tbl2"
        await db_session.flush()
        await service.open_activity(activity.id)
        emp = await _create_employee(db_session, "申报人", f"A{_rand()}")
        application = m.TitleReviewApplication(
            activity_id=activity.id,
            employee_id=emp.id,
            employee_no=emp.employee_number,
            name=emp.name,
            department="测试部",
            sequence=m.SEQUENCE_TECH,
            apply_level="工程师",
            status=m.APPLICATION_VOTING,
            feishu_record_id="rec-app-1",
        )
        await service.application_repo.create(application)
        judges = []
        for i in range(2):
            judges.append(await _create_employee(db_session, f"评委{i}", f"J{i}-{_rand()}"))
        await service.assign_judges(
            application.id,
            TitleReviewJudgeAssignIn(
                judges=[TitleReviewJudgeAssignItemIn(employee_id=j.id, role="技术专家") for j in judges]
            ),
        )
        return service, activity, application, judges

    async def test_judge_codes_anonymous(self, setup):
        service, activity, application, judges = setup
        rows = await service.judge_repo.list_by_application(application.id)
        assert {r.judge_code for r in rows} == {"P1", "P2"}

    async def test_voted_judge_cannot_be_removed(self, setup):
        service, activity, application, judges = setup
        rows = await service.judge_repo.list_by_application(application.id)
        row_by_emp = {r.judge_employee_id: r for r in rows}
        row0 = row_by_emp[judges[0].id]
        row0.vote_result = m.VOTE_AGREE
        await service.judge_repo.update(row0)
        with pytest.raises(HTTPException, match="已投票"):
            await service.assign_judges(
                application.id,
                TitleReviewJudgeAssignIn(
                    judges=[TitleReviewJudgeAssignItemIn(employee_id=judges[1].id, role="技术专家")]
                ),
            )

    async def test_finalize_by_votes_pass(self, setup):
        service, activity, application, judges = setup
        rows = await service.judge_repo.list_by_application(application.id)
        row_by_emp = {r.judge_employee_id: r for r in rows}
        for i, judge_emp in enumerate(judges):
            row = row_by_emp[judge_emp.id]
            row.vote_result = m.VOTE_AGREE if i == 0 else m.VOTE_OPPOSE
            await service.judge_repo.update(row)
        # 2 同意 1 反对需 3 评委场景，此处 2 评委 1:1 → 未通过；改用 2 同意
        row_by_emp[judges[1].id].vote_result = m.VOTE_AGREE
        await service.judge_repo.update(row_by_emp[judges[1].id])
        application = await service.finalize_by_votes(application.id)
        assert application.agree_votes == 2
        assert application.oppose_votes == 0
        assert application.status == m.APPLICATION_PASSED
        assert application.final_result == m.APPLICATION_PASSED

    async def test_finalize_by_votes_fail(self, setup):
        service, activity, application, judges = setup
        rows = await service.judge_repo.list_by_application(application.id)
        row_by_emp = {r.judge_employee_id: r for r in rows}
        row_by_emp[judges[0].id].vote_result = m.VOTE_AGREE
        await service.judge_repo.update(row_by_emp[judges[0].id])
        row_by_emp[judges[1].id].vote_result = m.VOTE_OPPOSE
        await service.judge_repo.update(row_by_emp[judges[1].id])
        application = await service.finalize_by_votes(application.id)
        assert application.status == m.APPLICATION_FAILED

    async def test_finalize_requires_all_voted_unless_force(self, setup):
        service, activity, application, judges = setup
        with pytest.raises(HTTPException, match="未投票"):
            await service.finalize_by_votes(application.id)
        # 提前判定：force=True，按已投票计
        rows = await service.judge_repo.list_by_application(application.id)
        rows[0].vote_result = m.VOTE_AGREE
        await service.judge_repo.update(rows[0])
        application = await service.finalize_by_votes(application.id, force=True)
        assert application.status == m.APPLICATION_PASSED

# ─── 评委内网投票（v3） ───


class TestJudgeVote:
    @pytest.fixture
    async def setup(self, db_session: AsyncSession, monkeypatch):
        """活动 + 申报(voting) + 2 位评委（无飞书投票表行）。"""
        monkeypatch.setattr(
            "app.modules.hr.title_review.notify.send_result_card", AsyncMock(return_value=True)
        )
        monkeypatch.setattr(
            "app.modules.hr.title_review.notify.send_judge_reminder", AsyncMock(return_value=True)
        )
        service = TitleReviewService(db_session)
        activity = await service.create_activity(_activity_create())
        activity.feishu_app_token = "app1"
        activity.apply_table_id = "tbl1"
        activity.vote_table_id = "tbl2"
        await db_session.flush()
        await service.open_activity(activity.id)
        emp = await _create_employee(db_session, "申报人", f"A{_rand()}")
        application = m.TitleReviewApplication(
            activity_id=activity.id,
            employee_id=emp.id,
            employee_no=emp.employee_number,
            name=emp.name,
            department="测试部",
            sequence=m.SEQUENCE_TECH,
            apply_level="工程师",
            status=m.APPLICATION_VOTING,
            feishu_record_id="rec-app-1",
        )
        await service.application_repo.create(application)
        judges = []
        for i in range(2):
            judges.append(await _create_employee(db_session, f"评委{i}", f"J{i}-{_rand()}"))
        await service.assign_judges(
            application.id,
            TitleReviewJudgeAssignIn(
                judges=[TitleReviewJudgeAssignItemIn(employee_id=j.id, role="技术专家") for j in judges]
            ),
        )
        return service, application, judges

    async def test_list_my_tasks(self, setup):
        service, application, judges = setup
        tasks = await service.list_my_judge_tasks(judges[0].employee_number)
        assert len(tasks) == 1
        assert tasks[0]["status"] == "pending"
        assert tasks[0]["application"]["name"] == "申报人"
        # 其他评委看不到该任务
        other = await _create_employee(service.session, "无关评委", f"X{_rand()}")
        assert await service.list_my_judge_tasks(other.employee_number) == []

    async def test_submit_vote_and_auto_finalize(self, setup):
        service, application, judges = setup
        rows = await service.judge_repo.list_by_application(application.id)
        row_by_emp = {r.judge_employee_id: r for r in rows}

        from app.modules.hr.title_review.schemas import TitleReviewJudgeVoteIn

        # 7 项全填合格 → 综合等级合格 → 投票结果自动为同意
        grades_ok = {name: "合格" for name in m.DEFAULT_DIMENSION_NAMES}
        vote1 = TitleReviewJudgeVoteIn(
            dimension_grades=grades_ok,
            review_comment="同意推荐",
        )
        await service.submit_vote(row_by_emp[judges[0].id].id, judges[0].employee_number, vote1)
        application = await service.application_repo.get_by_id(application.id)
        assert application.status == m.APPLICATION_VOTING  # 评委2 未投

        vote2 = TitleReviewJudgeVoteIn(dimension_grades=grades_ok)
        await service.submit_vote(row_by_emp[judges[1].id].id, judges[1].employee_number, vote2)
        application = await service.application_repo.get_by_id(application.id)
        assert application.status == m.APPLICATION_PASSED
        assert application.agree_votes == 2

    async def test_vote_result_auto_from_dimensions(self, setup):
        """投票结果由 7 维评价自动计算：不合格 → 不同意。"""
        service, application, judges = setup
        rows = await service.judge_repo.list_by_application(application.id)
        row_by_emp = {r.judge_employee_id: r for r in rows}

        from app.modules.hr.title_review.schemas import TitleReviewJudgeVoteIn

        grades = {name: "合格" for name in m.DEFAULT_DIMENSION_NAMES}
        # 3 项不合格 → 综合等级不合格 → 自动不同意
        for name in list(m.DEFAULT_DIMENSION_NAMES)[:3]:
            grades[name] = "不合格"
        await service.submit_vote(
            row_by_emp[judges[0].id].id,
            judges[0].employee_number,
            TitleReviewJudgeVoteIn(dimension_grades=grades),
        )
        rows = await service.judge_repo.list_by_application(application.id)
        voted = next(r for r in rows if r.judge_employee_id == judges[0].id)
        assert voted.vote_result == m.VOTE_OPPOSE
        assert voted.comprehensive_grade == "不合格"

    async def test_vote_ownership_isolation(self, setup):
        service, application, judges = setup
        rows = await service.judge_repo.list_by_application(application.id)
        row_by_emp = {r.judge_employee_id: r for r in rows}

        from app.modules.hr.title_review.schemas import TitleReviewJudgeVoteIn

        # 评委1 用评委2 的工号投自己的任务 → 403
        with pytest.raises(HTTPException, match="不属于您"):
            await service.submit_vote(
                row_by_emp[judges[0].id].id,
                judges[1].employee_number,
                TitleReviewJudgeVoteIn(vote_result=m.VOTE_AGREE),
            )

    async def test_incomplete_dimensions_rejected(self, setup):
        """维度未填齐不可提交投票。"""
        service, application, judges = setup
        rows = await service.judge_repo.list_by_application(application.id)
        row_by_emp = {r.judge_employee_id: r for r in rows}

        from app.modules.hr.title_review.schemas import TitleReviewJudgeVoteIn

        with pytest.raises(HTTPException, match="7 项维度评价"):
            await service.submit_vote(
                row_by_emp[judges[0].id].id,
                judges[0].employee_number,
                TitleReviewJudgeVoteIn(
                    dimension_grades={"本职工作完成评价": "优秀"}
                ),
            )



# ─── 按部门自动分配评委（v3） ───


class TestAutoAssign:
    async def test_start_review_auto_assigns_by_department(
        self, db_session: AsyncSession, monkeypatch
    ):
        monkeypatch.setattr(
            "app.modules.hr.title_review.notify.send_judge_reminder", AsyncMock(return_value=True)
        )
        service = TitleReviewService(db_session)
        activity = await service.create_activity(_activity_create())
        activity.feishu_app_token = "app1"
        activity.apply_table_id = "tbl1"
        activity.vote_table_id = "tbl2"
        await db_session.flush()
        await service.open_activity(activity.id)

        # 部门评审组：测试部 2 位评委
        m1 = await _create_employee(db_session, "组员1", f"C1-{_rand()}")
        m2 = await _create_employee(db_session, "组员2", f"C2-{_rand()}")
        await service.upsert_committee(
            TitleReviewDeptCommitteeIn(
                department="测试部",
                committee_members=[
                    TitleReviewCommitteeMemberIn(employee_id=m1.id, name=m1.name, employee_no=m1.employee_number),
                    TitleReviewCommitteeMemberIn(employee_id=m2.id, name=m2.name, employee_no=m2.employee_number),
                ],
            )
        )
        # 测试部申报人 1 条申报
        emp = await _create_employee(db_session, "申报人", f"A{_rand()}")
        application = m.TitleReviewApplication(
            activity_id=activity.id,
            employee_id=emp.id,
            employee_no=emp.employee_number,
            name=emp.name,
            department="测试部",
            status=m.APPLICATION_SUBMITTED,
            feishu_record_id="rec1",
        )
        await service.application_repo.create(application)

        await service.start_review(activity.id)

        application = await service.application_repo.get_by_id(application.id)
        assert application.status == m.APPLICATION_VOTING
        judges = await service.judge_repo.list_by_application(application.id)
        assert {j.judge_employee_id for j in judges} == {m1.id, m2.id}
        assert {j.judge_code for j in judges} == {"P1", "P2"}

    async def test_auto_assign_judge_sees_only_own_department(
        self, db_session: AsyncSession, monkeypatch
    ):
        """评委只看到自己部门分配的申报任务，看不到其他部门。"""
        monkeypatch.setattr(
            "app.modules.hr.title_review.notify.send_judge_reminder", AsyncMock(return_value=True)
        )
        service = TitleReviewService(db_session)
        activity = await service.create_activity(_activity_create())
        activity.feishu_app_token = "app1"
        activity.apply_table_id = "tbl1"
        activity.vote_table_id = "tbl2"
        await db_session.flush()
        await service.open_activity(activity.id)

        judge_a = await _create_employee(db_session, "甲部门评委", f"JA-{_rand()}")
        await service.upsert_committee(
            TitleReviewDeptCommitteeIn(
                department="甲部门",
                committee_members=[
                    TitleReviewCommitteeMemberIn(employee_id=judge_a.id, name=judge_a.name, employee_no=judge_a.employee_number),
                ],
            )
        )
        judge_b = await _create_employee(db_session, "乙部门评委", f"JB-{_rand()}")
        await service.upsert_committee(
            TitleReviewDeptCommitteeIn(
                department="乙部门",
                committee_members=[
                    TitleReviewCommitteeMemberIn(employee_id=judge_b.id, name=judge_b.name, employee_no=judge_b.employee_number),
                ],
            )
        )
        emp_a = await _create_employee(db_session, "甲申报人", f"A1-{_rand()}")
        emp_b = await _create_employee(db_session, "乙申报人", f"A2-{_rand()}")
        app_a = m.TitleReviewApplication(
            activity_id=activity.id, employee_id=emp_a.id, employee_no=emp_a.employee_number,
            name=emp_a.name, department="甲部门", status=m.APPLICATION_SUBMITTED, feishu_record_id="ra",
        )
        app_b = m.TitleReviewApplication(
            activity_id=activity.id, employee_id=emp_b.id, employee_no=emp_b.employee_number,
            name=emp_b.name, department="乙部门", status=m.APPLICATION_SUBMITTED, feishu_record_id="rb",
        )
        await service.application_repo.create(app_a)
        await service.application_repo.create(app_b)
        await service.start_review(activity.id)

        tasks_a = await service.list_my_judge_tasks(judge_a.employee_number)
        tasks_b = await service.list_my_judge_tasks(judge_b.employee_number)
        assert [t["application"]["name"] for t in tasks_a] == ["甲申报人"]
        assert [t["application"]["name"] for t in tasks_b] == ["乙申报人"]


# ─── 综合等级自动计算（制度附表5） ───


class TestComprehensiveGrade:
    def test_qualified(self):
        from app.modules.hr.title_review.service import compute_comprehensive_grade

        assert compute_comprehensive_grade(["合格"] * 7) == "合格"
        # 附表5：≥5 项合格 → 合格（含恰好 5 项）
        assert compute_comprehensive_grade(["合格"] * 5 + ["不合格"] * 2) == "合格"

    def test_unqualified(self):
        from app.modules.hr.title_review.service import compute_comprehensive_grade

        # 附表5：>2 项不合格 → 不合格
        assert compute_comprehensive_grade(["不合格"] * 3 + ["合格"] * 4) == "不合格"

    def test_incomplete_returns_none(self):
        from app.modules.hr.title_review.service import compute_comprehensive_grade

        assert compute_comprehensive_grade(["合格"] * 5 + [None, None]) is None

    def test_invalid_grade_returns_none(self):
        from app.modules.hr.title_review.service import compute_comprehensive_grade

        # 「优秀」等级已取消，出现即视为非法
        assert compute_comprehensive_grade(["优秀"] * 7) is None
