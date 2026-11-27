"""工序执行 MCP 工具测试 — change_batch_step_status 的错误结果标记。

背景：工具捕获业务异常返回错误文案时必须标记 is_error=True，
中间件据此回滚会话——否则失败操作中已入会话的写操作会被提交落库。
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.mcp_tools.execution import change_batch_step_status
from app.modules.production.models import NodeExecution
from app.modules.production.schemas import (
    BatchCreate,
    ExecutionCompleteIn,
    ExecutionStartIn,
    FieldValueIn,
)
from app.modules.production.service import (
    assignment_service,
    batch_service,
    execution_service,
)
from app.platform.identity.models import User
from app.platform.mcp.deps import reset_context, set_context
from tests.modules.production.conftest import rand_code


async def _make_plain_user(db: AsyncSession, *, name: str | None = None) -> User:
    """无任何工段/工序身份/权限码的用户。"""
    user = User(
        name=name or f"路人-{rand_code('U')}",
        employee_no=rand_code("EMP"),
    )
    db.add(user)
    await db.flush()
    return user


async def _call(db: AsyncSession, fn: Any, *args: Any, **kwargs: Any) -> Any:
    """在 MCP context 中调用工具函数，返回原始 ToolResult。"""
    db_token, user_token = set_context(db)
    try:
        return await fn(*args, **kwargs)
    finally:
        reset_context(db_token, user_token)


class TestChangeBatchStepStatus:
    async def test_permission_denied_marks_is_error(
        self,
        db_session: AsyncSession,
        published_route: dict[str, Any],
        test_user: User,
        monkeypatch: Any,
    ) -> None:
        """无身份用户结束他人批次的执行：返回错误文案且 is_error=True。"""
        from app.modules.production.service import execution_service as es

        async def fake_perms(_uid: str, _db: AsyncSession) -> set[str]:
            return set()

        monkeypatch.setattr(es, "get_user_permissions", fake_perms)

        batch = await batch_service.create_batch(
            db_session,
            BatchCreate(
                batch_no=rand_code("B"),
                product_id=published_route["product"].id,
                route_id=published_route["route"].id,
            ),
            user=None,
        )
        batch.owner_user_id = test_user.id  # 批次归属他人
        await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(node_id=published_route["node_a"].id),
            user=None,
        )

        outsider = await _make_plain_user(db_session)
        result = await _call(
            db_session,
            change_batch_step_status,
            operator_id=str(outsider.id),
            batch_no=batch.batch_no,
            step_name=published_route["node_a"].name,
            action="end",
        )
        assert result.is_error is True
        assert "结束工序失败" in "".join(getattr(b, "text", "") for b in result.content)

    async def test_invalid_action_marks_is_error(
        self,
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        result = await _call(
            db_session,
            change_batch_step_status,
            operator_id=str(test_user.id),
            batch_no="B-XXX",
            step_name="发酵",
            action="pause",
        )
        assert result.is_error is True


class TestStartWithOwner:
    """开始工序时可选指定工序执行人。

    候选 = 操作人自己配置的默认执行人（NodeAssignment，assigned_by=操作人）；
    操作人的开工权限用「他人名义分配的 NodeAssignment」构造，不污染候选名单。
    """

    async def _grant_start_permission(
        self, db: AsyncSession, route_id: Any, node_id: Any, user_id: Any,
    ) -> None:
        """以第三人（如管理员）名义给操作人分配该工序，取得开工权限。"""
        await assignment_service.create_node_assignment(
            db,
            user_id=user_id,
            node_id=node_id,
            route_id=route_id,
            assigned_by=uuid.uuid4(),
        )

    async def _make_candidate(
        self, db: AsyncSession, route_id: Any, node_id: Any,
        assigned_by: Any, *, name: str | None = None,
    ) -> User:
        """创建一个默认执行人：plain user + 操作人配置的 NodeAssignment。"""
        u = await _make_plain_user(db, name=name)
        await assignment_service.create_node_assignment(
            db,
            user_id=u.id,
            node_id=node_id,
            route_id=route_id,
            assigned_by=assigned_by,
        )
        return u

    async def _make_batch(
        self, db: AsyncSession, ctx: dict[str, Any],
    ) -> Any:
        return await batch_service.create_batch(
            db,
            BatchCreate(
                batch_no=rand_code("B"),
                product_id=ctx["product"].id,
                route_id=ctx["route"].id,
            ),
            user=None,
        )

    async def _executions_of(
        self, db: AsyncSession, batch_id: Any, node_id: Any,
    ) -> list[NodeExecution]:
        stmt = select(NodeExecution).where(
            NodeExecution.batch_id == batch_id,
            NodeExecution.node_id == node_id,
            NodeExecution.is_deleted == False,  # noqa: E712
        )
        return list((await db.execute(stmt)).scalars())

    @staticmethod
    def _no_perms(monkeypatch: Any) -> None:
        """操作人不持任何权限码，权限只能来自工段/工序身份。"""
        from app.modules.production.service import execution_service as es

        async def fake_perms(_uid: str, _db: AsyncSession) -> set[str]:
            return set()

        monkeypatch.setattr(es, "get_user_permissions", fake_perms)

    async def test_start_with_configured_owner_by_name(
        self,
        db_session: AsyncSession,
        published_route: dict[str, Any],
        test_user: User,
        monkeypatch: Any,
    ) -> None:
        """按姓名指定已配置的默认执行人：成功，执行 owner 落为该人。"""
        self._no_perms(monkeypatch)
        route_id = published_route["route"].id
        node_a = published_route["node_a"]
        await self._grant_start_permission(db_session, route_id, node_a.id, test_user.id)
        cand = await self._make_candidate(
            db_session, route_id, node_a.id, assigned_by=test_user.id,
        )
        batch = await self._make_batch(db_session, published_route)

        result = await _call(
            db_session,
            change_batch_step_status,
            operator_id=str(test_user.id),
            batch_no=batch.batch_no,
            step_name=node_a.name,
            action="start",
            owner=cand.name,
        )
        assert result.is_error is False
        content = "".join(getattr(b, "text", "") for b in result.content)
        assert cand.name in content
        assert "代为开始" in content
        [ex] = await self._executions_of(db_session, batch.id, node_a.id)
        assert ex.owner_id == cand.id

    async def test_start_with_owner_by_partial_name(
        self,
        db_session: AsyncSession,
        published_route: dict[str, Any],
        test_user: User,
        monkeypatch: Any,
    ) -> None:
        """姓名部分字符在候选内唯一命中：同样成功。"""
        self._no_perms(monkeypatch)
        route_id = published_route["route"].id
        node_a = published_route["node_a"]
        await self._grant_start_permission(db_session, route_id, node_a.id, test_user.id)
        cand = await self._make_candidate(
            db_session, route_id, node_a.id, assigned_by=test_user.id,
        )
        batch = await self._make_batch(db_session, published_route)

        result = await _call(
            db_session,
            change_batch_step_status,
            operator_id=str(test_user.id),
            batch_no=batch.batch_no,
            step_name=node_a.name,
            action="start",
            owner=cand.name.split("-")[-1],
        )
        assert result.is_error is False
        [ex] = await self._executions_of(db_session, batch.id, node_a.id)
        assert ex.owner_id == cand.id

    async def test_start_with_non_candidate_rejected(
        self,
        db_session: AsyncSession,
        published_route: dict[str, Any],
        test_user: User,
        monkeypatch: Any,
    ) -> None:
        """指定不在候选内的用户：拒绝并列出候选，不产生执行。"""
        self._no_perms(monkeypatch)
        route_id = published_route["route"].id
        node_a = published_route["node_a"]
        await self._grant_start_permission(db_session, route_id, node_a.id, test_user.id)
        cand = await self._make_candidate(
            db_session, route_id, node_a.id, assigned_by=test_user.id,
        )
        outsider = await _make_plain_user(db_session)
        batch = await self._make_batch(db_session, published_route)

        result = await _call(
            db_session,
            change_batch_step_status,
            operator_id=str(test_user.id),
            batch_no=batch.batch_no,
            step_name=node_a.name,
            action="start",
            owner=outsider.name,
        )
        assert result.is_error is True
        content = "".join(getattr(b, "text", "") for b in result.content)
        assert "不在您为该工序配置的默认执行人内" in content
        assert cand.name in content
        assert await self._executions_of(db_session, batch.id, node_a.id) == []

    async def test_start_with_ambiguous_name_rejected(
        self,
        db_session: AsyncSession,
        published_route: dict[str, Any],
        test_user: User,
        monkeypatch: Any,
    ) -> None:
        """候选内同名多人：拒绝并提示提供飞书 user_id 消歧。"""
        self._no_perms(monkeypatch)
        route_id = published_route["route"].id
        node_a = published_route["node_a"]
        await self._grant_start_permission(db_session, route_id, node_a.id, test_user.id)
        dup_name = f"重名-{rand_code('D')}"
        await self._make_candidate(
            db_session, route_id, node_a.id, assigned_by=test_user.id, name=dup_name,
        )
        await self._make_candidate(
            db_session, route_id, node_a.id, assigned_by=test_user.id, name=dup_name,
        )
        batch = await self._make_batch(db_session, published_route)

        result = await _call(
            db_session,
            change_batch_step_status,
            operator_id=str(test_user.id),
            batch_no=batch.batch_no,
            step_name=node_a.name,
            action="start",
            owner=dup_name,
        )
        assert result.is_error is True
        content = "".join(getattr(b, "text", "") for b in result.content)
        assert "匹配到多位可选执行人" in content
        assert await self._executions_of(db_session, batch.id, node_a.id) == []

    async def test_start_with_owner_without_any_candidates(
        self,
        db_session: AsyncSession,
        published_route: dict[str, Any],
        test_user: User,
        monkeypatch: Any,
    ) -> None:
        """未配置任何默认执行人时指定他人：拒绝并说明默认由本人执行。"""
        self._no_perms(monkeypatch)
        route_id = published_route["route"].id
        node_a = published_route["node_a"]
        await self._grant_start_permission(db_session, route_id, node_a.id, test_user.id)
        batch = await self._make_batch(db_session, published_route)

        result = await _call(
            db_session,
            change_batch_step_status,
            operator_id=str(test_user.id),
            batch_no=batch.batch_no,
            step_name=node_a.name,
            action="start",
            owner=f"任意人-{rand_code('N')}",
        )
        assert result.is_error is True
        content = "".join(getattr(b, "text", "") for b in result.content)
        assert "尚未为工序" in content and "配置默认执行人" in content
        assert await self._executions_of(db_session, batch.id, node_a.id) == []

    async def test_start_specifying_operator_self_allowed(
        self,
        db_session: AsyncSession,
        published_route: dict[str, Any],
        monkeypatch: Any,
    ) -> None:
        """指定操作人本人（即使不在候选内）等同默认行为：放行。

        操作人用随机姓名的新用户，避免 resolve_user 姓名模糊搜索
        在开发库残留数据上撞出多匹配。
        """
        self._no_perms(monkeypatch)
        route_id = published_route["route"].id
        node_a = published_route["node_a"]
        op = await _make_plain_user(db_session)
        await self._grant_start_permission(db_session, route_id, node_a.id, op.id)
        batch = await self._make_batch(db_session, published_route)

        result = await _call(
            db_session,
            change_batch_step_status,
            operator_id=str(op.id),
            batch_no=batch.batch_no,
            step_name=node_a.name,
            action="start",
            owner=op.name,
        )
        assert result.is_error is False
        [ex] = await self._executions_of(db_session, batch.id, node_a.id)
        assert ex.owner_id == op.id

    async def test_owner_on_end_rejected(
        self,
        db_session: AsyncSession,
        published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        """结束工序时传 owner：拒绝，执行人仅开始时可指定。"""
        node_a = published_route["node_a"]
        batch = await self._make_batch(db_session, published_route)
        await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(node_id=node_a.id),
            user=None,
        )

        result = await _call(
            db_session,
            change_batch_step_status,
            operator_id=str(test_user.id),
            batch_no=batch.batch_no,
            step_name=node_a.name,
            action="end",
            owner="张三",
        )
        assert result.is_error is True
        content = "".join(getattr(b, "text", "") for b in result.content)
        assert "仅可在开始工序" in content

    async def test_self_name_not_shadowed_by_candidate(
        self,
        db_session: AsyncSession,
        published_route: dict[str, Any],
        monkeypatch: Any,
    ) -> None:
        """操作人姓名是某候选姓名的前缀时，传自己姓名仍绑定本人。

        候选「X丰」包含操作人姓名「X」。本人判定若排在候选匹配之后，
        包含式匹配会把这次执行静默绑给「X丰」。
        """
        self._no_perms(monkeypatch)
        route_id = published_route["route"].id
        node_a = published_route["node_a"]
        op = await _make_plain_user(db_session)
        await self._grant_start_permission(db_session, route_id, node_a.id, op.id)
        shadow = await self._make_candidate(
            db_session, route_id, node_a.id, assigned_by=op.id,
            name=f"{op.name}丰",
        )
        batch = await self._make_batch(db_session, published_route)

        result = await _call(
            db_session,
            change_batch_step_status,
            operator_id=str(op.id),
            batch_no=batch.batch_no,
            step_name=node_a.name,
            action="start",
            owner=op.name,
        )
        assert result.is_error is False
        [ex] = await self._executions_of(db_session, batch.id, node_a.id)
        assert ex.owner_id == op.id
        assert ex.owner_id != shadow.id

    async def test_start_with_owner_by_user_id(
        self,
        db_session: AsyncSession,
        published_route: dict[str, Any],
        test_user: User,
        monkeypatch: Any,
    ) -> None:
        """按飞书 user_id 指定执行人：姓名无命中时走精确标识解析。"""
        self._no_perms(monkeypatch)
        route_id = published_route["route"].id
        node_a = published_route["node_a"]
        await self._grant_start_permission(db_session, route_id, node_a.id, test_user.id)
        cand = await self._make_candidate(
            db_session, route_id, node_a.id, assigned_by=test_user.id,
        )
        batch = await self._make_batch(db_session, published_route)

        result = await _call(
            db_session,
            change_batch_step_status,
            operator_id=str(test_user.id),
            batch_no=batch.batch_no,
            step_name=node_a.name,
            action="start",
            owner=str(cand.id),
        )
        assert result.is_error is False
        [ex] = await self._executions_of(db_session, batch.id, node_a.id)
        assert ex.owner_id == cand.id

    async def test_designated_owner_can_end_execution(
        self,
        db_session: AsyncSession,
        published_route: dict[str, Any],
        test_user: User,
        monkeypatch: Any,
    ) -> None:
        """代开工后由被指定的执行人本人结束：放行，卡片负责人为该执行人。

        开工后把执行人的 NodeAssignment 移出（候选身份本身会带来节点权限），
        使「单次执行负责人」豁免成为唯一通路——complete_execution 一旦不再
        传入 execution，本用例即红。
        """
        self._no_perms(monkeypatch)
        route_id = published_route["route"].id
        node_a = published_route["node_a"]
        await self._grant_start_permission(db_session, route_id, node_a.id, test_user.id)
        executor = await self._make_candidate(
            db_session, route_id, node_a.id, assigned_by=test_user.id,
        )
        batch = await self._make_batch(db_session, published_route)

        started = await _call(
            db_session,
            change_batch_step_status,
            operator_id=str(test_user.id),
            batch_no=batch.batch_no,
            step_name=node_a.name,
            action="start",
            owner=executor.name,
        )
        assert started.is_error is False

        for na in await assignment_service.list_node_assignments(
            db_session, node_id=node_a.id, assigned_by=test_user.id,
        ):
            await assignment_service.delete_node_assignment(db_session, na.id)

        ended = await _call(
            db_session,
            change_batch_step_status,
            operator_id=str(executor.id),
            batch_no=batch.batch_no,
            step_name=node_a.name,
            action="end",
        )
        assert ended.is_error is False
        content = "".join(getattr(b, "text", "") for b in ended.content)
        # 负责人是执行人而非结束操作人（卡片与 execution.owner 同口径）
        assert f"| 负责人 | {executor.name} |" in content
        [ex] = await self._executions_of(db_session, batch.id, node_a.id)
        assert ex.status == "completed"
        assert ex.owner_id == executor.id


class TestQueryStepFieldsExecutors:
    """query_step_fields start 阶段附带可选工序执行人名单。"""

    async def test_start_phase_lists_configured_candidates(
        self,
        db_session: AsyncSession,
        published_route: dict[str, Any],
        test_user: User,
    ) -> None:
        from app.modules.production.mcp_tools.fields import query_step_fields

        route_id = published_route["route"].id
        node_a = published_route["node_a"]
        cand = await assignment_service.create_node_assignment(
            db_session,
            user_id=test_user.id,
            node_id=node_a.id,
            route_id=route_id,
            assigned_by=test_user.id,
        )
        assert cand.assigned_by == test_user.id
        batch = await batch_service.create_batch(
            db_session,
            BatchCreate(
                batch_no=rand_code("B"),
                product_id=published_route["product"].id,
                route_id=route_id,
            ),
            user=None,
        )

        result = await _call(
            db_session,
            query_step_fields,
            batch_no=batch.batch_no,
            step_name=node_a.name,
            phase="start",
            operator_id=str(test_user.id),
        )
        assert result.is_error is False
        content = "".join(getattr(b, "text", "") for b in result.content)
        assert "可选工序执行人" in content
        assert test_user.name in content

        result_end = await _call(
            db_session,
            query_step_fields,
            batch_no=batch.batch_no,
            step_name=node_a.name,
            phase="end",
            operator_id=str(test_user.id),
        )
        content_end = "".join(
            getattr(b, "text", "") for b in result_end.content
        )
        assert "可选工序执行人" not in content_end

    async def test_start_phase_without_candidates(
        self,
        db_session: AsyncSession,
        published_route: dict[str, Any],
    ) -> None:
        from app.modules.production.mcp_tools.fields import query_step_fields

        plain = await _make_plain_user(db_session)
        batch = await batch_service.create_batch(
            db_session,
            BatchCreate(
                batch_no=rand_code("B"),
                product_id=published_route["product"].id,
                route_id=published_route["route"].id,
            ),
            user=None,
        )

        result = await _call(
            db_session,
            query_step_fields,
            batch_no=batch.batch_no,
            step_name=published_route["node_a"].name,
            phase="start",
            operator_id=str(plain.id),
        )
        assert result.is_error is False
        content = "".join(getattr(b, "text", "") for b in result.content)
        assert "未为该工序配置默认执行人" in content


class TestQueryStepFieldsPhase:
    """query_step_fields 的 phase 口径。

    缺填判定只有 end 口径（start 必填在开工时已强制、且不可补录），
    查 start 阶段时不能拿 end 的缺填结果顶替。
    """

    async def _make_completed_b_without_end_value(
        self, db: AsyncSession, ctx: dict[str, Any],
    ) -> Any:
        """辅助：建批 → 完成起点 A → 开始并结束 B（不填 end 必填 yield_qty）。"""
        batch = await batch_service.create_batch(
            db,
            BatchCreate(
                batch_no=rand_code("B"),
                product_id=ctx["product"].id,
                route_id=ctx["route"].id,
            ),
            user=None,
        )
        ex_a = await execution_service.start_execution(
            db, batch.id, ExecutionStartIn(node_id=ctx["node_a"].id), user=None,
        )
        await execution_service.complete_execution(
            db, ex_a.id, ExecutionCompleteIn(), user=None,
        )
        ex_b = await execution_service.start_execution(
            db,
            batch.id,
            ExecutionStartIn(
                node_id=ctx["node_b"].id,
                field_values=[FieldValueIn(field_key="temp", value=25)],
            ),
            user=None,
        )
        await execution_service.complete_execution(
            db, ex_b.id, ExecutionCompleteIn(), user=None,
        )
        return batch

    async def test_start_phase_does_not_report_end_missing_fields(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """查 start 阶段：不显示 end 的待补录字段，改为提示开工先决条件不可补录。"""
        from app.modules.production.mcp_tools.fields import query_step_fields

        batch = await self._make_completed_b_without_end_value(
            db_session, published_route,
        )
        result = await _call(
            db_session,
            query_step_fields,
            batch_no=batch.batch_no,
            step_name=published_route["node_b"].name,
            phase="start",
        )
        content = "".join(getattr(b, "text", "") for b in result.content)
        assert "待补录必填字段" not in content
        assert "不支持事后补录" in content

    async def test_end_phase_reports_missing_fields(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """查 end 阶段：缺填判定照旧生效（yield_qty 待补录）。"""
        from app.modules.production.mcp_tools.fields import query_step_fields

        batch = await self._make_completed_b_without_end_value(
            db_session, published_route,
        )
        result = await _call(
            db_session,
            query_step_fields,
            batch_no=batch.batch_no,
            step_name=published_route["node_b"].name,
            phase="end",
        )
        content = "".join(getattr(b, "text", "") for b in result.content)
        assert "待补录必填字段" in content
        assert "产出量" in content


class TestQueryUserActiveBatchesForOwner:
    """单次执行负责人经 Agent 的批次可见性（归属他人批次也可见自己执行所在批次）。"""

    async def test_owner_sees_batch_of_others(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        from app.modules.production.mcp_tools.user_scope import (
            query_user_active_batches,
        )

        owner = await _make_plain_user(db_session)
        batch = await batch_service.create_batch(
            db_session,
            BatchCreate(
                batch_no=rand_code("B"),
                product_id=published_route["product"].id,
                route_id=published_route["route"].id,
            ),
            user=None,
        )
        batch.owner_user_id = uuid.uuid4()  # 批次归属他人
        await execution_service.start_execution(
            db_session,
            batch.id,
            ExecutionStartIn(
                node_id=published_route["node_a"].id,
                owner_id=owner.id,
                owner_name=owner.name,
            ),
            user=None,
        )
        result = await _call(
            db_session, query_user_active_batches, operator_id=str(owner.id),
        )
        content = "".join(getattr(b, "text", "") for b in result.content)
        assert batch.batch_no in content
        assert result.is_error is False

    async def test_plain_user_without_execution_sees_nothing(
        self, db_session: AsyncSession,
    ) -> None:
        from app.modules.production.mcp_tools.user_scope import (
            query_user_active_batches,
        )

        plain = await _make_plain_user(db_session)
        result = await _call(
            db_session, query_user_active_batches, operator_id=str(plain.id),
        )
        content = "".join(getattr(b, "text", "") for b in result.content)
        assert "没有负责任何工序" in content
