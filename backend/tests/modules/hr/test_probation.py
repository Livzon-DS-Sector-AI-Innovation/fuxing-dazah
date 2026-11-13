"""试用期转正评估测试：computed 倒计时 / 发起 / 卡片回调 / HR 确认生效（写源表）/ 取消 / 到期提醒。

回调（handle_review_submit）走独立 session factory，按根 conftest 约定
用 _test_session_factory 真实 commit 并自行清理。
"""

import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete

from app.modules.hr.models import Employee, ProbationReview
from app.modules.hr.probation_service import (
    CARD_ACTION,
    cancel_review,
    create_review,
    finalize_review,
    handle_review_submit,
)
from tests.conftest import _test_session_factory
from tests.modules.hr.conftest import _rand


def _mk_probation_employee(db, *, hire_date: date | None = None,
                           probation_end: date | None = None) -> Employee:
    e = Employee(
        name=_rand("试用期员工"), employee_number=_rand("PB"),
        department="QC部", position="QC工程师",
        hire_date=hire_date or date.today() - timedelta(days=83),  # 3月期剩约7天
        status="试用期", status_category="试用期",
        probation_end_date=probation_end,
        feishu_record_id="rec_pb_1",
    )
    db.add(e)
    return e


def _ready_config():
    from app.modules.hr.employee_sync.config import EmployeeSyncConfig

    return EmployeeSyncConfig(enabled=True, app_token="app_x", source_table_id="tbl_y")


# ─── computed 派生 ───


def test_computed_probation_end_derived():
    hire = date(2026, 8, 15)
    e = Employee(name="x", employee_number="x1", department="d", position="p",
                 hire_date=hire, status="试用期", status_category="试用期")
    # 入职+3月-1天（与 document_generator 口径一致）
    assert e.computed_probation_end == date(2026, 11, 14)
    assert e.computed_probation_days_left is not None


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


async def test_create_review_sends_card(db_session):
    e = _mk_probation_employee(db_session)
    await db_session.flush()
    with (
        patch("app.modules.hr.feishu_review_service._lookup_open_id",
              new=AsyncMock(return_value="ou_rev_1")),
        patch("app.modules.hr.probation_service._send_card", new=AsyncMock(return_value=True)) as mock_send,
    ):
        review = await create_review(db_session, e.id, "王负责人", operator="HR")

    assert review.status == "pending_reviewer"
    assert review.reviewer_open_id == "ou_rev_1"
    card = mock_send.await_args.args[1]
    assert card["header"]["title"]["content"] == "试用期转正评估"
    form = next(el for el in card["body"]["elements"] if el.get("tag") == "form")
    btn = next(el for el in form["elements"] if el.get("action_type") == "form_submit")
    assert btn["value"]["action"] == CARD_ACTION


async def test_create_review_rejects_non_probation(db_session):
    e = Employee(name=_rand("在职"), employee_number=_rand("E"), department="d", position="p",
                 hire_date=date.today(), status="在职", status_category="正式")
    db_session.add(e)
    await db_session.flush()

    with pytest.raises(ValueError, match="仅试用期员工"):
        await create_review(db_session, e.id, "王负责人", operator="HR")


async def test_create_review_rejects_reviewer_without_open_id(db_session):
    e = _mk_probation_employee(db_session)
    await db_session.flush()
    with patch("app.modules.hr.feishu_review_service._lookup_open_id",
               new=AsyncMock(return_value=None)):
        with pytest.raises(ValueError, match="评估人"):
            await create_review(db_session, e.id, "查无此人", operator="HR")


async def test_create_review_rejects_duplicate(db_session):
    e = _mk_probation_employee(db_session)
    await db_session.flush()
    db_session.add(ProbationReview(employee_id=e.id, reviewer_name="王负责人",
                                   reviewer_open_id="ou_rev_1"))
    await db_session.flush()

    with (
        patch("app.modules.hr.feishu_review_service._lookup_open_id",
              new=AsyncMock(return_value="ou_rev_1")),
        patch("app.modules.hr.probation_service._send_card", new=AsyncMock(return_value=True)),
    ):
        with pytest.raises(ValueError, match="进行中"):
            await create_review(db_session, e.id, "王负责人", operator="HR")


# ─── 卡片提交回调（独立 factory 真实 commit + 自行清理） ───


async def _setup_callback_case() -> tuple[uuid.UUID, uuid.UUID]:
    """独立 factory 造员工+评估记录（回调内部自开 session，须真实可见）。"""
    async with _test_session_factory() as s:
        e = _mk_probation_employee(s)
        await s.flush()
        r = ProbationReview(id=uuid.uuid4(), employee_id=e.id, reviewer_name="王负责人",
                            reviewer_open_id="ou_rev_1")
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


def _payload(rid: uuid.UUID, form: dict, open_id: str = "ou_rev_1") -> dict:
    return {"action": CARD_ACTION, "review_id": str(rid), "_open_id": open_id, "_form_value": form}


async def test_review_submit_ok():
    rid, eid = await _setup_callback_case()
    try:
        with patch("app.core.database.async_session_factory", _test_session_factory):
            result = await handle_review_submit(_payload(rid, {
                "conclusion": "通过", "comment": "表现良好，同意转正",
            }), "u1")
        assert result == {"toast": {"type": "success", "content": "评估已提交，等待人事确认"}}
        async with _test_session_factory() as s:
            r = await s.get(ProbationReview, rid)
            assert r is not None
            assert r.status == "pending_hr" and r.conclusion == "通过"
    finally:
        await _cleanup_case(rid, eid)


async def test_review_submit_rejects_wrong_open_id():
    rid, eid = await _setup_callback_case()
    try:
        with patch("app.core.database.async_session_factory", _test_session_factory):
            result = await handle_review_submit(_payload(rid, {
                "conclusion": "通过", "comment": "x",
            }, open_id="ou_someone_else"), "u2")
        assert result["toast"]["type"] == "error"
        async with _test_session_factory() as s:
            r = await s.get(ProbationReview, rid)
            assert r is not None
            assert r.status == "pending_reviewer"  # 未被篡改
    finally:
        await _cleanup_case(rid, eid)


async def test_review_submit_rejects_bad_conclusion(db_session):
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
            # 合法新日期 → success
            new_end = (date.today() + timedelta(days=60)).isoformat()
            r3 = await handle_review_submit(_payload(rid, {
                "conclusion": "延长", "comment": "再观察", "proposed_probation_end": new_end,
            }), "u4")
            assert r3["toast"]["type"] == "success"
        async with _test_session_factory() as s:
            r = await s.get(ProbationReview, rid)
            assert r is not None
            assert r.proposed_probation_end == date.fromisoformat(new_end)
    finally:
        await _cleanup_case(rid, eid)


# ─── HR 确认生效 ───


async def _mk_pending_hr(db, conclusion: str, proposed: date | None = None) -> tuple[ProbationReview, Employee]:
    e = _mk_probation_employee(db)
    await db.flush()
    r = ProbationReview(employee_id=e.id, reviewer_name="王负责人", reviewer_open_id="ou_rev_1")
    r.status = "pending_hr"
    r.conclusion = conclusion
    r.comment = "评语"
    r.proposed_probation_end = proposed
    db.add(r)
    await db.flush()
    return r, e


async def test_finalize_pass_writes_source_and_local(db_session):
    r, e = await _mk_pending_hr(db_session, "通过")
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
    r, e = await _mk_pending_hr(db_session, "延长", proposed=new_end)
    with patch("app.modules.hr.probation_service._send_card", new=AsyncMock(return_value=True)):
        result = await finalize_review(db_session, r.id, hr_note=None, reviewer="HR张")

    assert result["extended_to"] == new_end.isoformat()
    assert e.probation_end_date == new_end
    assert e.status == "试用期"  # 状态不变，到期重走一轮
    assert r.status == "effective"


async def test_finalize_requires_pending_hr(db_session):
    r, e = await _mk_pending_hr(db_session, "通过")
    r.status = "pending_reviewer"  # 退回待评估
    await db_session.flush()
    with pytest.raises(ValueError, match="待HR确认"):
        await finalize_review(db_session, r.id, hr_note=None, reviewer="HR张")


async def test_cancel_review(db_session):
    e = _mk_probation_employee(db_session)
    await db_session.flush()
    r = ProbationReview(employee_id=e.id, reviewer_name="王负责人", reviewer_open_id="ou_rev_1")
    db_session.add(r)
    await db_session.flush()
    await cancel_review(db_session, r.id, operator="HR张")
    assert r.status == "cancelled"
    with pytest.raises(ValueError, match="进行中"):
        await cancel_review(db_session, r.id, operator="HR张")


# ─── 到期提醒扫描 ───


async def test_reminder_scan_skips_active_reviews(db_session, monkeypatch):
    from app.core.config import get_settings
    from app.modules.hr.probation_scheduled import run_probation_reminder

    # 未配置接收人：仅日志不推送（不炸即过）
    monkeypatch.setattr(get_settings(), "HR_PROBATION_REMINDER_OPEN_IDS", "")
    e = _mk_probation_employee(db_session)
    await db_session.flush()
    # 有进行中评估 → 不在提醒列表（靠日志覆盖，这里主要验证任务可运行）
    db_session.add(ProbationReview(employee_id=e.id, reviewer_name="王负责人",
                                   reviewer_open_id="ou_rev_1"))
    await db_session.flush()
    await run_probation_reminder()  # 无接收人，静默通过


# ─── API ───


async def test_api_create_and_list(client, db_session):
    e = _mk_probation_employee(db_session)
    await db_session.flush()
    with (
        patch("app.modules.hr.feishu_review_service._lookup_open_id",
              new=AsyncMock(return_value="ou_rev_1")),
        patch("app.modules.hr.probation_service._send_card", new=AsyncMock(return_value=True)),
    ):
        res = await client.post("/api/v1/hr/probation-reviews", json={
            "employee_id": str(e.id), "reviewer_name": "王负责人",
        })
    assert res.status_code == 200, res.text

    lst = await client.get("/api/v1/hr/probation-reviews?status=pending_reviewer")
    rows = lst.json()["data"]
    mine = [x for x in rows if x["employee_name"] == e.name]
    assert mine and mine[0]["reviewer_name"] == "王负责人"
    assert mine[0]["probation_end"]  # 列表含到期日
