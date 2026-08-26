"""工作台 MCP 工具测试 — query_workbench_todo / activate_planned_batch / receive_batch。

工具层是薄胶水（批号解析、参数组装、Markdown 渲染、错误包裹），
业务校验已由 test_workbench_service.py 覆盖，这里只测胶水逻辑与文案。
用 set_context 注入 db session 后直接调工具函数。
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production import repository as repo
from app.modules.production.mcp_tools.workbench import (
    activate_planned_batch,
    query_workbench_todo,
    receive_batch,
)
from app.modules.production.models import Batch
from app.modules.production.schemas import (
    BatchCreate,
    ExecutionCompleteIn,
    ExecutionStartIn,
)
from app.modules.production.service import (
    assignment_service,
    batch_service,
    execution_service,
)
from app.platform.identity.models import User
from app.platform.mcp.deps import reset_context, set_context
from tests.modules.production.conftest import rand_code


async def _get_or_create_user_named(db: AsyncSession, employee_no: str) -> User:
    """按工号获取或创建用户（同一测试内需要多个不同用户时使用）。"""
    stmt = select(User).where(
        User.employee_no == employee_no, User.is_deleted == False  # noqa: E712
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        return existing
    user = User(name=f"测试-{employee_no}", employee_no=employee_no)
    db.add(user)
    await db.flush()
    return user


async def _make_stage_owner(
    db: AsyncSession, employee_no: str, route_id: uuid.UUID, stage_name: str,
) -> User:
    user = await _get_or_create_user_named(db, employee_no)
    await assignment_service.create_stage_assignment(
        db,
        user_id=user.id,
        stage_name=stage_name,
        route_id=route_id,
        created_by=user.id,
    )
    return user


async def _make_batch(
    db: AsyncSession, published_route: dict[str, Any],
) -> Batch:
    return await batch_service.create_batch(
        db,
        BatchCreate(
            batch_no=rand_code("B"),
            product_id=published_route["product"].id,
            route_id=published_route["route"].id,
        ),
        user=None,
    )


async def _make_scheduled_plan_batch(
    db: AsyncSession, published_route: dict[str, Any],
) -> Batch:
    """直接落一条 scheduled 计划批次（激活对象）。"""
    batch = Batch(
        batch_no=rand_code("PLAN"),
        product_id=published_route["product"].id,
        route_id=published_route["route"].id,
        status="scheduled",
        creation_type="plan",
        quantity=100.0,
        unit="kg",
    )
    db.add(batch)
    await db.flush()
    return batch


async def _complete_node_a(
    db: AsyncSession, batch: Batch, published_route: dict[str, Any],
) -> None:
    ex = await execution_service.start_execution(
        db, batch.id,
        ExecutionStartIn(node_id=published_route["node_a"].id),
        user=None,
    )
    await execution_service.complete_execution(
        db, ex.id, ExecutionCompleteIn(), user=None,
    )


async def _call(
    db: AsyncSession, fn: Any, *args: Any, **kwargs: Any,
) -> str:
    """在 MCP context 中调用工具函数，返回其 content 文本。"""
    db_token, user_token = set_context(db)
    try:
        result = await fn(*args, **kwargs)
    finally:
        reset_context(db_token, user_token)
    return "".join(getattr(b, "text", "") for b in result.content)


class TestWorkbenchMcpTools:
    async def test_query_todo_empty_for_unassigned_user(
        self, db_session: AsyncSession, test_user: User,
    ) -> None:
        """无任何工段/工序分配的用户，三段均为空。"""
        content = await _call(
            db_session, query_workbench_todo, str(test_user.id),
        )
        assert "一、待接收批次" in content
        assert "二、待开工工序" in content
        assert "三、可激活计划批次" in content
        assert content.count("无") >= 3

    async def test_query_todo_split_card(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """边界起点完成后：待接收段有分裂卡片，含建议批号与 edge 标识。"""
        route_id = published_route["route"].id
        user = await _make_stage_owner(db_session, "TODO-OWN", route_id, "提炼")
        await assignment_service.set_stage_suffix(
            db_session, user_id=user.id, route_id=route_id,
            stage_name="提炼", suffix="-T1",
        )
        batch = await _make_batch(db_session, published_route)
        await _complete_node_a(db_session, batch, published_route)

        content = await _call(db_session, query_workbench_todo, str(user.id))
        assert "一、待接收批次" in content
        assert "分裂" in content
        assert batch.batch_no in content
        assert f"{batch.batch_no}-T1" in content
        assert str(published_route["edge_ab"].id) in content

    async def test_activate_success(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """第一工段负责人激活计划批次：scheduled → pending。"""
        route_id = published_route["route"].id
        user = await _make_stage_owner(db_session, "ACT-OWN", route_id, "发酵")
        batch = await _make_scheduled_plan_batch(db_session, published_route)

        content = await _call(
            db_session, activate_planned_batch, str(user.id), batch.batch_no,
        )
        assert "已接收" in content
        assert "待执行" in content
        assert batch.status == "pending"

    async def test_activate_rejected_for_non_first_stage_owner(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """非第一工段负责人激活被拒，错误文案透出。"""
        route_id = published_route["route"].id
        user = await _make_stage_owner(db_session, "ACT-NO", route_id, "提炼")
        batch = await _make_scheduled_plan_batch(db_session, published_route)

        content = await _call(
            db_session, activate_planned_batch, str(user.id), batch.batch_no,
        )
        assert "激活失败" in content
        assert batch.status == "scheduled"

    async def test_activate_rejected_for_non_scheduled(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """非 scheduled 批次激活被拒。"""
        route_id = published_route["route"].id
        user = await _make_stage_owner(db_session, "ACT-PEN", route_id, "发酵")
        batch = await _make_batch(db_session, published_route)  # pending

        content = await _call(
            db_session, activate_planned_batch, str(user.id), batch.batch_no,
        )
        assert "激活失败" in content

    async def test_activate_unknown_batch(
        self, db_session: AsyncSession, test_user: User,
    ) -> None:
        """批号不存在：友好文案。"""
        content = await _call(
            db_session, activate_planned_batch, str(test_user.id), "NO-SUCH",
        )
        assert "未找到批次" in content

    async def test_receive_split_success(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """分裂接收成功：创建子批次，返回状态表。

        边界接收的工段权限校验在 service 内（边界边起点工段负责人），
        与 test_workbench_service.py 的 receive 用例同口径。
        """
        route_id = published_route["route"].id
        user = await _make_stage_owner(db_session, "RCV-OWN", route_id, "发酵")
        batch = await _make_batch(db_session, published_route)
        await _complete_node_a(db_session, batch, published_route)
        child_no = f"{batch.batch_no}-T1"

        content = await _call(
            db_session, receive_batch, str(user.id),
            [batch.batch_no],
            [{"batch_no": child_no, "quantity": 100, "unit": "kg"}],
            edge_id=str(published_route["edge_ab"].id),
        )
        assert "接收成功" in content
        assert child_no in content
        child = await repo.get_batch_by_no(db_session, child_no)
        assert child is not None
        assert child.status == "pending"

    async def test_receive_unknown_parent(
        self, db_session: AsyncSession, test_user: User,
    ) -> None:
        """父批号不存在：列出缺失批号。"""
        content = await _call(
            db_session, receive_batch, str(test_user.id),
            ["NO-SUCH"],
            [{"batch_no": "X-1"}],
        )
        assert "接收失败" in content
        assert "NO-SUCH" in content

    async def test_receive_missing_child_batch_no(
        self, db_session: AsyncSession, test_user: User,
    ) -> None:
        """子批次缺批号：参数预校验拦截。"""
        content = await _call(
            db_session, receive_batch, str(test_user.id),
            ["SOME-PARENT"],
            [{"quantity": 10}],
        )
        assert "接收失败" in content
        assert "batch_no" in content

    async def test_receive_merge_missing_deviation_reason(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """合并接收不传偏离原因：service 校验拒绝，文案透出。"""
        route_id = published_route["route"].id
        user = await _make_stage_owner(db_session, "MRG-OWN", route_id, "提炼")
        b1 = await _make_batch(db_session, published_route)
        b2 = await _make_batch(db_session, published_route)
        await _complete_node_a(db_session, b1, published_route)
        await _complete_node_a(db_session, b2, published_route)

        content = await _call(
            db_session, receive_batch, str(user.id),
            [b1.batch_no, b2.batch_no],
            [{"batch_no": rand_code("MERGED")}],
        )
        assert "接收失败" in content
