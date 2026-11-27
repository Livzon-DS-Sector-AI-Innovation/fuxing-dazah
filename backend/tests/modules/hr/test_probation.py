"""试用期转正评估测试：computed 倒计时 / 三级审批链 / 卡片回调 / 兜底生效 / 取消 / 提醒扫描。

回调（handle_review_submit）走独立 session factory，按根 conftest 约定
用 _test_session_factory 真实 commit 并自行清理。
"""

import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete

from app.modules.hr import probation_config
from app.modules.hr.models import Employee, HrDepartment, ProbationReview
from app.modules.hr.probation_service import (
    CARD_ACTION_SUBMIT,
    cancel_review,
    create_review,
    finalize_review,
    handle_review_submit,
)
from tests.conftest import _test_session_factory
from tests.modules.hr.conftest import _rand


@pytest.fixture(autouse=True)
def _fixed_duration_cache():
    """锁定时长缓存（一般3/重点6），隔离 system_settings 里的运行值。"""
    original = dict(probation_config._cache)
    probation_config._cache = {"standard": 3, "key_position": 6}
    yield
    probation_config._cache = original


def _mk_probation_employee(db, *, hire_date: date | None = None,
                           probation_end: date | None = None,
                           is_key_position: bool | None = None,
                           department: str = "QC部") -> Employee:
    e = Employee(
        name=_rand("试用期员工"), employee_number=_rand("PB"),
        department=department, position="QC工程师",
        hire_date=hire_date or date.today() - timedelta(days=83),  # 3月期剩约7天
        status="试用期", status_category="试用期",
        probation_end_date=probation_end,
        is_key_position=is_key_position,
        direct_manager_name="王直属",
        feishu_record_id="rec_pb_1",
    )
    db.add(e)
    return e


def _mk_department(db, name: str = "QC部") -> HrDepartment:
    d = HrDepartment(
        name=name, code=_rand("DEPT"),
        department_manager_name="李经理", supervising_leader_name="赵领导",
    )
    db.add(d)
    return d


def _ready_config():
    from app.modules.hr.employee_sync.config import EmployeeSyncConfig

    return EmployeeSyncConfig(enabled=True, app_token="app_x", source_table_id="tbl_y")


# ─── computed 派生 ───


def test_computed_probation_end_derived():
    hire = date(2026, 8, 15)
    e = Employee(name="x", employee_number="x1", department="d", position="p",
                 hire_date=hire, status="试用期", status_category="试用期")
    # 一般岗位：入职+3月-1天
    assert e.computed_probation_end == date(2026, 11, 14)
    assert e.computed_probation_days_left is not None


def test_computed_probation_end_key_position_six_months():
    hire = date(2026, 5, 1)
    e = Employee(name="x", employee_number="x1b", department="d", position="p",
                 hire_date=hire, status="试用期", status_category="试用期",
                 is_key_position=True)
    # 重点岗位：入职+6月-1天
    assert e.computed_probation_end == date(2026, 10, 31)


def test_computed_probation_explicit_and_non_probation():
    hire = date(2026, 1, 1)
    e = Employee(name="x", employee_number="x2", department="d", position="p",
                 hire_date=hire, status="试用期", status_category="实习转试用",
                 probation_end_date=date(2026, 12, 31))
    assert e.computed_probation_end == date(2026, 12, 31)  # 显式值优先

    e2 = Employee(name="y", employee_number="x3", department="d", position="p",
                  hire_date=hire, status="在职", status_category="正式")
    assert e2.computed_probation_end is None
    assert e2.computed_probation_days_left is None


# ─── 发起 ───


def _patch_approvers():
    """姓名→open_id 解析：三个审批人各有独立 open_id。"""
    async def _fake_lookup(name: str) -> str | None:
        return {"王直属": "ou_dm", "李经理": "ou_dept", "赵领导": "ou_leader"}.get(name)

    return patch("app.modules.hr.feishu_review_service._lookup_open_id", new=_fake_lookup)


async def test_create_review_resolves_three_approvers(db_session):
    e = _mk_probation_employee(db_session)
    _mk_department(db_session)
    await db_session.flush()
    with (
        _patch_approvers(),
        patch("app.modules.hr.probation_service._send_card", new=AsyncMock(return_value=True)) as mock_send,
    ):
        review = await create_review(db_session, e.id, operator="HR")

    assert review.status == "pending_step1"
    assert review.direct_manager_open_id == "ou_dm"
    assert review.dept_manager_open_id == "ou_dept"
    assert review.leader_open_id == "ou_leader"
    card = mock_send.await_args.args[1]
    assert card["header"]["title"]["content"] == "试用期转正评估"
    form = next(el for el in card["body"]["elements"] if el.get("tag") == "form")
    btn = next(el for el in form["elements"] if el.get("action_type") == "form_submit")
    assert btn["value"]["action"] == CARD_ACTION_SUBMIT
    assert btn["value"]["step"] == 1


async def test_create_review_requires_direct_manager(db_session):
    e = _mk_probation_employee(db_session)
    e.direct_manager_name = None
    _mk_department(db_session)
    await db_session.flush()
    with pytest.raises(ValueError, match="直属上级"):
        await create_review(db_session, e.id, operator="HR")


async def test_create_review_requires_department_approvers(db_session):
    e = _mk_probation_employee(db_session)
    # 造一个没配审批人的部门
    db_session.add(HrDepartment(name="无配置部", code=_rand("DEPT")))
    e.department = "无配置部"
    await db_session.flush()
    with pytest.raises(ValueError, match="未配置部门负责人"):
        await create_review(db_session, e.id, operator="HR")


async def test_create_review_rejects_non_probation(db_session):
    e = Employee(name=_rand("在职"), employee_number=_rand("E"), department="d", position="p",
                 hire_date=date.today(), status="在职", status_category="正式")
    db_session.add(e)
    await db_session.flush()

    with pytest.raises(ValueError, match="仅试用期员工"):
        await create_review(db_session, e.id, operator="HR")


async def test_create_review_rejects_key_position_without_exam(db_session):
    from app.modules.hr.models import ProbationSafetyExam

    e = _mk_probation_employee(db_session, is_key_position=True)
    _mk_department(db_session)
    await db_session.flush()
    with pytest.raises(ValueError, match="安全考试"):
        await create_review(db_session, e.id, operator="HR")

    # 补一条合格记录后可发起
    db_session.add(ProbationSafetyExam(
        employee_id=e.id, exam_date=date.today(), passed=True,
    ))
    await db_session.flush()
    with (
        _patch_approvers(),
        patch("app.modules.hr.probation_service._send_card", new=AsyncMock(return_value=True)),
    ):
        review = await create_review(db_session, e.id, operator="HR")
    assert review.status == "pending_step1"


async def test_create_review_rejects_duplicate(db_session):
    e = _mk_probation_employee(db_session)
    _mk_department(db_session)
    await db_session.flush()
    db_session.add(ProbationReview(
        employee_id=e.id, current_step=1,
        direct_manager_name="王直属", direct_manager_open_id="ou_dm",
    ))
    await db_session.flush()

    with (
        _patch_approvers(),
        patch("app.modules.hr.probation_service._send_card", new=AsyncMock(return_value=True)),
    ):
        with pytest.raises(ValueError, match="进行中"):
            await create_review(db_session, e.id, operator="HR")


# ─── 三级卡片提交回调（独立 factory 真实 commit + 自行清理） ───


async def _setup_callback_case(*, key_position: bool | None = None) -> tuple[uuid.UUID, uuid.UUID]:
    """独立 factory 造员工+三级评估记录（回调内部自开 session，须真实可见）。"""
    async with _test_session_factory() as s:
        e = _mk_probation_employee(s, is_key_position=key_position)
        await s.flush()
        r = ProbationReview(
            id=uuid.uuid4(), employee_id=e.id, current_step=1,
            direct_manager_name="王直属", direct_manager_open_id="ou_dm",
            dept_manager_name="李经理", dept_manager_open_id="ou_dept",
            leader_name="赵领导", leader_open_id="ou_leader",
        )
        s.add(r)
        await s.commit()
        return r.id, e.id


async def _cleanup_case(review_id: uuid.UUID, employee_id: uuid.UUID) -> None:
    async with _test_session_factory() as s:
        r = await s.get(ProbationReview, review_id)
        if r is not None:
            await s.delete(r)
            await s.flush()
        e = await s.get(Employee, employee_id)
        if e is not None:
            await s.delete(e)
        await s.commit()


def _payload(rid: uuid.UUID, form: dict, open_id: str = "ou_dm", step: int = 1) -> dict:
    return {"action": CARD_ACTION_SUBMIT, "review_id": str(rid),
            "step": step, "_open_id": open_id, "_form_value": form}


def _patch_source_write(ok: bool = True):
    """mock 源表回写链路；ok=False 时 update_record 抛错模拟回写失败。"""
    fields = [{"field_name": n} for n in ("员工性质", "人员状态")]

    async def _maybe_update(*args, **kwargs):
        if not ok:
            raise RuntimeError("feishu down")

    update_mock = AsyncMock(side_effect=_maybe_update)
    return (
        patch("app.modules.hr.employee_sync.config.load_config",
              new=AsyncMock(return_value=_ready_config())),
        patch("app.platform.integrations.feishu.bitable.list_fields",
              new=AsyncMock(return_value=fields)),
        patch("app.platform.integrations.feishu.bitable.update_record", new=update_mock),
    )


async def test_three_step_approval_flow_auto_effectuates():
    """三级依次同意 → 自动生效（源表回写 + 本地状态更新）。"""
    rid, eid = await _setup_callback_case()
    try:
        cfg, fields, update = _patch_source_write()
        with patch("app.core.database.async_session_factory", _test_session_factory), \
                patch("app.modules.hr.probation_service._send_card", new=AsyncMock(return_value=True)), \
                cfg, fields, update as mock_update:
            r1 = await handle_review_submit(_payload(rid, {
                "conclusion": "通过", "comment": "表现良好",
            }), "u1")
            assert r1["toast"]["type"] == "success"
            r2 = await handle_review_submit(_payload(rid, {
                "decision": "同意", "comment": "同意",
            }, open_id="ou_dept", step=2), "u2")
            assert r2["toast"]["type"] == "success"
            r3 = await handle_review_submit(_payload(rid, {
                "decision": "同意", "comment": "同意",
            }, open_id="ou_leader", step=3), "u3")
            assert "自动转正生效" in r3["toast"]["content"]
            # 源表写「员工性质」=正式
            payload = mock_update.await_args.kwargs.get("fields") or mock_update.await_args.args[3]
            assert payload == {"员工性质": "正式"}

        async with _test_session_factory() as s:
            r = await s.get(ProbationReview, rid)
            e = await s.get(Employee, eid)
            assert r.status == "effective" and r.current_step == 3
            assert r.dept_manager_decision == "同意" and r.leader_decision == "同意"
            assert e.status == "在职" and e.status_category == "正式"
    finally:
        await _cleanup_case(rid, eid)


async def test_step3_source_write_failure_keeps_pending_step3():
    """第三级同意但源表回写失败 → 决策已落库、停留 pending_step3（HR 兜底入口）。"""
    rid, eid = await _setup_callback_case()
    try:
        with patch("app.core.database.async_session_factory", _test_session_factory), \
                patch("app.modules.hr.probation_service._send_card", new=AsyncMock(return_value=True)):
            await handle_review_submit(_payload(rid, {
                "conclusion": "通过", "comment": "ok",
            }), "u1")
            await handle_review_submit(_payload(rid, {
                "decision": "同意", "comment": "ok",
            }, open_id="ou_dept", step=2), "u2")

            cfg, fields, update = _patch_source_write(ok=False)
            with cfg, fields, update:
                r3 = await handle_review_submit(_payload(rid, {
                    "decision": "同意", "comment": "ok",
                }, open_id="ou_leader", step=3), "u3")
            assert r3["toast"]["type"] == "error"
            assert "确认生效" in r3["toast"]["content"]

        async with _test_session_factory() as s:
            r = await s.get(ProbationReview, rid)
            e = await s.get(Employee, eid)
            # 决策保留、未生效
            assert r.status == "pending_step3"
            assert r.leader_decision == "同意"
            assert e.status == "试用期"
    finally:
        await _cleanup_case(rid, eid)


async def test_step1_fail_short_circuits_to_rejected():
    rid, eid = await _setup_callback_case()
    try:
        with patch("app.core.database.async_session_factory", _test_session_factory):
            result = await handle_review_submit(_payload(rid, {
                "conclusion": "不通过", "comment": "不胜任",
            }), "u1")
        assert "不通过" in result["toast"]["content"]
        async with _test_session_factory() as s:
            r = await s.get(ProbationReview, rid)
            assert r.status == "rejected"
    finally:
        await _cleanup_case(rid, eid)


async def test_step2_return_rejects():
    rid, eid = await _setup_callback_case()
    try:
        with patch("app.core.database.async_session_factory", _test_session_factory), \
                patch("app.modules.hr.probation_service._send_card", new=AsyncMock(return_value=True)):
            await handle_review_submit(_payload(rid, {
                "conclusion": "通过", "comment": "ok",
            }), "u1")
            result = await handle_review_submit(_payload(rid, {
                "decision": "退回", "comment": "材料不足",
            }, open_id="ou_dept", step=2), "u2")
        assert result["toast"]["type"] == "success"
        async with _test_session_factory() as s:
            r = await s.get(ProbationReview, rid)
            assert r.status == "rejected" and r.dept_manager_decision == "退回"
    finally:
        await _cleanup_case(rid, eid)


async def test_review_submit_rejects_wrong_open_id():
    """防代填：step1 必须直属上级本人 open_id。"""
    rid, eid = await _setup_callback_case()
    try:
        with patch("app.core.database.async_session_factory", _test_session_factory):
            result = await handle_review_submit(_payload(rid, {
                "conclusion": "通过", "comment": "x",
            }, open_id="ou_dept"), "u2")  # 部门经理代填 → 拒绝
        assert result["toast"]["type"] == "error"
        async with _test_session_factory() as s:
            r = await s.get(ProbationReview, rid)
            assert r is not None
            assert r.status == "pending_step1"  # 未被篡改
    finally:
        await _cleanup_case(rid, eid)


async def test_review_submit_rejects_bad_conclusion():
    rid, eid = await _setup_callback_case()
    try:
        with patch("app.core.database.async_session_factory", _test_session_factory):
            result = await handle_review_submit(_payload(rid, {
                "conclusion": "优秀", "comment": "x",
            }), "u3")
        assert "通过 / 延长 / 不通过" in result["toast"]["content"]
    finally:
        await _cleanup_case(rid, eid)


async def test_review_submit_extension_requires_later_date():
    rid, eid = await _setup_callback_case()
    try:
        with patch("app.core.database.async_session_factory", _test_session_factory):
            # 无新日期 → error
            r1 = await handle_review_submit(_payload(rid, {
                "conclusion": "延长", "comment": "再观察",
            }), "u4")
            assert r1["toast"]["type"] == "error"
            # 新日期早于当前到期日 → error
            r2 = await handle_review_submit(_payload(rid, {
                "conclusion": "延长", "comment": "再观察", "proposed_probation_end": "2020-01-01",
            }), "u4")
            assert r2["toast"]["type"] == "error"
            # 合法新日期 → success（流转 step2）
            new_end = (date.today() + timedelta(days=60)).isoformat()
            r3 = await handle_review_submit(_payload(rid, {
                "conclusion": "延长", "comment": "再观察", "proposed_probation_end": new_end,
            }), "u4")
            assert r3["toast"]["type"] == "success"
        async with _test_session_factory() as s:
            r = await s.get(ProbationReview, rid)
            assert r is not None
            assert r.proposed_probation_end == date.fromisoformat(new_end)
            assert r.status == "pending_step2"
    finally:
        await _cleanup_case(rid, eid)


# ─── HR 兜底生效 ───


async def _mk_step3_review(db, conclusion: str, proposed: date | None = None) -> tuple[ProbationReview, Employee]:
    e = _mk_probation_employee(db)
    await db.flush()
    r = ProbationReview(
        employee_id=e.id, current_step=3,
        direct_manager_name="王直属", direct_manager_open_id="ou_dm",
        dept_manager_name="李经理", dept_manager_open_id="ou_dept",
        leader_name="赵领导", leader_open_id="ou_leader",
    )
    r.status = "pending_step3"
    r.conclusion = conclusion
    r.comment = "评语"
    r.proposed_probation_end = proposed
    db.add(r)
    await db.flush()
    return r, e


async def test_finalize_pass_writes_source_and_local(db_session):
    r, e = await _mk_step3_review(db_session, "通过")
    fields = [{"field_name": n} for n in ("员工性质", "人员状态")]
    with (
        patch("app.modules.hr.employee_sync.config.load_config",
              new=AsyncMock(return_value=_ready_config())),
        patch("app.platform.integrations.feishu.bitable.list_fields",
              new=AsyncMock(return_value=fields)),
        patch("app.platform.integrations.feishu.bitable.update_record", new=AsyncMock()) as mock_update,
        patch("app.modules.hr.probation_service._send_card", new=AsyncMock(return_value=True)),
    ):
        result = await finalize_review(db_session, r.id, hr_note=None, reviewer="HR张")

    assert result["conclusion"] == "通过"
    # 源表写「员工性质」=正式
    payload = mock_update.await_args.kwargs.get("fields") or mock_update.await_args.args[3]
    assert payload == {"员工性质": "正式"}
    assert mock_update.await_args.args[2] == "rec_pb_1"
    # 本地三字段同值预更新 + 到期日定格（= 入职+3月-1天；转正后 computed 返回 None 属预期）
    assert e.status_category == "正式"
    assert e.status == "在职"
    from dateutil.relativedelta import relativedelta

    assert e.probation_end_date == e.hire_date + relativedelta(months=3, days=-1)
    assert r.status == "effective"


async def test_finalize_extension_updates_end_date_only(db_session):
    new_end = date.today() + timedelta(days=60)
    r, e = await _mk_step3_review(db_session, "延长", proposed=new_end)
    with patch("app.modules.hr.probation_service._send_card", new=AsyncMock(return_value=True)):
        result = await finalize_review(db_session, r.id, hr_note=None, reviewer="HR张")

    assert result["extended_to"] == new_end.isoformat()
    assert e.probation_end_date == new_end
    assert e.status == "试用期"  # 状态不变，到期重走一轮
    assert r.status == "effective"


async def test_finalize_requires_active_and_conclusion(db_session):
    r, e = await _mk_step3_review(db_session, "通过")
    r.status = "cancelled"  # 已完结
    await db_session.flush()
    with pytest.raises(ValueError, match="进行中"):
        await finalize_review(db_session, r.id, hr_note=None, reviewer="HR张")

    # step1 未提交结论也不可生效
    e2 = _mk_probation_employee(db_session, department="QC二部")
    await db_session.flush()
    r2 = ProbationReview(
        employee_id=e2.id, current_step=1,
        direct_manager_name="王直属", direct_manager_open_id="ou_dm",
    )
    db_session.add(r2)
    await db_session.flush()
    with pytest.raises(ValueError, match="尚未提交"):
        await finalize_review(db_session, r2.id, hr_note=None, reviewer="HR张")


async def test_cancel_review(db_session):
    e = _mk_probation_employee(db_session)
    await db_session.flush()
    r = ProbationReview(
        employee_id=e.id, current_step=1,
        direct_manager_name="王直属", direct_manager_open_id="ou_dm",
    )
    db_session.add(r)
    await db_session.flush()
    await cancel_review(db_session, r.id, operator="HR张")
    assert r.status == "cancelled"
    with pytest.raises(ValueError, match="进行中"):
        await cancel_review(db_session, r.id, operator="HR张")


# ─── 提醒扫描 ───


async def test_reminder_scan_runs_silently(db_session, monkeypatch):
    from app.modules.hr import probation_scheduled
    from app.modules.hr.probation_scheduled import run_probation_reminder

    # 未配置接收人（KV 缺省为空）：仅日志不推送（不炸即过）
    async def _no_receivers(db):
        return []

    monkeypatch.setattr(probation_scheduled, "_load_reminder_open_ids", _no_receivers)
    e = _mk_probation_employee(db_session)
    await db_session.flush()
    # 有进行中评估 → 三段扫描均不触发推送
    db_session.add(ProbationReview(
        employee_id=e.id, current_step=1,
        direct_manager_name="王直属", direct_manager_open_id="ou_dm",
    ))
    await db_session.flush()
    await run_probation_reminder()  # 无接收人，静默通过


# ─── API ───


async def test_api_create_and_list(client, db_session):
    e = _mk_probation_employee(db_session)
    _mk_department(db_session)
    await db_session.flush()
    with (
        _patch_approvers(),
        patch("app.modules.hr.probation_service._send_card", new=AsyncMock(return_value=True)),
    ):
        res = await client.post("/api/v1/hr/probation-reviews", json={
            "employee_id": str(e.id),
        })
    assert res.status_code == 200, res.text

    lst = await client.get("/api/v1/hr/probation-reviews?status=pending_step1")
    rows = lst.json()["data"]
    mine = [x for x in rows if x["employee_name"] == e.name]
    assert mine and mine[0]["direct_manager_name"] == "王直属"
    assert mine[0]["status_label"] == "直属上级待评"
    assert mine[0]["probation_end"]  # 列表含到期日


# ─── 清理测试造的部门配置行（防 code 唯一冲突累积） ───


async def test_cleanup_departments(db_session):
    await db_session.execute(
        delete(HrDepartment).where(HrDepartment.department_manager_name == "李经理")
    )
