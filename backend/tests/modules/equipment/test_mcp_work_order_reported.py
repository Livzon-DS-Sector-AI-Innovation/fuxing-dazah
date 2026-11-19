"""报修人查询工单进度 MCP 工具测试 — list_my_reported_work_orders。

报修人视角（reporter_id）与维修人视角（get_user_work_orders 的
assignee/responsible 过滤）互补：只报修、不负责维修的用户也要能查到
自己的单子，且已完结（已完成/已关闭）历史单可见。
用 set_context 注入 db session 后直接调工具函数。
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.mcp_tools.work_order import (
    list_my_reported_work_orders,
)
from app.modules.equipment.models import (
    Equipment,
    Location,
    WorkOrder,
)
from app.modules.equipment.repository import (
    create_work_order as repo_create_work_order,
)
from app.platform.identity.models import User
from app.platform.mcp.deps import reset_context, set_context


def _uid() -> str:
    """共享库唯一后缀，避免唯一键冲突。"""
    return uuid.uuid4().hex[:6].upper()


async def _call(db: AsyncSession, fn: Any, *args: Any, **kwargs: Any) -> Any:
    """在 MCP context 中调用工具函数，返回 ToolResult。"""
    db_token, user_token = set_context(db)
    try:
        result = await fn(*args, **kwargs)
    finally:
        reset_context(db_token, user_token)
    return result


def _text(result: Any) -> str:
    return "".join(getattr(b, "text", "") for b in result.content)


async def _make_user(db: AsyncSession, name: str) -> User:
    user = User(name=name, employee_no=f"EMP-Q-{_uid()}")
    db.add(user)
    await db.flush()
    return user


async def _make_equipment(db: AsyncSession) -> Equipment:
    location = Location(name="进度车间", code=f"WS-{_uid()}")
    db.add(location)
    await db.flush()
    equipment = Equipment(
        equipment_no=f"EQ-{_uid()}",
        name="R-201离心泵",
        location_id=location.id,
        status="完好",
    )
    db.add(equipment)
    await db.flush()
    return equipment


async def _make_work_order(
    db: AsyncSession,
    *,
    equipment_id: uuid.UUID,
    reporter_id: uuid.UUID,
    status: str = "待处理",
    assignee_id: uuid.UUID | None = None,
) -> WorkOrder:
    """repo 直建工单（绕过 service 状态机，构造任意状态的单）。"""
    return await repo_create_work_order(db, {
        "work_order_no": f"WO-20261119-{_uid()[:4]}",
        "equipment_id": equipment_id,
        "order_type": "故障维修",
        "priority": "中",
        "status": status,
        "reporter_id": reporter_id,
        "assignee_id": assignee_id,
    })


async def test_reporter_sees_own_orders_including_finished(
    db_session: AsyncSession,
) -> None:
    """自己报的单（待处理/已完成/已关闭）都返回，他人报的不入列。"""
    reporter = await _make_user(db_session, "进度报修人")
    other = await _make_user(db_session, "进度路人")
    repairman = await _make_user(db_session, "进度维修员")
    equipment = await _make_equipment(db_session)

    wo_open = await _make_work_order(
        db_session, equipment_id=equipment.id, reporter_id=reporter.id
    )
    wo_done = await _make_work_order(
        db_session,
        equipment_id=equipment.id,
        reporter_id=reporter.id,
        status="已完成",
        assignee_id=repairman.id,
    )
    wo_closed = await _make_work_order(
        db_session, equipment_id=equipment.id, reporter_id=reporter.id, status="已关闭"
    )
    await _make_work_order(
        db_session, equipment_id=equipment.id, reporter_id=other.id
    )

    result = await _call(db_session, list_my_reported_work_orders, str(reporter.id))
    assert not result.is_error
    nos = {r["work_order_no"] for r in result.structured_content["result"]}
    assert nos == {wo_open.work_order_no, wo_done.work_order_no, wo_closed.work_order_no}
    text = _text(result)
    assert "维修人：进度维修员" in text
    assert "维修人：未指派" in text


async def test_reporter_isolated_from_assignee_view(
    db_session: AsyncSession,
) -> None:
    """只报修、不负责维修的用户在维修人视角查不到，在报修人视角查得到。"""
    from app.modules.equipment.repository.work_order import get_user_work_orders

    reporter = await _make_user(db_session, "纯报修人")
    equipment = await _make_equipment(db_session)
    wo = await _make_work_order(
        db_session, equipment_id=equipment.id, reporter_id=reporter.id
    )

    # 维修人/负责人视角：reporter 既非 assignee 也非 responsible，查不到
    maint_view = await get_user_work_orders(db_session, reporter.id)
    assert all(w.id != wo.id for w in maint_view)

    # 报修人视角：查得到
    result = await _call(db_session, list_my_reported_work_orders, str(reporter.id))
    assert result.structured_content["total"] == 1
    assert result.structured_content["result"][0]["work_order_no"] == wo.work_order_no


async def test_status_filter_and_invalid_status(
    db_session: AsyncSession,
) -> None:
    """状态过滤生效；非法状态直接报错。"""
    reporter = await _make_user(db_session, "过滤报修人")
    equipment = await _make_equipment(db_session)
    wo_done = await _make_work_order(
        db_session, equipment_id=equipment.id, reporter_id=reporter.id, status="已完成"
    )
    await _make_work_order(
        db_session, equipment_id=equipment.id, reporter_id=reporter.id
    )

    result = await _call(
        db_session, list_my_reported_work_orders, str(reporter.id), "已完成"
    )
    assert result.structured_content["total"] == 1
    assert result.structured_content["result"][0]["work_order_no"] == wo_done.work_order_no

    invalid = await _call(
        db_session, list_my_reported_work_orders, str(reporter.id), "进行中"
    )
    assert invalid.is_error


async def test_no_reported_orders_message(db_session: AsyncSession) -> None:
    """没报修过的用户返回友好空文案而非报错。"""
    user = await _make_user(db_session, "没报过的人")

    result = await _call(db_session, list_my_reported_work_orders, str(user.id))
    assert not result.is_error
    assert result.structured_content["total"] == 0
    assert "还没有报修过工单" in _text(result)
