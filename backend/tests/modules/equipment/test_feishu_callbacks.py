"""设备模块飞书验收回调（feishu/callbacks）测试。

验证从平台 event_handler 迁入的回调业务逻辑：
approve/reject 验收路径，以及工单缺失、状态错误、用户缺失、未知 action 的兜底。
"""

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.modules.equipment.feishu.callbacks as callbacks_mod
from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.models import Equipment, Location, WorkOrder
from app.modules.equipment.schemas import WorkOrderComplete, WorkOrderCreate
from app.modules.equipment.service import (
    assign_work_order,
    complete_work_order,
    create_work_order,
    start_work_order,
)
from app.platform.identity.models import User


def _uid() -> str:
    """共享库唯一后缀，避免唯一键冲突。"""
    return uuid.uuid4().hex[:8]


def _sent_title(card_mock: AsyncMock) -> str:
    """最近一次发卡调用的 title。"""
    assert card_mock.await_args is not None
    return str(card_mock.await_args.kwargs["title"])


@pytest.fixture
async def reporter(db_session: AsyncSession) -> User:
    """报修人。"""
    user = User(name="回调报修人", employee_no=f"EMP-R-{_uid()}")
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def equipment(db_session: AsyncSession) -> Equipment:
    """完好设备。"""
    location = Location(name="回调车间", code=f"WS-{_uid()}")
    db_session.add(location)
    await db_session.flush()

    eq = Equipment(
        equipment_no=f"EQ-{_uid()}",
        name="回调反应釜",
        location_id=location.id,
        status="完好",
    )
    db_session.add(eq)
    await db_session.flush()
    return eq


@pytest.fixture
def isolated_callbacks(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[AsyncMock]:
    """回调内部会话替换为测试会话，commit 与发卡全部 mock。

    沿用 hr/test_title_review_sync 的惯例：handler 用生产
    async_session_factory 开会话，测试中替换为当前测试会话，
    使未 commit 的测试数据可见，并 mock commit 阻止测试数据落库。
    """
    @asynccontextmanager
    async def _fake_factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(callbacks_mod, "async_session_factory", _fake_factory)
    monkeypatch.setattr(db_session, "commit", AsyncMock())
    card_mock = AsyncMock()
    monkeypatch.setattr(callbacks_mod, "send_user_card", card_mock)
    yield card_mock


async def _wo_at_acceptance(
    db_session: AsyncSession,
    equipment: Equipment,
    reporter: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> WorkOrder:
    """创建并推进到「待验收」的工单。"""
    assignee = User(name="回调维修员", employee_no=f"EMP-A-{_uid()}")
    db_session.add(assignee)
    await db_session.flush()

    ctx = make_access_ctx(reporter)
    data = WorkOrderCreate(
        equipment_id=equipment.id,
        responsible_person_id=reporter.id,
    )
    wo = await create_work_order(db_session, data, ctx)
    wo = await assign_work_order(db_session, wo.id, assignee.id, ctx)
    wo = await start_work_order(db_session, wo.id, ctx)
    wo = await complete_work_order(
        db_session, wo.id, WorkOrderComplete(repair_detail="回调维修"), ctx,
    )
    return wo


async def _verifier(db_session: AsyncSession) -> User:
    """带 feishu_user_id 的验收人。"""
    user = User(
        name="回调验收员", employee_no=f"EMP-V-{_uid()}",
        feishu_user_id=f"feishu-{_uid()}",
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _reload(db_session: AsyncSession, wo_id: uuid.UUID) -> WorkOrder:
    result = await db_session.execute(
        select(WorkOrder).where(WorkOrder.id == wo_id),
    )
    return result.scalar_one()


async def test_approve_verifies_work_order_and_sends_card(
    db_session: AsyncSession,
    equipment: Equipment,
    reporter: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
    isolated_callbacks: AsyncMock,
) -> None:
    """approve 回调 → 验收合格、工单完成，并发送成功卡片。"""
    verifier = await _verifier(db_session)
    assert verifier.feishu_user_id is not None
    wo = await _wo_at_acceptance(
        db_session, equipment, reporter, make_access_ctx,
    )

    await callbacks_mod.handle_work_order_verify(
        {"action": "approve", "work_order_id": str(wo.id)},
        verifier.feishu_user_id,
    )

    wo = await _reload(db_session, wo.id)
    assert wo.status == "已完成"
    assert wo.verification_result == "合格"
    isolated_callbacks.assert_awaited_once()
    assert _sent_title(isolated_callbacks) == "✅ 验收通过"


async def test_reject_returns_work_order_to_executing(
    db_session: AsyncSession,
    equipment: Equipment,
    reporter: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
    isolated_callbacks: AsyncMock,
) -> None:
    """reject 回调 → 验收不合格、退回执行中。"""
    verifier = await _verifier(db_session)
    assert verifier.feishu_user_id is not None
    wo = await _wo_at_acceptance(
        db_session, equipment, reporter, make_access_ctx,
    )

    await callbacks_mod.handle_work_order_verify(
        {"action": "reject", "work_order_id": str(wo.id)},
        verifier.feishu_user_id,
    )

    wo = await _reload(db_session, wo.id)
    assert wo.status == "执行中"
    assert wo.verification_result == "不合格"
    assert _sent_title(isolated_callbacks) == "✅ 退回"


async def test_missing_work_order_sends_error_card(
    db_session: AsyncSession, isolated_callbacks: AsyncMock,
) -> None:
    """工单不存在 → 发送错误卡片，不抛异常。"""
    verifier = await _verifier(db_session)
    assert verifier.feishu_user_id is not None

    await callbacks_mod.handle_work_order_verify(
        {"action": "approve", "work_order_id": str(uuid.uuid4())},
        verifier.feishu_user_id,
    )

    isolated_callbacks.assert_awaited_once()
    assert _sent_title(isolated_callbacks) == "❌ 工单不存在"


async def test_wrong_status_sends_warning_card(
    db_session: AsyncSession,
    equipment: Equipment,
    reporter: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
    isolated_callbacks: AsyncMock,
) -> None:
    """非「待验收」状态 → 警告卡片，状态不变。"""
    verifier = await _verifier(db_session)
    assert verifier.feishu_user_id is not None
    ctx = make_access_ctx(reporter)
    data = WorkOrderCreate(
        equipment_id=equipment.id,
        responsible_person_id=reporter.id,
    )
    wo = await create_work_order(db_session, data, ctx)  # 待处理

    await callbacks_mod.handle_work_order_verify(
        {"action": "approve", "work_order_id": str(wo.id)},
        verifier.feishu_user_id,
    )

    wo = await _reload(db_session, wo.id)
    assert wo.status == "待处理"
    assert _sent_title(isolated_callbacks) == "⚠️ 无法验收"


async def test_unknown_user_is_ignored(
    db_session: AsyncSession,
    equipment: Equipment,
    reporter: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
    isolated_callbacks: AsyncMock,
) -> None:
    """飞书用户不存在 → 静默忽略，不发卡、不动工单。"""
    wo = await _wo_at_acceptance(
        db_session, equipment, reporter, make_access_ctx,
    )

    await callbacks_mod.handle_work_order_verify(
        {"action": "approve", "work_order_id": str(wo.id)},
        "feishu-nobody",
    )

    wo = await _reload(db_session, wo.id)
    assert wo.status == "待验收"
    isolated_callbacks.assert_not_awaited()


async def test_unknown_action_is_ignored(isolated_callbacks: AsyncMock) -> None:
    """未知 action → 静默忽略。"""
    await callbacks_mod.handle_work_order_verify(
        {"action": "weird-action", "work_order_id": str(uuid.uuid4())},
        "feishu-anyone",
    )

    isolated_callbacks.assert_not_awaited()


def test_register_feishu_callbacks_maps_approve_and_reject() -> None:
    """注册函数把 approve/reject 都映射到验收 handler。"""
    from app.platform.integrations.feishu import event_handler

    snapshot = dict(event_handler._CARD_ACTION_HANDLERS)
    event_handler._CARD_ACTION_HANDLERS.clear()
    try:
        callbacks_mod.register_feishu_callbacks()
        assert (
            event_handler._CARD_ACTION_HANDLERS["approve"]
            is callbacks_mod.handle_work_order_verify
        )
        assert (
            event_handler._CARD_ACTION_HANDLERS["reject"]
            is callbacks_mod.handle_work_order_verify
        )
    finally:
        event_handler._CARD_ACTION_HANDLERS.clear()
        event_handler._CARD_ACTION_HANDLERS.update(snapshot)
