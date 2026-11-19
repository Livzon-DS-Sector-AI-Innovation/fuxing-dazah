"""工单指派维修人 MCP 工具测试 — list_my_pending / list_repair_candidates / assign。

工具层守卫（仅工单负责人可操作、状态限制、跨部门拦截）与文案；
候选推导规则本身已由 test_personnel_derive.py 覆盖，这里只造最小数据。
用 set_context 注入 db session 后直接调工具函数。
"""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import time as app_time
from app.modules.equipment.mcp_tools.work_order import (
    assign_work_order,
    list_my_pending_work_orders,
    list_repair_candidates,
)
from app.modules.equipment.models import (
    Equipment,
    EquipmentPersonnel,
    EquipmentPersonnelRole,
    EquipmentRole,
    Location,
    WorkOrder,
)
from app.modules.equipment.service.personnel import REPAIR_ROLE_CODE
from app.platform.identity.models import Department, User
from app.platform.mcp.deps import reset_context, set_context


def _uid() -> str:
    return uuid.uuid4().hex[:6].upper()


async def _call(db: AsyncSession, fn: Any, *args: Any, **kwargs: Any) -> Any:
    """在 MCP context 中调用工具函数，返回 ToolResult。"""
    db_token, user_token = set_context(db)
    try:
        result = await fn(*args, **kwargs)
    finally:
        reset_context(db_token, user_token)
    return result


async def _content(db: AsyncSession, fn: Any, *args: Any, **kwargs: Any) -> str:
    result = await _call(db, fn, *args, **kwargs)
    return "".join(getattr(b, "text", "") for b in result.content)


@pytest.fixture(autouse=True)
def _mock_assignment_notify(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Mock 指派飞书通知（fire-and-forget 后台任务会自建 session，测试内必炸）。

    notify_assignment_in_background 是同步函数（内部 create_task），
    用 MagicMock 按 call 断言，AsyncMock 会因无人 await 计数为 0。
    """
    from unittest.mock import MagicMock

    mock = MagicMock()
    monkeypatch.setattr(
        "app.modules.equipment.service.work_order."
        "notify_assignment_in_background",
        mock,
    )
    return mock


@pytest.fixture(autouse=True)
def _soft_commit(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """MCP 工具内的 db.commit() 降级为 flush，保住测试事务回滚语义。"""
    monkeypatch.setattr(db_session, "commit", db_session.flush)


@pytest.fixture
async def repair_role(db_session: AsyncSession) -> EquipmentRole:
    """复用已存在的 repair 角色（code 唯一索引，开发库已配置）。"""
    existing = (
        await db_session.execute(
            select(EquipmentRole).where(
                EquipmentRole.code == REPAIR_ROLE_CODE,
                EquipmentRole.is_deleted == False,  # noqa: E712
            )
        )
    ).scalars().first()
    if existing is not None:
        return existing
    role = EquipmentRole(name="维修工", code=REPAIR_ROLE_CODE)
    db_session.add(role)
    await db_session.flush()
    return role


async def _make_user(
    db: AsyncSession, name: str, *, department: str | None = None
) -> User:
    user = User(
        name=name,
        employee_no=f"EMP-A-{_uid()}",
        department=department,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_department(db: AsyncSession) -> Department:
    dept = Department(name=f"指派部-{_uid()}", feishu_department_id=f"od-a-{_uid()}")
    db.add(dept)
    await db.flush()
    return dept


async def _make_equipment(db: AsyncSession, department_id: uuid.UUID) -> Equipment:
    location = Location(name="指派车间", code=f"WS-{_uid()}")
    db.add(location)
    await db.flush()
    eq = Equipment(
        equipment_no=f"EQ-{_uid()}",
        name="指派用反应釜",
        location_id=location.id,
        status="完好",
        department_id=department_id,
    )
    db.add(eq)
    await db.flush()
    return eq


async def _make_work_order(
    db: AsyncSession,
    equipment_id: uuid.UUID,
    *,
    responsible_person_id: uuid.UUID | None,
    assignee_id: uuid.UUID | None = None,
    status: str = "待处理",
    priority: str = "中",
    reporter_id: uuid.UUID | None = None,
    reported_at_offset_minutes: int = 0,
) -> WorkOrder:
    wo = WorkOrder(
        work_order_no=f"WO-TEST-{_uid()}",
        equipment_id=equipment_id,
        order_type="故障维修",
        priority=priority,
        status=status,
        fault_description="电机异响，转速不稳",
        responsible_person_id=responsible_person_id,
        assignee_id=assignee_id,
        reporter_id=reporter_id,
        reported_at=app_time.now()
        - timedelta(minutes=reported_at_offset_minutes),
    )
    db.add(wo)
    await db.flush()
    return wo


async def _add_repair_personnel(
    db: AsyncSession,
    role: EquipmentRole,
    *,
    user_id: uuid.UUID | None,
    department: str | None,
    name: str,
) -> EquipmentPersonnel:
    person = EquipmentPersonnel(
        name=name,
        user_id=user_id,
        employee_no=f"PP-{_uid()}",
        department=department,
    )
    db.add(person)
    await db.flush()
    db.add(EquipmentPersonnelRole(personnel_id=person.id, role_id=role.id))
    await db.flush()
    return person


async def _reload_wo(db: AsyncSession, wo_id: uuid.UUID) -> WorkOrder:
    return (
        await db.execute(select(WorkOrder).where(WorkOrder.id == wo_id))
    ).scalar_one()


# ── Tool: list_my_pending_work_orders ──


async def test_list_my_pending_scoped_to_responsible(
    db_session: AsyncSession,
) -> None:
    """只列「我负责的待处理单」：默认仅未指派，unassigned_only=False 含已指派。"""
    dept = await _make_department(db_session)
    eq = await _make_equipment(db_session, dept.id)
    responsible = await _make_user(db_session, f"负责人{_uid()}")
    other = await _make_user(db_session, f"路人{_uid()}")
    repairer = await _make_user(db_session, f"维修工{_uid()}")
    bystander = await _make_user(db_session, f"旁观者{_uid()}")

    wo_unassigned = await _make_work_order(
        db_session, eq.id, responsible_person_id=responsible.id
    )
    wo_assigned = await _make_work_order(
        db_session,
        eq.id,
        responsible_person_id=responsible.id,
        assignee_id=repairer.id,
    )
    await _make_work_order(
        db_session, eq.id, responsible_person_id=bystander.id
    )  # 别人名下
    await _make_work_order(
        db_session,
        eq.id,
        responsible_person_id=responsible.id,
        status="已完成",
    )  # 已完成不算待处理

    content = await _content(
        db_session, list_my_pending_work_orders, str(responsible.id)
    )
    assert wo_unassigned.work_order_no in content
    assert "未指派" in content
    assert wo_assigned.work_order_no not in content

    content_all = await _content(
        db_session,
        list_my_pending_work_orders,
        str(responsible.id),
        unassigned_only=False,
    )
    assert wo_unassigned.work_order_no in content_all
    assert wo_assigned.work_order_no in content_all

    content_other = await _content(
        db_session, list_my_pending_work_orders, str(other.id)
    )
    assert "没有" in content_other


async def test_list_my_pending_orders_by_priority(
    db_session: AsyncSession,
) -> None:
    """排序：紧急在前，低在后。"""
    dept = await _make_department(db_session)
    eq = await _make_equipment(db_session, dept.id)
    responsible = await _make_user(db_session, f"排序负责人{_uid()}")

    wo_low = await _make_work_order(
        db_session,
        eq.id,
        responsible_person_id=responsible.id,
        priority="低",
        reported_at_offset_minutes=0,
    )
    wo_urgent = await _make_work_order(
        db_session,
        eq.id,
        responsible_person_id=responsible.id,
        priority="紧急",
        reported_at_offset_minutes=30,
    )

    content = await _content(
        db_session, list_my_pending_work_orders, str(responsible.id)
    )
    assert content.index(wo_urgent.work_order_no) < content.index(
        wo_low.work_order_no
    )


# ── Tool: list_repair_candidates ──


async def test_candidates_ranked_with_recommended(
    db_session: AsyncSession, repair_role: EquipmentRole
) -> None:
    """同部门有账号排最前并标记推荐；跨部门/无账号靠后并标注。"""
    dept = await _make_department(db_session)
    eq = await _make_equipment(db_session, dept.id)
    responsible = await _make_user(db_session, f"候选负责人{_uid()}")

    same_dept_user = await _make_user(
        db_session, f"同部维修{_uid()}", department=dept.name
    )
    await _add_repair_personnel(
        db_session,
        repair_role,
        user_id=same_dept_user.id,
        department=dept.name,
        name=same_dept_user.name,
    )
    cross_dept_user = await _make_user(
        db_session, f"跨部维修{_uid()}", department=f"外部门-{_uid()}"
    )
    await _add_repair_personnel(
        db_session,
        repair_role,
        user_id=cross_dept_user.id,
        department=f"外部门-{_uid()}",
        name=cross_dept_user.name,
    )
    await _add_repair_personnel(  # 有人员记录但未绑定平台账号
        db_session,
        repair_role,
        user_id=None,
        department=dept.name,
        name=f"无账号维修{_uid()}",
    )

    wo = await _make_work_order(
        db_session, eq.id, responsible_person_id=responsible.id
    )
    result = await _call(
        db_session,
        list_repair_candidates,
        wo.work_order_no,
        str(responsible.id),
    )
    content = "".join(getattr(b, "text", "") for b in result.content)
    assert same_dept_user.name in content
    assert cross_dept_user.name in content
    assert "未绑定平台账号" in content
    # 同部门有账号者排第一位且是推荐人
    assert result.structured_content["result"][0]["name"] == same_dept_user.name
    assert (
        result.structured_content["recommended_user_id"]
        == str(same_dept_user.id)
    )


async def test_candidates_denied_for_non_responsible(
    db_session: AsyncSession,
) -> None:
    """非工单负责人查看候选人被拒。"""
    dept = await _make_department(db_session)
    eq = await _make_equipment(db_session, dept.id)
    responsible = await _make_user(db_session, f"守卫负责人{_uid()}")
    other = await _make_user(db_session, f"守卫路人{_uid()}")
    wo = await _make_work_order(
        db_session, eq.id, responsible_person_id=responsible.id
    )

    result = await _call(
        db_session, list_repair_candidates, wo.work_order_no, str(other.id)
    )
    assert result.is_error
    assert "只有工单负责人" in "".join(
        getattr(b, "text", "") for b in result.content
    )


# ── Tool: assign_work_order ──


async def test_assign_by_name_happy_path(
    db_session: AsyncSession, repair_role: EquipmentRole, _mock_assignment_notify: Any
) -> None:
    """负责人按姓名指派：落库 assignee_id/assigned_at，发飞书通知。"""
    dept = await _make_department(db_session)
    eq = await _make_equipment(db_session, dept.id)
    responsible = await _make_user(db_session, f"指派负责人{_uid()}")
    repairer = await _make_user(
        db_session, f"被指派人{_uid()}", department=dept.name
    )

    wo = await _make_work_order(
        db_session, eq.id, responsible_person_id=responsible.id
    )
    result = await _call(
        db_session,
        assign_work_order,
        wo.work_order_no,
        repairer.name,  # 姓名路径：resolve_user 唯一命中
        str(responsible.id),
    )
    content = "".join(getattr(b, "text", "") for b in result.content)
    assert not result.is_error
    assert f"已指派给 {repairer.name}" in content
    assert result.structured_content["reassigned"] is False

    reloaded = await _reload_wo(db_session, wo.id)
    assert reloaded.assignee_id == repairer.id
    assert reloaded.assigned_at is not None
    _mock_assignment_notify.assert_called_once()
    assert (
        _mock_assignment_notify.call_args.kwargs["assignee_id"] == repairer.id
    )


async def test_assign_reassign_mentions_previous(
    db_session: AsyncSession, _mock_assignment_notify: Any
) -> None:
    """改派已指派工单：文案含「改派」与原维修人。"""
    dept = await _make_department(db_session)
    eq = await _make_equipment(db_session, dept.id)
    responsible = await _make_user(db_session, f"改派负责人{_uid()}")
    old = await _make_user(db_session, f"原维修人{_uid()}", department=dept.name)
    new = await _make_user(db_session, f"新维修人{_uid()}", department=dept.name)

    wo = await _make_work_order(
        db_session,
        eq.id,
        responsible_person_id=responsible.id,
        assignee_id=old.id,
    )
    result = await _call(
        db_session,
        assign_work_order,
        wo.work_order_no,
        new.name,
        str(responsible.id),
    )
    content = "".join(getattr(b, "text", "") for b in result.content)
    assert not result.is_error
    assert "已改派" in content
    assert f"原维修人：{old.name}" in content
    assert (await _reload_wo(db_session, wo.id)).assignee_id == new.id


async def test_assign_guards(
    db_session: AsyncSession,
) -> None:
    """守卫：非负责人 / 无负责人 / 状态不允许。"""
    dept = await _make_department(db_session)
    eq = await _make_equipment(db_session, dept.id)
    responsible = await _make_user(db_session, f"守卫甲{_uid()}")
    other = await _make_user(db_session, f"守卫乙{_uid()}")

    wo = await _make_work_order(
        db_session, eq.id, responsible_person_id=responsible.id
    )
    wo_no_resp = await _make_work_order(
        db_session, eq.id, responsible_person_id=None
    )
    wo_done = await _make_work_order(
        db_session,
        eq.id,
        responsible_person_id=responsible.id,
        status="已完成",
    )

    # 非负责人
    result = await _call(
        db_session, assign_work_order, wo.work_order_no, "张三", str(other.id)
    )
    assert result.is_error
    assert "只有工单负责人" in "".join(
        getattr(b, "text", "") for b in result.content
    )

    # 工单未设置负责人
    result = await _call(
        db_session,
        assign_work_order,
        wo_no_resp.work_order_no,
        "张三",
        str(other.id),
    )
    assert result.is_error
    assert "未设置负责人" in "".join(
        getattr(b, "text", "") for b in result.content
    )

    # 已完成状态
    result = await _call(
        db_session,
        assign_work_order,
        wo_done.work_order_no,
        "张三",
        str(responsible.id),
    )
    assert result.is_error
    assert "已完成" in "".join(
        getattr(b, "text", "") for b in result.content
    )


async def test_assign_cross_department_blocked(
    db_session: AsyncSession,
) -> None:
    """被指派人部门与设备部门不一致时拦截，并提示查看候选人。"""
    dept = await _make_department(db_session)
    eq = await _make_equipment(db_session, dept.id)
    responsible = await _make_user(db_session, f"跨部负责人{_uid()}")
    outsider = await _make_user(
        db_session, f"跨部人选{_uid()}", department=f"隔壁部-{_uid()}"
    )

    wo = await _make_work_order(
        db_session, eq.id, responsible_person_id=responsible.id
    )
    result = await _call(
        db_session,
        assign_work_order,
        wo.work_order_no,
        str(outsider.id),
        str(responsible.id),
    )
    content = "".join(getattr(b, "text", "") for b in result.content)
    assert result.is_error
    assert "跨部门" in content
    assert "list_repair_candidates" in content
    assert (await _reload_wo(db_session, wo.id)).assignee_id is None
