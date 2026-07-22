"""工段与工序负责人分配及权限校验测试。

覆盖业务场景：
- 工段分配 CRUD：创建并列表；重复分配拒绝（DuplicateException）；
  删除后可重新创建相同分配；删除不存在记录抛 NotFoundException
- 工序分配 CRUD：创建并列表；重复分配拒绝；删除不存在记录抛 NotFoundException
- 权限校验：无分配默认无权限；工段权限授予后 check 返回 True；
  工序权限授予后 check 返回 True；require 无权限时抛 ForbiddenException；
  stage_name 为 None 时始终无权限
"""

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    DuplicateException,
    ForbiddenException,
    NotFoundException,
)
from app.modules.production.service import assignment_service


class TestStageAssignment:
    async def test_create_and_list(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """创建工段分配后可在此路线的分配列表中查到。"""
        user_id = uuid.uuid4()
        route_id = published_route["route"].id
        sa = await assignment_service.create_stage_assignment(
            db_session,
            user_id=user_id,
            stage_name="发酵",
            route_id=route_id,
            created_by=user_id,
        )
        assert sa.user_id == user_id
        assert sa.stage_name == "发酵"

        items = await assignment_service.list_stage_assignments(
            db_session, route_id=route_id,
        )
        assert len(items) >= 1
        assert any(s.id == sa.id for s in items)

    async def test_duplicate_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """同一用户在同一路线同一工段上重复分配时抛出 DuplicateException。"""
        user_id = uuid.uuid4()
        route_id = published_route["route"].id
        await assignment_service.create_stage_assignment(
            db_session,
            user_id=user_id,
            stage_name="发酵",
            route_id=route_id,
            created_by=user_id,
        )
        with pytest.raises(DuplicateException):
            await assignment_service.create_stage_assignment(
                db_session,
                user_id=user_id,
                stage_name="发酵",
                route_id=route_id,
                created_by=user_id,
            )

    async def test_delete_and_recreate(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """软删除后同用户+同工段可再次分配，新记录 ID 与旧不同。"""
        user_id = uuid.uuid4()
        route_id = published_route["route"].id
        sa = await assignment_service.create_stage_assignment(
            db_session,
            user_id=user_id,
            stage_name="发酵",
            route_id=route_id,
            created_by=user_id,
        )
        await assignment_service.delete_stage_assignment(db_session, sa.id)
        sa2 = await assignment_service.create_stage_assignment(
            db_session,
            user_id=user_id,
            stage_name="发酵",
            route_id=route_id,
            created_by=user_id,
        )
        assert sa2.id != sa.id

    async def test_delete_nonexistent_rejected(
        self, db_session: AsyncSession,
    ) -> None:
        """删除不存在的工段分配抛出 NotFoundException。"""
        with pytest.raises(NotFoundException):
            await assignment_service.delete_stage_assignment(
                db_session, uuid.uuid4(),
            )


class TestNodeAssignment:
    async def test_create_and_list(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """创建工序分配后可在此路线的分配列表中查到。"""
        user_id = uuid.uuid4()
        node_id = published_route["node_a"].id
        route_id = published_route["route"].id
        na = await assignment_service.create_node_assignment(
            db_session,
            user_id=user_id,
            node_id=node_id,
            route_id=route_id,
            assigned_by=user_id,
        )
        assert na.user_id == user_id

        items = await assignment_service.list_node_assignments(
            db_session, route_id=route_id,
        )
        assert len(items) >= 1

    async def test_duplicate_rejected(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """同一用户在同一节点上重复分配时抛出 DuplicateException。"""
        user_id = uuid.uuid4()
        node_id = published_route["node_a"].id
        route_id = published_route["route"].id
        await assignment_service.create_node_assignment(
            db_session,
            user_id=user_id,
            node_id=node_id,
            route_id=route_id,
            assigned_by=user_id,
        )
        with pytest.raises(DuplicateException):
            await assignment_service.create_node_assignment(
                db_session,
                user_id=user_id,
                node_id=node_id,
                route_id=route_id,
                assigned_by=user_id,
            )

    async def test_delete_nonexistent_rejected(
        self, db_session: AsyncSession,
    ) -> None:
        """删除不存在的工序分配抛出 NotFoundException。"""
        with pytest.raises(NotFoundException):
            await assignment_service.delete_node_assignment(
                db_session, uuid.uuid4(),
            )


class TestPermissionCheck:
    async def test_no_permission_by_default(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """未分配任何权限的用户 check_stage_permission 返回 False。"""
        has_perm = await assignment_service.check_stage_permission(
            db_session,
            user_id=uuid.uuid4(),
            node_id=published_route["node_a"].id,
            route_id=published_route["route"].id,
            stage_name="发酵",
        )
        assert has_perm is False

    async def test_stage_permission_granted(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """分配工段权限后 check_stage_permission 返回 True。"""
        user_id = uuid.uuid4()
        route_id = published_route["route"].id
        await assignment_service.create_stage_assignment(
            db_session,
            user_id=user_id,
            stage_name="发酵",
            route_id=route_id,
            created_by=user_id,
        )
        has_perm = await assignment_service.check_stage_permission(
            db_session,
            user_id=user_id,
            node_id=published_route["node_a"].id,
            route_id=route_id,
            stage_name="发酵",
        )
        assert has_perm is True

    async def test_node_permission_granted(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """分配工序权限后 check_stage_permission 对该节点返回 True。"""
        user_id = uuid.uuid4()
        node_id = published_route["node_a"].id
        route_id = published_route["route"].id
        await assignment_service.create_node_assignment(
            db_session,
            user_id=user_id,
            node_id=node_id,
            route_id=route_id,
            assigned_by=user_id,
        )
        has_perm = await assignment_service.check_stage_permission(
            db_session,
            user_id=user_id,
            node_id=node_id,
            route_id=route_id,
            stage_name="发酵",
        )
        assert has_perm is True

    async def test_require_permission_raises_when_denied(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """无权限时 require_stage_permission 抛出 ForbiddenException。"""
        with pytest.raises(ForbiddenException):
            await assignment_service.require_stage_permission(
                db_session,
                user_id=uuid.uuid4(),
                node_id=published_route["node_a"].id,
                route_id=published_route["route"].id,
                stage_name="发酵",
            )

    async def test_permission_none_stage_name_denied(
        self, db_session: AsyncSession, published_route: dict[str, Any],
    ) -> None:
        """stage_name 为 None 时 check_stage_permission 始终返回 False。"""
        has_perm = await assignment_service.check_stage_permission(
            db_session,
            user_id=uuid.uuid4(),
            node_id=published_route["node_a"].id,
            route_id=published_route["route"].id,
            stage_name=None,
        )
        assert has_perm is False
