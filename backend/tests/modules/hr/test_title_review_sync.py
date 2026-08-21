"""职称评审同步测试（v2）：申报落库（原型字段映射）、投票回传与判定、事件路由、卡片审批。

bitable_client 全部 monkeypatch（不真连飞书）；Redis 全部 monkeypatch。
"""

import uuid
from datetime import date
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr import models as hr_models
from app.modules.hr.title_review import bitable_handler as bh
from app.modules.hr.title_review import models as m
from app.modules.hr.title_review.service import TitleReviewService
from app.modules.hr.title_review.schemas import TitleReviewActivityCreate


def _rand(prefix: str = "") -> str:
    suffix = uuid.uuid4().hex[:8].upper()
    return f"{prefix}{suffix}"


def _activity_create(**overrides) -> TitleReviewActivityCreate:
    payload = {"name": f"同步活动{_rand()}"}
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


def _apply_fields(name: str, employee_no: str, **overrides) -> dict:
    fields = {
        "姓名": name,
        "工号": employee_no,
        "申报序列": "技术职级",
        "申报职级": "工程师",
        "现任职级": "助理工程师",
        "是否破格申报": "否",
        "岗位任务自我评价": "合格",
        "工作思想表现自我评价": "优秀",
        "岗位规定的职责任务完成情况": "完成了各项任务",
        "职称评审申报表": [{"file_token": "ft1", "name": "申报表.pdf", "size": 100}],
        "近五年年终绩效考核结果": "2021年佳",
    }
    fields.update(overrides)
    return fields


# ─── 申报同步（原型字段映射） ───


class TestApplySync:
    async def test_added_parses_prototype_fields(self, db_session: AsyncSession, monkeypatch):
        service = TitleReviewService(db_session)
        activity = await service.create_activity(_activity_create())
        employee_no = f"E{_rand()}"
        await _create_employee(db_session, "李四", employee_no)

        application = await service.sync_apply_record_added(
            activity.id, "rec1", _apply_fields("李四", employee_no)
        )
        assert application.status == m.APPLICATION_SUBMITTED
        assert application.sequence == "技术职级"
        assert application.apply_level == "工程师"
        assert application.current_level == "助理工程师"
        assert application.is_exception is False
        assert application.self_evaluations == {
            "岗位任务自我评价": "合格",
            "工作思想表现自我评价": "优秀",
        }
        assert application.work_statements == {
            "岗位规定的职责任务完成情况": "完成了各项任务",
            "近五年年终绩效考核结果": "2021年佳",
        }
        assert application.attachments == {
            "职称评审申报表": [{"file_token": "ft1", "name": "申报表.pdf", "size": 100}]
        }

    async def test_added_invalid_employee(self, db_session: AsyncSession, monkeypatch):
        service = TitleReviewService(db_session)
        activity = await service.create_activity(_activity_create())
        application = await service.sync_apply_record_added(
            activity.id, "rec1", _apply_fields("王五", "E-NOT-EXIST")
        )
        assert application.status == m.APPLICATION_INVALID

    async def test_edited_invalid_to_valid(self, db_session: AsyncSession, monkeypatch):
        service = TitleReviewService(db_session)
        activity = await service.create_activity(_activity_create())
        employee_no = f"E{_rand()}"
        await _create_employee(db_session, "赵六", employee_no)
        await service.sync_apply_record_added(
            activity.id, "rec1", _apply_fields("赵六", "E-WRONG")
        )
        application = await service.sync_apply_record_edited(
            activity.id, "rec1", _apply_fields("赵六", employee_no)
        )
        assert application.status == m.APPLICATION_SUBMITTED

    async def test_deleted_soft_delete(self, db_session: AsyncSession, monkeypatch):
        service = TitleReviewService(db_session)
        activity = await service.create_activity(_activity_create())
        await service.sync_apply_record_added(
            activity.id, "rec1", _apply_fields("钱七", "E-NONE")
        )
        await service.sync_apply_record_deleted(activity.id, "rec1")
        assert (
            await service.application_repo.get_by_feishu_record(activity.id, "rec1")
        ) is None


# ─── 投票回传 + 判定 ───


class TestVoteSync:
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
        employee_no = f"E{_rand()}"
        emp = await _create_employee(db_session, "申报人", employee_no)
        application = m.TitleReviewApplication(
            activity_id=activity.id,
            employee_id=emp.id,
            employee_no=employee_no,
            name=emp.name,
            department="测试部",
            sequence=m.SEQUENCE_SKILL,
            apply_level="中级工",  # 中级工不需终审
            status=m.APPLICATION_VOTING,
            feishu_record_id="rec-app-1",
        )
        await service.application_repo.create(application)
        judges = []
        for i in range(2):
            judges.append(await _create_employee(db_session, f"评委{i}", f"J{i}-{_rand()}"))
        from app.modules.hr.title_review.schemas import TitleReviewJudgeAssignIn, TitleReviewJudgeAssignItemIn

        await service.assign_judges(
            application.id,
            TitleReviewJudgeAssignIn(
                judges=[TitleReviewJudgeAssignItemIn(employee_id=j.id, role="技术专家") for j in judges]
            ),
        )
        return service, activity, application, judges

    def _vote_fields(self, judge_code: str, result: str, **overrides) -> dict:
        fields = {
            "评审人编号": judge_code,
            "投票结果": result,
            "综合等级": "合格",
            "评审意见": "同意推荐",
            "本职工作完成评价": "合格",
        }
        fields.update(overrides)
        return fields

    async def test_partial_then_full_auto_finalize(self, setup):
        service, activity, application, judges = setup
        rows = await service.judge_repo.list_by_application(application.id)
        row_by_emp = {r.judge_employee_id: r for r in rows}
        # 评委1 投票 → 未全投，不判定
        await service.sync_vote_record(
            activity.id,
            row_by_emp[judges[0].id].feishu_record_id,
            self._vote_fields(row_by_emp[judges[0].id].judge_code, m.VOTE_AGREE),
        )
        application = await service.application_repo.get_by_id(application.id)
        assert application.status == m.APPLICATION_VOTING
        # 评委2 投票 → 2:0 全投自动判定通过
        await service.sync_vote_record(
            activity.id,
            row_by_emp[judges[1].id].feishu_record_id,
            self._vote_fields(row_by_emp[judges[1].id].judge_code, m.VOTE_AGREE),
        )
        application = await service.application_repo.get_by_id(application.id)
        assert application.agree_votes == 2
        assert application.status == m.APPLICATION_PASSED
        # 评价明细落库
        scores = await service.score_repo.list_by_application(application.id)
        assert any(s.dimension_name == "本职工作完成评价" and s.grade == "合格" for s in scores)

    async def test_fallback_match_by_judge_code(self, setup):
        service, activity, application, judges = setup
        rows = await service.judge_repo.list_by_application(application.id)
        row_by_emp = {r.judge_employee_id: r for r in rows}
        # 用未知 record_id 但携带正确评审人编号 → 按编号匹配
        await service.sync_vote_record(
            activity.id,
            "unknown-row",
            self._vote_fields(row_by_emp[judges[0].id].judge_code, m.VOTE_AGREE),
        )
        row = await service.judge_repo.get_by_id(row_by_emp[judges[0].id].id)
        assert row.vote_result == m.VOTE_AGREE
        assert row.comprehensive_grade == "合格"
        assert row.review_comment == "同意推荐"


# ─── 事件处理器路由 ───


class TestHandlerRouting:
    async def test_apply_record_added_routed(self, db_session: AsyncSession, monkeypatch):
        service = TitleReviewService(db_session)
        activity = await service.create_activity(_activity_create())
        activity.feishu_app_token = "app1"
        activity.apply_table_id = "tbl1"
        activity.vote_table_id = "tbl2"
        await db_session.flush()
        employee_no = f"E{_rand()}"
        await _create_employee(db_session, "路由测试员", employee_no)
        await db_session.flush()

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _fake_factory():
            yield db_session

        monkeypatch.setattr(bh, "async_session_factory", _fake_factory)
        monkeypatch.setattr(db_session, "commit", AsyncMock())
        monkeypatch.setattr(bh, "_redis_set", AsyncMock(return_value=True))
        monkeypatch.setattr(bh, "_redis_get", AsyncMock(return_value=None))
        apply_names = ["姓名", "工号", "申报序列", "申报职级", "现任职级", "是否破格申报"]
        field_map = [
            {"field_id": f"f{i}", "field_name": name}
            for i, name in enumerate(apply_names)
        ]
        monkeypatch.setattr(
            "app.modules.hr.title_review.bitable_client.list_fields",
            AsyncMock(return_value=field_map),
        )

        after = {
            "f0": "路由测试员", "f1": employee_no, "f2": "技术职级",
            "f3": "工程师", "f4": "助理工程师", "f5": "否",
        }
        await bh.handle_record_changed(
            "app1", "tbl1",
            [{"action": "record_added", "record_id": "rec1", "after_value": after}],
        )
        applications = await service.application_repo.list_all_by_activity(activity.id)
        assert len(applications) == 1
        assert applications[0].status == m.APPLICATION_SUBMITTED
        assert applications[0].sequence == "技术职级"

    async def test_ignore_key_skips(self, db_session: AsyncSession, monkeypatch):
        service = TitleReviewService(db_session)
        activity = await service.create_activity(_activity_create())
        activity.feishu_app_token = "app1"
        activity.apply_table_id = "tbl1"
        activity.vote_table_id = "tbl2"
        await db_session.flush()

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _fake_factory():
            yield db_session

        monkeypatch.setattr(bh, "async_session_factory", _fake_factory)
        monkeypatch.setattr(db_session, "commit", AsyncMock())
        monkeypatch.setattr(bh, "_redis_set", AsyncMock(return_value=True))
        monkeypatch.setattr(bh, "_redis_get", AsyncMock(return_value="1"))
        field_map = [
            {"field_id": "f0", "field_name": "姓名"},
            {"field_id": "f1", "field_name": "工号"},
        ]
        monkeypatch.setattr(
            "app.modules.hr.title_review.bitable_client.list_fields",
            AsyncMock(return_value=field_map),
        )
        after = {"f0": "某人", "f1": "E-NONE"}
        await bh.handle_record_changed(
            "app1", "tbl1",
            [{"action": "record_added", "record_id": "rec-ignored", "after_value": after}],
        )
        applications = await service.application_repo.list_all_by_activity(activity.id)
        assert applications == []


# ─── 卡片审批 ───
