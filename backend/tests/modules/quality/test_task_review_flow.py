"""复核状态机测试：自动流转待复核 + 状态转移规则（回滚式 db_session）。"""

import uuid

import pytest

from app.core.exceptions import AppException
from app.modules.quality.repository import (
    create_test_results,
    create_test_task,
    get_test_task,
    list_test_results,
)
from app.modules.quality.schemas import TestTaskStatusUpdate
from app.modules.quality.service import TestTaskService


def _row_data(**overrides) -> dict:
    data = {
        "item_name": "水分",
        "sop_no": "SOP.03.1111",
        "standard_text": "≤3.0%",
        "operator": "≤",
        "limit_min": None,
        "limit_max": 3.0,
        "judge_mode": "auto",
        "source": "manual",
    }
    data.update(overrides)
    return data


async def _make_task(db, status="in_progress", filled: bool = True):
    task = await create_test_task(
        db,
        product_name="盐酸万古霉素",
        batch_number=f"HAF2608{uuid.uuid4().hex[:4].upper()}",
        production_date="2026-09-01",
        expiry_date="2028-08-31",
        specification=None,
        form_id=None,
        standard_document_id=None,
    )
    rows = await create_test_results(db, task.id, [
        _row_data(item_name="水分"),
        _row_data(item_name="酸度", sop_no="SOP.03.2222", standard_text="3.5~4.5", operator="范围", limit_min=3.5, limit_max=4.5),
    ])
    if filled:
        for r in rows:
            r.is_pass = True
            r.result_value = 1.0
        await db.flush()
    return task


async def test_auto_advance_when_all_filled(db_session):
    task = await _make_task(db_session, filled=True)
    advanced = await TestTaskService.auto_advance_pending_review(db_session, task.id)
    assert advanced is True
    fresh = await get_test_task(db_session, task.id)
    assert fresh.status == "pending_review"


async def test_no_advance_when_unfilled(db_session):
    task = await _make_task(db_session, filled=False)
    advanced = await TestTaskService.auto_advance_pending_review(db_session, task.id)
    assert advanced is False
    fresh = await get_test_task(db_session, task.id)
    assert fresh.status == "in_progress"


async def test_review_requires_two_distinct_reviewers(db_session):
    task = await _make_task(db_session)
    await TestTaskService.auto_advance_pending_review(db_session, task.id)
    reviewer_a = uuid.uuid4()
    # 第一人通过：仍待复核
    detail1, approved1, advanced1 = await TestTaskService.add_review(
        db_session, task.id, reviewer_a, "首次复核"
    )
    assert approved1 == 1 and advanced1 is False
    assert detail1.status == "pending_review"
    # 同一人重复通过：拒绝
    with pytest.raises(AppException):
        await TestTaskService.add_review(db_session, task.id, reviewer_a, "再来一次")
    # 第二人（不同）通过：转完成
    detail2, approved2, advanced2 = await TestTaskService.add_review(
        db_session, task.id, uuid.uuid4(), "复核通过"
    )
    assert approved2 == 2 and advanced2 is True
    assert detail2.status == "completed"


async def test_review_same_reviewer_not_counted(db_session):
    task = await _make_task(db_session)
    await TestTaskService.auto_advance_pending_review(db_session, task.id)
    reviewer = uuid.uuid4()
    await TestTaskService.add_review(db_session, task.id, reviewer, None)
    with pytest.raises(AppException):
        await TestTaskService.add_review(db_session, task.id, reviewer, None)


async def test_direct_complete_from_review_rejected(db_session):
    """完成只能经双人复核接口，直接改状态应被拒绝。"""
    task = await _make_task(db_session)
    await TestTaskService.auto_advance_pending_review(db_session, task.id)
    with pytest.raises(AppException):
        await TestTaskService.update_status(
            db_session, task.id, TestTaskStatusUpdate(status="completed")
        )


async def test_reject_transition_removed(db_session):
    """驳回链路已删除（专员复核时直接改结果），pending_review→in_progress 应被拒绝。"""
    task = await _make_task(db_session)
    await TestTaskService.auto_advance_pending_review(db_session, task.id)
    with pytest.raises(AppException):
        await TestTaskService.update_status(
            db_session, task.id, TestTaskStatusUpdate(status="in_progress")
        )


async def test_completed_reopen(db_session):
    task = await _make_task(db_session)
    await TestTaskService.auto_advance_pending_review(db_session, task.id)
    await TestTaskService.add_review(db_session, task.id, uuid.uuid4(), None)
    await TestTaskService.add_review(db_session, task.id, uuid.uuid4(), None)
    detail = await TestTaskService.update_status(
        db_session, task.id, TestTaskStatusUpdate(status="in_progress")
    )
    assert detail.status == "in_progress"


async def test_illegal_direct_complete_rejected(db_session):
    task = await _make_task(db_session, filled=True)
    with pytest.raises(AppException):
        await TestTaskService.update_status(
            db_session, task.id, TestTaskStatusUpdate(status="completed")
        )


async def test_manual_pending_review_requires_all_filled(db_session):
    task = await _make_task(db_session, filled=False)
    with pytest.raises(AppException):
        await TestTaskService.update_status(
            db_session, task.id, TestTaskStatusUpdate(status="pending_review")
        )


async def test_void_from_pending_review(db_session):
    task = await _make_task(db_session)
    await TestTaskService.auto_advance_pending_review(db_session, task.id)
    detail = await TestTaskService.update_status(
        db_session, task.id, TestTaskStatusUpdate(status="void")
    )
    assert detail.status == "void"


async def test_results_preserved_after_advance(db_session):
    task = await _make_task(db_session)
    await TestTaskService.auto_advance_pending_review(db_session, task.id)
    rows = await list_test_results(db_session, task.id)
    assert len(rows) == 2


