"""equipment.scheduled 统一调度任务测试 — 工单超时扫描。

验证从平台 feishu/sync 迁入的超时扫描：
- TIMEOUT_SCAN_TASK 为 60 秒间隔的统一调度任务定义
- 超时未接单的工单触发主管通知
- 未配置部门 ID 时安全跳过
"""

import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.modules.equipment.scheduled as scheduled_mod
from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.models import Equipment, Location
from app.modules.equipment.schemas import WorkOrderCreate
from app.modules.equipment.service import create_work_order
from app.platform.identity.models import User
from app.platform.scheduler import ScheduleStrategy, TaskDefinition


def _uid() -> str:
    """共享库唯一后缀，避免唯一键冲突。"""
    return uuid.uuid4().hex[:8]


@pytest.fixture
async def reporter(db_session: AsyncSession) -> User:
    """报修人。"""
    user = User(name="超时扫描报修人", employee_no=f"EMP-R-{_uid()}")
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def equipment(db_session: AsyncSession) -> Equipment:
    """完好设备。"""
    location = Location(name="超时扫描车间", code=f"WS-{_uid()}")
    db_session.add(location)
    await db_session.flush()

    eq = Equipment(
        equipment_no=f"EQ-{_uid()}",
        name="超时扫描反应釜",
        location_id=location.id,
        status="完好",
    )
    db_session.add(eq)
    await db_session.flush()
    return eq


def test_timeout_scan_task_is_interval_task() -> None:
    """TIMEOUT_SCAN_TASK 为 60 秒间隔的统一调度任务。"""
    task = scheduled_mod.TIMEOUT_SCAN_TASK
    assert isinstance(task, TaskDefinition)
    assert task.name == "equipment.scan_timeout_work_orders"
    assert task.schedule.strategy == ScheduleStrategy.INTERVAL
    assert task.schedule.interval_seconds == 60
    assert task.module == "equipment"
    assert task.coro is scheduled_mod.scan_timeout_work_orders


async def test_scan_notifies_leader_for_timeout_work_order(
    db_session: AsyncSession,
    reporter: User,
    equipment: Equipment,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """超时未接单的工单 → 通知设备主管。"""
    ctx = make_access_ctx(reporter)
    wo = await create_work_order(
        db_session,
        WorkOrderCreate(
            equipment_id=equipment.id,
            responsible_person_id=reporter.id,
        ),
        ctx,
    )
    wo.reported_at = datetime.now(UTC) - timedelta(hours=2)
    await db_session.flush()

    monkeypatch.setattr(
        scheduled_mod, "settings",
        SimpleNamespace(FEISHU_EQUIPMENT_DEPT_ID="dept-1"),
    )
    monkeypatch.setattr(
        scheduled_mod, "get_claim_timeout_config",
        AsyncMock(
            return_value=SimpleNamespace(
                emergency=1, high=1, medium=1, low=1,
            ),
        ),
    )
    monkeypatch.setattr(
        scheduled_mod, "get_department_leader",
        AsyncMock(return_value={"name": "主管"}),
    )
    notify_mock = AsyncMock()
    monkeypatch.setattr(scheduled_mod, "send_timeout_notification", notify_mock)

    @asynccontextmanager
    async def _fake_factory():
        yield db_session

    monkeypatch.setattr(scheduled_mod, "async_session_factory", _fake_factory)

    await scheduled_mod.scan_timeout_work_orders()

    # 共享测试库可能残留其他测试的历史待处理工单，
    # 因此只断言本测试的工单号出现在通知中。
    notified_nos = [
        call.args[0] for call in notify_mock.await_args_list
    ]
    assert wo.work_order_no in notified_nos


async def test_scan_skips_when_dept_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未配置设备部门 ID → 安全跳过，不发任何通知。"""
    monkeypatch.setattr(
        scheduled_mod, "settings",
        SimpleNamespace(FEISHU_EQUIPMENT_DEPT_ID=""),
    )
    notify_mock = AsyncMock()
    monkeypatch.setattr(scheduled_mod, "send_timeout_notification", notify_mock)

    await scheduled_mod.scan_timeout_work_orders()

    notify_mock.assert_not_awaited()
