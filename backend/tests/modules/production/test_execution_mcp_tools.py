"""工序执行 MCP 工具测试 — change_batch_step_status 的错误结果标记。

背景：工具捕获业务异常返回错误文案时必须标记 is_error=True，
中间件据此回滚会话——否则失败操作中已入会话的写操作会被提交落库。
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.mcp_tools.execution import change_batch_step_status
from app.modules.production.schemas import BatchCreate, ExecutionStartIn
from app.modules.production.service import batch_service, execution_service
from app.platform.identity.models import User
from app.platform.mcp.deps import reset_context, set_context
from tests.modules.production.conftest import rand_code


async def _make_plain_user(db: AsyncSession) -> User:
    """无任何工段/工序身份/权限码的用户。"""
    user = User(name=f"路人-{rand_code('U')}", employee_no=rand_code("EMP"))
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
