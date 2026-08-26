"""职称评审同步测试（v2）：申报落库（原型字段映射）、投票回传与判定、事件路由、卡片审批。

bitable_client 全部 monkeypatch（不真连飞书）；Redis 全部 monkeypatch。
"""

import uuid
from datetime import date, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr import models as hr_models
from app.modules.hr.title_review import bitable_handler as bh
from app.modules.hr.title_review import models as m
from app.modules.hr.title_review.schemas import TitleReviewActivityCreate
from app.modules.hr.title_review.service import TitleReviewService


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

    async def test_added_lookup_style_values(self, db_session: AsyncSession, monkeypatch):
        """lookup 列值为 [{text, type}] 结构时正常解析并匹配员工。"""
        service = TitleReviewService(db_session)
        activity = await service.create_activity(_activity_create())
        employee_no = f"E{_rand()}"
        await _create_employee(db_session, "孙八", employee_no)

        fields = {
            "姓名": "孙八",
            "工号": [{"text": employee_no, "type": "text"}],
            "学历": [{"text": "本科", "type": "text"}],
            "申报序列": "技术职级",
            "申报职级": "工程师",
            "近五年年终绩效考核结果": [{"text": '2024年"佳"', "type": "text"}],
        }
        application = await service.sync_apply_record_added(activity.id, "rec1", fields)
        assert application.status == m.APPLICATION_SUBMITTED
        assert application.employee_no == employee_no
        assert application.work_statements == {
            "近五年年终绩效考核结果": '2024年"佳"'
        }

    async def test_added_department_prefers_actual(self, db_session: AsyncSession, monkeypatch):
        """部门取实际部门，实际部门为空才回落体现部门。"""
        service = TitleReviewService(db_session)
        activity = await service.create_activity(_activity_create())
        employee_no = f"E{_rand()}"
        emp = await _create_employee(db_session, "周九", employee_no)
        emp.actual_department = "AI创新部"
        emp.department = "质量控制部（QC部）"
        await db_session.flush()

        application = await service.sync_apply_record_added(
            activity.id, "rec1", _apply_fields("周九", employee_no)
        )
        assert application.department == "AI创新部"

    async def test_added_current_level_empty_stays_empty(self, db_session: AsyncSession, monkeypatch):
        """现任职级为空即留空，不做员工档案职称兜底（无职称如实体现）。"""
        service = TitleReviewService(db_session)
        activity = await service.create_activity(_activity_create())
        employee_no = f"E{_rand()}"
        emp = await _create_employee(db_session, "吴十", employee_no)
        emp.qualifications = ["工程师"]
        await db_session.flush()

        fields = _apply_fields("吴十", employee_no)
        fields.pop("现任职级")
        application = await service.sync_apply_record_added(activity.id, "rec1", fields)
        assert application.current_level is None

    async def test_added_profile_from_employee_info_table(self, db_session: AsyncSession, monkeypatch):
        """员工信息表按姓名+工号自动带出个人档案，存入申报 profile。"""
        from app.modules.hr.title_review import bitable_client as bc

        service = TitleReviewService(db_session)
        activity = await service.create_activity(
            _activity_create(feishu_app_token="app1")
        )
        employee_no = f"E{_rand()}"
        await _create_employee(db_session, "郑十一", employee_no)
        monkeypatch.setattr(
            bc, "list_tables",
            AsyncMock(return_value=[{"name": "员工信息表", "table_id": "emp_tbl"}]),
        )
        monkeypatch.setattr(
            bc, "list_all_records",
            AsyncMock(return_value=[{
                "record_id": "er1",
                "fields": {
                    "姓名": "郑十一", "工号": employee_no, "学历": "本科",
                    "司龄": "3 年", "入职日期": "2023-05-01", "性别": "男",
                    "职务": "工程师", "岗位职级": "技术职级",
                    "近5年年终绩效考评结果": '2024年"佳"',
                },
            }]),
        )
        application = await service.sync_apply_record_added(
            activity.id, "rec1", _apply_fields("郑十一", employee_no)
        )
        assert application.profile == {
            "学历": "本科", "司龄": "3 年", "入职日期": "2023-05-01",
            "性别": "男", "职务": "工程师", "岗位职级": "技术职级",
            "近5年年终绩效考评结果": '2024年"佳"',
        }

    async def test_added_resume_and_external_cert(self, db_session: AsyncSession, monkeypatch):
        """工作简历与外部职称证书选择随申报表字段落库到业绩陈述。"""
        service = TitleReviewService(db_session)
        activity = await service.create_activity(_activity_create())
        employee_no = f"E{_rand()}"
        await _create_employee(db_session, "周十四", employee_no)
        fields = _apply_fields("周十四", employee_no)
        fields["任职以来工作简历"] = "2024-2026 车间技术员"
        fields["是否具备外部专业技术职称或职业/执业技能证书"] = "是"
        application = await service.sync_apply_record_added(activity.id, "rec1", fields)
        assert application.work_statements["任职以来工作简历"] == "2024-2026 车间技术员"
        assert application.work_statements["是否具备外部专业技术职称或职业/执业技能证书"] == "是"

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
        from app.modules.hr.title_review.schemas import (
            TitleReviewJudgeAssignIn,
            TitleReviewJudgeAssignItemIn,
        )

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
            "完成本职工作情况": "合格",
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
        assert any(s.dimension_name == "完成本职工作情况" and s.grade == "合格" for s in scores)

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


# ─── 审批实例同步（简化表单 → 申报表字段映射） ───


def _table_fields_fixture() -> list[dict]:
    return [
        {"field_id": "f1", "field_name": "姓名", "type": 1},
        {"field_id": "f2", "field_name": "工号", "type": 19},  # lookup 只读
        {"field_id": "f3", "field_name": "学历", "type": 19},
        {
            "field_id": "f4", "field_name": "申报序列", "type": 3,
            "property": {"options": [{"name": "技术职级"}, {"name": "职业技能"}]},
        },
        {
            "field_id": "f5", "field_name": "申报职级", "type": 3,
            "property": {"options": [{"name": "技术员"}, {"name": "工程师"}]},
        },
        {
            "field_id": "f6", "field_name": "岗位任务自我评价", "type": 3,
            "property": {"options": [{"name": "优秀"}, {"name": "合格"}, {"name": "不合格"}]},
        },
        {"field_id": "f7", "field_name": "专利/论文/著作/总结/报告及发表情况", "type": 1},
        {"field_id": "f8", "field_name": "审批实例编号", "type": 1},
        {"field_id": "f9", "field_name": "申报编号", "type": 1005},  # 系统列只读
        {
            "field_id": "f10", "field_name": "是否破格申报", "type": 3,
            "property": {"options": [{"name": "是"}, {"name": "否"}]},
        },
        {"field_id": "f11", "field_name": "任职以来工作简历", "type": 1},
        {
            "field_id": "f12", "field_name": "是否具备外部专业技术职称或职业/执业技能证书",
            "type": 1,
        },
        {"field_id": "f13", "field_name": "证明材料上传（图片）", "type": 1},
    ]


def _approved_instance_form() -> list[dict]:
    return [
        {"name": "姓名", "type": "radioV2", "value": "测试员工"},
        {"name": "工号", "type": "radioV2", "value": "T-000001"},
        {"name": "部门", "type": "radioV2", "value": "AI创新部"},
        {"name": "本次申报职级类型", "type": "radioV2", "value": "技术职级"},
        {"name": "本次申报职级（技术）", "type": "radioV2", "value": "技术员"},
        {"name": "岗位规定职责自我评价", "type": "radioV2", "value": "合格"},
        {
            "name": "任现职以来撰写的专利、论文、著作、总结、报告",
            "type": "textarea", "value": "专利2篇",
        },
        {"name": "说明 1", "type": "text", "value": "以下为附件4内容"},
    ]


class TestApprovalInstanceSync:
    async def test_sync_maps_new_form_fields_to_table_columns(
        self, db_session: AsyncSession, monkeypatch
    ):
        from app.modules.hr.title_review import approval_client as ac
        from app.modules.hr.title_review import bitable_client as bc

        service = TitleReviewService(db_session)
        activity = await service.create_activity(
            _activity_create(
                feishu_app_token="app1", apply_table_id="tbl1", approval_code="CODE1"
            )
        )
        monkeypatch.setattr(ac, "list_instance_codes", AsyncMock(return_value=["INST1"]))
        monkeypatch.setattr(bc, "list_tables", AsyncMock(return_value=[]))
        monkeypatch.setattr(
            ac, "get_instance",
            AsyncMock(return_value={"status": "APPROVED", "form": _approved_instance_form()}),
        )
        monkeypatch.setattr(bc, "list_all_records", AsyncMock(return_value=[]))
        monkeypatch.setattr(
            bc, "list_fields", AsyncMock(return_value=_table_fields_fixture())
        )
        written: list[dict] = []
        async def _fake_batch_create(app_token, table_id, records):
            written.extend(records)
            return ["rec1"]
        monkeypatch.setattr(bc, "batch_create_records", _fake_batch_create)
        # 图片转存下载在测试中打桩失败 → 保留原链接（断言不变）
        monkeypatch.setattr(
            "app.modules.hr.title_review.service._download_image_bytes",
            AsyncMock(side_effect=Exception("offline")),
        )

        stats = await service.sync_approval_instances(activity.id)
        assert stats["approval_synced"] == 1
        assert len(written) == 1
        fields = written[0]
        # 映射：本次申报职级类型→申报序列、本次申报职级（技术）→申报职级、
        # 岗位规定职责自我评价→岗位任务自我评价、撰写专利…→专利/论文/著作/…及发表情况
        assert fields == {
            "姓名": "测试员工",
            "申报序列": "技术职级",
            "申报职级": "技术员",
            "岗位任务自我评价": "合格",
            "专利/论文/著作/总结/报告及发表情况": "专利2篇",
            "审批实例编号": "INST1",
        }
        # lookup/系统列与申报表无对应列不写：工号/学历/申报编号/部门/说明 1
        assert "工号" not in fields and "部门" not in fields and "学历" not in fields

    async def test_sync_merges_duplicate_target_columns(
        self, db_session: AsyncSession, monkeypatch
    ):
        """多个表单字段映射到同一申报表列时按换行合并；是否破格映射到是否破格申报。"""
        from app.modules.hr.title_review import approval_client as ac
        from app.modules.hr.title_review import bitable_client as bc

        service = TitleReviewService(db_session)
        activity = await service.create_activity(
            _activity_create(
                feishu_app_token="app1", apply_table_id="tbl1", approval_code="CODE1"
            )
        )
        monkeypatch.setattr(ac, "list_instance_codes", AsyncMock(return_value=["INST1"]))
        monkeypatch.setattr(bc, "list_tables", AsyncMock(return_value=[]))
        form = _approved_instance_form() + [
            {
                "name": "专利、论文、著作、总结、报告（本人负责部分）以及授权、刊出及交流情况 （时间、刊物或会议名称）",
                "type": "textarea", "value": "详细B",
            },
            {"name": "是否破格", "type": "radioV2", "value": "否"},
            {
                "name": "任职以来工作简历", "type": "fieldList",
                "value": [[
                    {"name": "DateInterval", "type": "dateInterval", "value": {"start": "2024-08-25", "end": "2026-06-15"}},
                    {"name": "部门/担任职位", "type": "input", "value": "统计"},
                ]],
            },
            {"name": "是否具备外部专业技术职称或职业/执业技能证书", "type": "radioV2", "value": "是"},
            {
                "name": "证明材料上传（图片）", "type": "image",
                "value": [{"url": "https://img.feishu.cn/xx1.png", "name": "证书.jpg"}],
            },
        ]
        monkeypatch.setattr(
            ac, "get_instance", AsyncMock(return_value={"status": "APPROVED", "form": form})
        )
        monkeypatch.setattr(bc, "list_all_records", AsyncMock(return_value=[]))
        monkeypatch.setattr(
            bc, "list_fields", AsyncMock(return_value=_table_fields_fixture())
        )
        written: list[dict] = []

        async def _fake_batch_create(app_token, table_id, records):
            written.extend(records)
            return ["rec1"]

        monkeypatch.setattr(bc, "batch_create_records", _fake_batch_create)
        # 图片转存下载在测试中打桩失败 → 保留原链接（断言不变）
        monkeypatch.setattr(
            "app.modules.hr.title_review.service._download_image_bytes",
            AsyncMock(side_effect=Exception("offline")),
        )
        stats = await service.sync_approval_instances(activity.id)
        assert stats["approval_synced"] == 1
        fields = written[0]
        assert fields["专利/论文/著作/总结/报告及发表情况"] == "专利2篇\n详细B"
        assert fields["是否破格申报"] == "否"
        assert fields["任职以来工作简历"] == "任职时间：2024-08-25 ~ 2026-06-15\n部门/担任职位：统计"
        assert fields["是否具备外部专业技术职称或职业/执业技能证书"] == "是"
        assert fields["证明材料上传（图片）"] == "证书.jpg https://img.feishu.cn/xx1.png"

    async def test_sync_updates_existing_employee_row(
        self, db_session: AsyncSession, monkeypatch
    ):
        """同员工再次提交审批 → 覆盖更新申报表行，审批实例编号累积防旧实例重写。"""
        from app.modules.hr.title_review import approval_client as ac
        from app.modules.hr.title_review import bitable_client as bc

        service = TitleReviewService(db_session)
        activity = await service.create_activity(
            _activity_create(
                feishu_app_token="app1", apply_table_id="tbl1", approval_code="CODE1"
            )
        )
        monkeypatch.setattr(ac, "list_instance_codes", AsyncMock(return_value=["NEW"]))
        monkeypatch.setattr(bc, "list_tables", AsyncMock(return_value=[]))
        monkeypatch.setattr(
            ac, "get_instance",
            AsyncMock(return_value={"status": "APPROVED", "form": _approved_instance_form()}),
        )
        monkeypatch.setattr(
            bc, "list_all_records",
            AsyncMock(return_value=[{
                "record_id": "rec-old",
                "fields": {
                    "审批实例编号": "OLD",
                    "姓名": "测试员工",
                    "工号": [{"text": "T-000001", "type": "text"}],
                },
            }]),
        )
        monkeypatch.setattr(
            bc, "list_fields", AsyncMock(return_value=_table_fields_fixture())
        )
        updated: list[tuple] = []

        async def _fake_update(app_token, table_id, record_id, fields):
            updated.append((app_token, table_id, record_id, fields))

        monkeypatch.setattr(bc, "update_record", _fake_update)
        batch_create = AsyncMock(return_value=[])
        monkeypatch.setattr(bc, "batch_create_records", batch_create)
        # 图片转存下载在测试中打桩失败 → 保留原链接（断言不变）
        monkeypatch.setattr(
            "app.modules.hr.title_review.service._download_image_bytes",
            AsyncMock(side_effect=Exception("offline")),
        )

        stats = await service.sync_approval_instances(activity.id)
        assert stats["approval_updated"] == 1
        assert stats["approval_synced"] == 0
        batch_create.assert_not_awaited()
        assert len(updated) == 1
        assert updated[0][2] == "rec-old"
        fields = updated[0][3]
        assert fields["审批实例编号"] == "OLD,NEW"
        assert fields["姓名"] == "测试员工"
        assert fields["申报序列"] == "技术职级"

    async def test_sync_skips_existing_instance(self, db_session: AsyncSession, monkeypatch):
        from app.modules.hr.title_review import approval_client as ac
        from app.modules.hr.title_review import bitable_client as bc

        service = TitleReviewService(db_session)
        activity = await service.create_activity(
            _activity_create(
                feishu_app_token="app1", apply_table_id="tbl1", approval_code="CODE1"
            )
        )
        monkeypatch.setattr(ac, "list_instance_codes", AsyncMock(return_value=["INST1"]))
        monkeypatch.setattr(bc, "list_tables", AsyncMock(return_value=[]))
        monkeypatch.setattr(
            bc, "list_all_records",
            AsyncMock(return_value=[{"record_id": "rec1", "fields": {"审批实例编号": "INST1"}}]),
        )
        monkeypatch.setattr(
            bc, "list_fields", AsyncMock(return_value=_table_fields_fixture())
        )
        batch_create = AsyncMock(return_value=[])
        monkeypatch.setattr(bc, "batch_create_records", batch_create)

        stats = await service.sync_approval_instances(activity.id)
        assert stats["approval_skipped"] == 1
        assert stats["approval_synced"] == 0
        batch_create.assert_not_awaited()

    async def test_sync_select_value_not_in_options_dropped(
        self, db_session: AsyncSession, monkeypatch
    ):
        from app.modules.hr.title_review import approval_client as ac
        from app.modules.hr.title_review import bitable_client as bc

        service = TitleReviewService(db_session)
        activity = await service.create_activity(
            _activity_create(
                feishu_app_token="app1", apply_table_id="tbl1", approval_code="CODE1"
            )
        )
        monkeypatch.setattr(ac, "list_instance_codes", AsyncMock(return_value=["INST1"]))
        monkeypatch.setattr(bc, "list_tables", AsyncMock(return_value=[]))
        form = _approved_instance_form()
        form[4] = {"name": "本次申报职级（技术）", "type": "radioV2", "value": "无此职级"}
        monkeypatch.setattr(
            ac, "get_instance", AsyncMock(return_value={"status": "APPROVED", "form": form})
        )
        monkeypatch.setattr(bc, "list_all_records", AsyncMock(return_value=[]))
        monkeypatch.setattr(
            bc, "list_fields", AsyncMock(return_value=_table_fields_fixture())
        )
        written: list[dict] = []
        async def _fake_batch_create(app_token, table_id, records):
            written.extend(records)
            return ["rec1"]
        monkeypatch.setattr(bc, "batch_create_records", _fake_batch_create)

        stats = await service.sync_approval_instances(activity.id)
        assert stats["approval_synced"] == 1
        # 非法单选值整列丢弃，其余列正常写入
        assert "申报职级" not in written[0]
        assert written[0]["申报序列"] == "技术职级"

    async def test_sync_from_approval_mirror_table(
        self, db_session: AsyncSession, monkeypatch
    ):
        """Base 内存在审批镜像表时直接作为数据源（不调用审批 API）。"""
        import base64 as b64

        from app.modules.hr.title_review import approval_client as ac
        from app.modules.hr.title_review import bitable_client as bc

        service = TitleReviewService(db_session)
        activity = await service.create_activity(
            _activity_create(
                feishu_app_token="app1", apply_table_id="tbl1", approval_code="CODE1"
            )
        )
        instance_code = "E4135F70-F67D-4C1A-B70E-80ECC622F5B1"
        source_id = b64.b64encode(
            f"7677215254350269401:{instance_code}-1:54aa1137".encode()
        ).decode("utf-8")
        start_ms, end_ms = 1758398400000, 1759003200000
        mirror_fields = {
            "申请状态": "已通过",
            "SourceID": source_id,
            "姓名": "测试员工",
            "工号": "T-000001",
            "本次申报职级类型": "技术职级",
            "本次申报职级（技术）": "工程师",
            "岗位规定职责自我评价": "合格",
            "任职以来工作简历_开始时间": start_ms,
            "任职以来工作简历_结束时间": end_ms,
            "任职以来工作简历_部门/担任职位": "测试部",
        }
        monkeypatch.setattr(ac, "list_instance_codes", AsyncMock())
        monkeypatch.setattr(
            bc, "list_tables",
            AsyncMock(return_value=[{"name": "福兴医药职称审批", "table_id": "tbl_mirror"}]),
        )
        monkeypatch.setattr(
            bc, "list_all_records",
            AsyncMock(side_effect=[[], [{"record_id": "mr1", "fields": mirror_fields}]]),
        )
        monkeypatch.setattr(
            bc, "list_fields", AsyncMock(return_value=_table_fields_fixture())
        )
        written: list[dict] = []
        async def _fake_batch_create(app_token, table_id, records):
            written.extend(records)
            return ["rec1"]
        monkeypatch.setattr(bc, "batch_create_records", _fake_batch_create)
        monkeypatch.setattr(
            "app.modules.hr.title_review.service._download_image_bytes",
            AsyncMock(side_effect=Exception("offline")),
        )

        stats = await service.sync_approval_instances(activity.id)
        ac.list_instance_codes.assert_not_awaited()
        assert stats["approval_synced"] == 1
        assert stats["approval_skipped"] == 0
        assert written[0]["审批实例编号"] == instance_code
        assert written[0]["申报序列"] == "技术职级"
        assert written[0]["申报职级"] == "工程师"
        assert written[0]["岗位任务自我评价"] == "合格"
        expected_resume = (
            f"任职时间：{datetime.fromtimestamp(start_ms / 1000).strftime('%Y-%m-%d')} ~ "
            f"{datetime.fromtimestamp(end_ms / 1000).strftime('%Y-%m-%d')}\n"
            "部门/担任职位：测试部"
        )
        assert written[0]["任职以来工作简历"] == expected_resume

    async def test_sync_mirror_table_skips_done_and_updates_existing(
        self, db_session: AsyncSession, monkeypatch
    ):
        """镜像表已写入过的实例跳过；同员工新实例覆盖更新申报行并累积编号。"""
        import base64 as b64

        from app.modules.hr.title_review import bitable_client as bc

        service = TitleReviewService(db_session)
        activity = await service.create_activity(
            _activity_create(
                feishu_app_token="app1", apply_table_id="tbl1", approval_code="CODE1"
            )
        )
        old_code = "60A7E503-F16F-4CCB-8F5F-081C80F1C1E7"
        new_code = "E4135F70-F67D-4C1A-B70E-80ECC622F5B1"

        def _sid(code: str) -> str:
            return b64.b64encode(
                f"7677215254350269401:{code}-1:abc".encode()
            ).decode("utf-8")

        apply_row = {
            "record_id": "apply_rec1",
            "fields": {"姓名": "测试员工", "工号": "T-000001", "审批实例编号": old_code},
        }
        mirror_rows = [
            {"record_id": "mr_old", "fields": {
                "申请状态": "已通过", "SourceID": _sid(old_code),
                "姓名": "测试员工", "工号": "T-000001",
            }},
            {"record_id": "mr_new", "fields": {
                "申请状态": "已通过", "SourceID": _sid(new_code),
                "姓名": "测试员工", "工号": "T-000001",
                "本次申报职级（技术）": "工程师",
            }},
        ]
        monkeypatch.setattr(
            bc, "list_tables",
            AsyncMock(return_value=[{"name": "福兴医药职称审批", "table_id": "tbl_mirror"}]),
        )
        monkeypatch.setattr(
            bc, "list_all_records", AsyncMock(side_effect=[[apply_row], mirror_rows])
        )
        monkeypatch.setattr(
            bc, "list_fields", AsyncMock(return_value=_table_fields_fixture())
        )
        updated: list[tuple] = []
        async def _fake_update(app_token, table_id, record_id, fields):
            updated.append((record_id, fields))
        monkeypatch.setattr(bc, "update_record", _fake_update)
        monkeypatch.setattr(bc, "batch_create_records", AsyncMock(return_value=[]))
        monkeypatch.setattr(
            "app.modules.hr.title_review.service._download_image_bytes",
            AsyncMock(side_effect=Exception("offline")),
        )

        stats = await service.sync_approval_instances(activity.id)
        assert stats["approval_updated"] == 1
        assert stats["approval_skipped"] == 1
        assert updated[0][0] == "apply_rec1"
        assert updated[0][1]["审批实例编号"] == f"{old_code},{new_code}"
        assert updated[0][1]["申报职级"] == "工程师"


def test_extract_approval_code_from_source_id():
    import base64 as b64

    from app.modules.hr.title_review import service as svc

    raw = "7677215254350269401:E4135F70-F67D-4C1A-B70E-80ECC622F5B1-1:54aa1137"
    sid = b64.b64encode(raw.encode("utf-8")).decode("utf-8")
    assert (
        svc._extract_approval_code_from_source_id(sid)
        == "E4135F70-F67D-4C1A-B70E-80ECC622F5B1"
    )
    assert svc._extract_approval_code_from_source_id("!!不是base64!!") is None
    assert svc._extract_approval_code_from_source_id("") is None


# ─── 对账 ───


class TestReconcile:
    async def _mk_activity(self, db_session: AsyncSession, monkeypatch):
        """创建绑定申报表的 draft 活动，档案拉取打桩为 None（不连飞书）。"""
        monkeypatch.setattr(
            TitleReviewService, "_load_employee_profile", AsyncMock(return_value=None)
        )
        service = TitleReviewService(db_session)
        activity = await service.create_activity(
            _activity_create(
                feishu_app_token="HKb0bhufoab2wwsblj1c9qxgnPI",
                apply_table_id="tblq63r6qdlICQaJ",
            )
        )
        return service, activity

    async def _seed_application(self, service, activity, db_session, name: str):
        employee_no = f"E{_rand()}"
        await _create_employee(db_session, name, employee_no)
        application = await service.sync_apply_record_added(
            activity.id, "rec1", _apply_fields(name, employee_no)
        )
        return application, employee_no

    async def test_updates_existing_fields_and_counts(
        self, db_session: AsyncSession, monkeypatch
    ):
        """对账应同步申报职级/现任职级等全部字段，并计入 applications_updated。"""
        from app.modules.hr.title_review import bitable_client as bc

        service, activity = await self._mk_activity(db_session, monkeypatch)
        application, employee_no = await self._seed_application(
            service, activity, db_session, "李四"
        )
        assert application.status == m.APPLICATION_SUBMITTED
        updated = _apply_fields(
            "李四", employee_no, **{"申报职级": "高级工程师", "现任职级": "工程师"}
        )
        monkeypatch.setattr(
            bc, "list_all_records",
            AsyncMock(return_value=[{"record_id": "rec1", "fields": updated}]),
        )
        stats = await service.reconcile_activity(activity.id)
        assert stats["applications_updated"] == 1
        assert stats["applications_created"] == 0
        assert stats["errors"] == []
        refreshed = await service.application_repo.get_by_feishu_record(
            activity.id, "rec1"
        )
        assert refreshed.apply_level == "高级工程师"
        assert refreshed.current_level == "工程师"

    async def test_no_change_not_counted(self, db_session: AsyncSession, monkeypatch):
        """字段无变化时不计入 applications_updated（5 分钟对账不产生噪音）。"""
        from app.modules.hr.title_review import bitable_client as bc

        service, activity = await self._mk_activity(db_session, monkeypatch)
        _, employee_no = await self._seed_application(service, activity, db_session, "李四")
        monkeypatch.setattr(
            bc, "list_all_records",
            AsyncMock(return_value=[{"record_id": "rec1", "fields": _apply_fields("李四", employee_no)}]),
        )
        stats = await service.reconcile_activity(activity.id)
        assert stats["applications_updated"] == 0
        assert stats["errors"] == []

    async def test_updates_terminal_application_info_but_keeps_votes(
        self, db_session: AsyncSession, monkeypatch
    ):
        """终态（投票通过/未通过）申报：申报信息放开更新，票数/判定结果冻结。"""
        from app.modules.hr.title_review import bitable_client as bc

        service, activity = await self._mk_activity(db_session, monkeypatch)
        application, employee_no = await self._seed_application(
            service, activity, db_session, "李四"
        )
        application.status = m.APPLICATION_PASSED
        application.agree_votes = 1
        application.oppose_votes = 0
        application.abstain_votes = 0
        await db_session.flush()
        updated = _apply_fields("李四", employee_no, **{"申报职级": "高级工程师"})
        monkeypatch.setattr(
            bc, "list_all_records",
            AsyncMock(return_value=[{"record_id": "rec1", "fields": updated}]),
        )
        stats = await service.reconcile_activity(activity.id)
        assert stats["applications_updated"] == 1
        assert stats["terminal_applications_updated"] == 1
        refreshed = await service.application_repo.get_by_feishu_record(
            activity.id, "rec1"
        )
        assert refreshed.apply_level == "高级工程师"
        # 票数与判定结果不动
        assert refreshed.status == m.APPLICATION_PASSED
        assert refreshed.agree_votes == 1

    async def test_edited_event_updates_terminal_application_info(
        self, db_session: AsyncSession, monkeypatch
    ):
        """WS 事件路径同样放开终态申报信息更新。"""
        service, activity = await self._mk_activity(db_session, monkeypatch)
        application, employee_no = await self._seed_application(
            service, activity, db_session, "李四"
        )
        application.status = m.APPLICATION_PASSED
        await db_session.flush()
        await service.sync_apply_record_edited(
            activity.id,
            "rec1",
            _apply_fields("李四", employee_no, **{"申报职级": "高级工程师"}),
        )
        refreshed = await service.application_repo.get_by_feishu_record(
            activity.id, "rec1"
        )
        assert refreshed.apply_level == "高级工程师"
        assert refreshed.status == m.APPLICATION_PASSED

    async def test_reconcile_duplicate_across_activities_not_500(
        self, db_session: AsyncSession, monkeypatch
    ):
        """申报行已归属其他活动（审批实例编号全局唯一）时记入 errors，而非 500。"""
        from app.modules.hr.title_review import bitable_client as bc

        monkeypatch.setattr(
            TitleReviewService, "_load_employee_profile", AsyncMock(return_value=None)
        )
        service = TitleReviewService(db_session)
        activity_a = await service.create_activity(
            _activity_create(feishu_app_token="app1", apply_table_id="tbl1")
        )
        activity_b = await service.create_activity(
            _activity_create(feishu_app_token="app1", apply_table_id="tbl1")
        )
        employee_no = f"E{_rand()}"
        await _create_employee(db_session, "李四", employee_no)
        rec_id = f"rec{_rand()}"
        fields = _apply_fields("李四", employee_no, **{"审批实例编号": f"CODE{_rand()}"})
        await service.sync_apply_record_added(activity_a.id, rec_id, fields)
        monkeypatch.setattr(
            bc, "list_all_records",
            AsyncMock(return_value=[{"record_id": rec_id, "fields": fields}]),
        )
        stats = await service.reconcile_activity(activity_b.id)
        assert stats["applications_created"] == 0
        assert any("重复" in err for err in stats["errors"])


async def test_bind_rejects_duplicate_apply_table(
    db_session: AsyncSession, monkeypatch
):
    """同一申报表禁止绑定多个活动：第二个活动绑定时直接 400 并说明归属。"""
    from fastapi import HTTPException

    service = TitleReviewService(db_session)
    await service.create_activity(
        _activity_create(name="活动A", feishu_app_token="app1", apply_table_id="tbl1")
    )
    activity_b = await service.create_activity(
        _activity_create(name="活动B", feishu_app_token="app1", apply_table_id="tbl1")
    )
    with pytest.raises(HTTPException) as exc_info:
        await service.bind_tables(activity_b.id)
    assert exc_info.value.status_code == 400
    assert "已绑定活动「活动A」" in str(exc_info.value.detail)


# ─── 卡片审批 ───
