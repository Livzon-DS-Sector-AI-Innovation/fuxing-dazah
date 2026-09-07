"""生产通知配置 API 测试。

GET / PUT 通知配置：权限校验、默认值、upsert、入参校验。
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.main import app
from app.modules.production.models import NotificationConfig
from app.modules.production.service.reminder_service import NOTIFICATION_TYPES
from app.platform.identity.deps import get_current_user
from app.platform.identity.models import User


@pytest.fixture(autouse=True)
async def _clean_notification_configs(db_session: AsyncSession) -> None:
    """清空通知配置（会话结束时回滚，不污染 dev 库），默认值断言依赖空表。"""
    await db_session.execute(delete(NotificationConfig))


@pytest.fixture
async def manage_client(
    db_session: AsyncSession, test_user: User,
) -> AsyncIterator[AsyncClient]:
    """HTTP 客户端：共享会话 + 固定用户 + 放行通知配置权限。"""

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    async def _override_get_current_user() -> User:
        return test_user

    async def _grant_manage_perms(user_id: str, db: object) -> set[str]:
        return {"production:notification:manage"}

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user
    with patch(
        "app.platform.permission.deps.get_user_permissions",
        new=_grant_manage_perms,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    app.dependency_overrides.clear()


class TestListNotificationConfigs:
    async def test_requires_manage_permission(
        self, manage_client: AsyncClient,
    ) -> None:
        """无 production:notification:manage 权限：403。"""

        async def _no_perms(user_id: str, db: object) -> set[str]:
            return set()

        with patch(
            "app.platform.permission.deps.get_user_permissions", new=_no_perms,
        ):
            resp = await manage_client.get("/api/v1/production/notification-configs")
            assert resp.status_code == 403

    async def test_returns_all_types_with_defaults(
        self, manage_client: AsyncClient,
    ) -> None:
        """无配置行：返回全部类型，默认启用、无额外人员。"""
        resp = await manage_client.get("/api/v1/production/notification-configs")
        assert resp.status_code == 200, resp.text
        data: list[dict[str, Any]] = resp.json()["data"]
        assert [c["notify_type"] for c in data] == list(NOTIFICATION_TYPES)
        assert all(c["is_enabled"] for c in data)
        assert all(c["extra_user_ids"] == [] for c in data)
        # 每类通知都带名称与说明（配置页展示用）
        assert all(c["name"] and c["description"] for c in data)


class TestUpdateNotificationConfig:
    async def test_upsert_and_read_back(
        self, manage_client: AsyncClient, test_user: User,
    ) -> None:
        """PUT 更新配置（禁用 + 额外人员），GET 读回一致。"""
        resp = await manage_client.put(
            "/api/v1/production/notification-configs/plan_released",
            json={"is_enabled": False, "extra_user_ids": [str(test_user.id)]},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["notify_type"] == "plan_released"
        assert body["is_enabled"] is False
        assert body["extra_user_ids"] == [str(test_user.id)]

        # 再次 PUT 同一类型：走 ON CONFLICT DO UPDATE 分支（部分唯一索引推断）
        resp = await manage_client.put(
            "/api/v1/production/notification-configs/plan_released",
            json={"is_enabled": True, "extra_user_ids": []},
        )
        assert resp.status_code == 200, resp.text

        resp = await manage_client.get("/api/v1/production/notification-configs")
        data = resp.json()["data"]
        plan_released = next(c for c in data if c["notify_type"] == "plan_released")
        assert plan_released["is_enabled"] is True
        assert plan_released["extra_user_ids"] == []
        # 其他类型不受影响
        step = next(c for c in data if c["notify_type"] == "step_completed")
        assert step["is_enabled"] is True

    async def test_unknown_type_returns_404(
        self, manage_client: AsyncClient,
    ) -> None:
        resp = await manage_client.put(
            "/api/v1/production/notification-configs/not_a_type",
            json={"is_enabled": True, "extra_user_ids": []},
        )
        assert resp.status_code == 404

    async def test_nonexistent_user_rejected(
        self, manage_client: AsyncClient,
    ) -> None:
        """额外人员必须是存在且未删除的用户。"""
        resp = await manage_client.put(
            "/api/v1/production/notification-configs/plan_completed",
            json={"is_enabled": True, "extra_user_ids": [str(uuid.uuid4())]},
        )
        assert resp.status_code == 400
        assert "不存在" in resp.json()["message"]

    async def test_dedups_extra_user_ids(
        self, manage_client: AsyncClient, test_user: User,
    ) -> None:
        """重复 user_id 入参去重后落库。"""
        resp = await manage_client.put(
            "/api/v1/production/notification-configs/batch_start_due",
            json={
                "is_enabled": True,
                "extra_user_ids": [str(test_user.id), str(test_user.id)],
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["extra_user_ids"] == [str(test_user.id)]
