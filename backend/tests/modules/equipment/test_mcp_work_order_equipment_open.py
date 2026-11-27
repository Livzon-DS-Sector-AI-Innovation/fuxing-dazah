"""设备进行中工单查询 MCP 工具测试 — list_equipment_open_work_orders。

报修建单前查重视角：同设备、未完结（待处理/执行中/待验收）、未删除；
已完成/已关闭不返回（修完又坏属复发）。输出必须带报修人与故障描述
全文——查重命中时用户要靠「谁报的、报了什么」做判断。
用 set_context 注入 db session 后直接调工具函数。
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.mcp_tools.work_order import (
    list_equipment_open_work_orders,
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
    user = User(name=name, employee_no=f"EMP-D-{_uid()}")
    db.add(user)
    await db.flush()
    return user


async def _make_equipment(db: AsyncSession, name: str = "R-301离心泵") -> Equipment:
    location = Location(name="查重车间", code=f"WS-{_uid()}")
    db.add(location)
    await db.flush()
    equipment = Equipment(
        equipment_no=f"EQ-{_uid()}",
        name=name,
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
    fault_description: str = "电机异响",
    order_type: str = "故障维修",
    status: str = "待处理",
    is_deleted: bool = False,
) -> WorkOrder:
    """repo 直建工单（绕过 service 状态机，构造任意状态的单）。"""
    return await repo_create_work_order(db, {
        "work_order_no": f"WO-20261119-{_uid()[:4]}",
        "equipment_id": equipment_id,
        "order_type": order_type,
        "priority": "中",
        "status": status,
        "fault_description": fault_description,
        "reporter_id": reporter_id,
        "is_deleted": is_deleted,
    })


async def test_open_orders_returned_with_reporter_and_description(
    db_session: AsyncSession,
) -> None:
    """进行中的单返回，且输出含报修人与故障描述全文（查重判断依据）。"""
    reporter = await _make_user(db_session, "查重报修人")
    equipment = await _make_equipment(db_session)
    wo = await _make_work_order(
        db_session,
        equipment_id=equipment.id,
        reporter_id=reporter.id,
        fault_description="泵体密封处漏水，地面有积水",
        status="执行中",
    )

    result = await _call(
        db_session, list_equipment_open_work_orders, equipment.equipment_no, str(reporter.id)
    )
    assert not result.is_error
    assert result.structured_content["total"] == 1
    assert result.structured_content["result"][0]["work_order_no"] == wo.work_order_no
    text = _text(result)
    assert "查重报修人" in text
    assert "泵体密封处漏水，地面有积水" in text


async def test_finished_and_deleted_excluded(
    db_session: AsyncSession,
) -> None:
    """已完成/已关闭/已删除的单不返回——修完又坏属复发，应允许再报。"""
    reporter = await _make_user(db_session, "状态报修人")
    equipment = await _make_equipment(db_session)
    for status in ("已完成", "已关闭"):
        await _make_work_order(
            db_session, equipment_id=equipment.id, reporter_id=reporter.id, status=status
        )
    await _make_work_order(
        db_session, equipment_id=equipment.id, reporter_id=reporter.id, is_deleted=True
    )

    result = await _call(
        db_session, list_equipment_open_work_orders, equipment.equipment_no, str(reporter.id)
    )
    assert result.structured_content["total"] == 0
    assert "没有进行中的工单" in _text(result)


async def test_equipment_isolation(db_session: AsyncSession) -> None:
    """只返回目标设备的单，别的设备的进行中单不入列。"""
    reporter = await _make_user(db_session, "隔离报修人")
    target = await _make_equipment(db_session, "目标泵")
    other = await _make_equipment(db_session, "别的泵")
    wo = await _make_work_order(
        db_session, equipment_id=target.id, reporter_id=reporter.id
    )
    await _make_work_order(db_session, equipment_id=other.id, reporter_id=reporter.id)

    result = await _call(
        db_session, list_equipment_open_work_orders, target.equipment_no, str(reporter.id)
    )
    assert result.structured_content["total"] == 1
    assert result.structured_content["result"][0]["work_order_no"] == wo.work_order_no


async def test_limit_five_most_recent(db_session: AsyncSession) -> None:
    """超过 5 条时只返回最近 5 条。"""
    reporter = await _make_user(db_session, "限量报修人")
    equipment = await _make_equipment(db_session)
    for _ in range(6):
        await _make_work_order(db_session, equipment_id=equipment.id, reporter_id=reporter.id)

    result = await _call(
        db_session, list_equipment_open_work_orders, equipment.equipment_no, str(reporter.id)
    )
    assert result.structured_content["total"] == 5


async def test_equipment_not_found(db_session: AsyncSession) -> None:
    """设备不存在时报错而非空列表。"""
    reporter = await _make_user(db_session, "无设备报修人")
    result = await _call(
        db_session,
        list_equipment_open_work_orders,
        f"EQ-NONE-{_uid()}",
        str(reporter.id),
    )
    assert result.is_error
