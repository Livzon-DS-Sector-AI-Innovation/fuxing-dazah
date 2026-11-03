"""QA API 鉴权测试：未登录 401、无权限 403、读取需 ``qa:*:read``。

对齐 meter 的 test_api_authz 模式：匿名场景仅覆盖 get_db，
已登录场景再覆盖 get_current_user 并 patch 权限集合。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import get_db
from app.main import app as fastapi_app
from app.platform.identity.deps import get_current_user
from app.platform.identity.models import User
from tests.conftest import _test_session_factory


async def _ensure_test_user(session: Any) -> User:
    """取已有用户或现场造一个，供 get_current_user 覆盖使用。"""
    stmt = select(User).where(User.is_deleted == False).limit(1)  # noqa: E712
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing:
        return existing
    user = User(name="qa测试用户", employee_no="QA-TEST-001")
    session.add(user)
    await session.flush()
    return user


class TestQaAuthz:
    async def test_anonymous_get_rejected(self) -> None:
        """不带登录态访问读取端点应 401。"""
        async with _test_session_factory() as session:

            async def _override_get_db() -> Any:
                yield session

            fastapi_app.dependency_overrides[get_db] = _override_get_db
            transport = ASGITransport(app=fastapi_app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/v1/qa/master-objects")
            fastapi_app.dependency_overrides.clear()
            await session.rollback()
        assert resp.status_code == 401

    async def test_logged_in_without_permission_gets_403(self) -> None:
        """已登录但无 QA 权限：读取端点 403（读取不再默认放行）。"""
        async with _test_session_factory() as session:
            test_user = await _ensure_test_user(session)

            async def _override_get_db() -> Any:
                yield session

            async def _override_get_current_user() -> Any:
                return test_user

            fastapi_app.dependency_overrides[get_db] = _override_get_db
            fastapi_app.dependency_overrides[get_current_user] = _override_get_current_user

            async def _no_perms(user_id: str, db: object) -> set[str]:
                return set()

            transport = ASGITransport(app=fastapi_app)
            with patch(
                "app.platform.permission.deps.get_user_permissions", new=_no_perms
            ):
                async with AsyncClient(
                    transport=transport, base_url="http://test"
                ) as ac:
                    resp = await ac.get("/api/v1/qa/master-objects")
            fastapi_app.dependency_overrides.clear()
            await session.rollback()
        assert resp.status_code == 403

    async def test_read_code_grants_read_but_not_write(self) -> None:
        """仅持 qa:*:read：主数据列表 200，创建 403。"""
        async with _test_session_factory() as session:
            test_user = await _ensure_test_user(session)

            async def _override_get_db() -> Any:
                yield session

            async def _override_get_current_user() -> Any:
                return test_user

            fastapi_app.dependency_overrides[get_db] = _override_get_db
            fastapi_app.dependency_overrides[get_current_user] = _override_get_current_user

            async def _read_only(user_id: str, db: object) -> set[str]:
                return {"qa:*:read"}

            transport = ASGITransport(app=fastapi_app)
            with patch(
                "app.platform.permission.deps.get_user_permissions", new=_read_only
            ):
                async with AsyncClient(
                    transport=transport, base_url="http://test"
                ) as ac:
                    ok = await ac.get("/api/v1/qa/master-objects")
                    forbidden = await ac.post(
                        "/api/v1/qa/master-objects",
                        json={
                            "object_type": "MATERIAL",
                            "code": f"QA-{uuid4().hex[:8]}",
                            "name": "鉴权测试主数据",
                        },
                    )
            fastapi_app.dependency_overrides.clear()
            await session.rollback()
        assert ok.status_code == 200
        assert forbidden.status_code == 403

    async def test_read_code_does_not_grant_audit(self) -> None:
        """仅持 qa:*:read：审计日志仍 403，需独立的 qa:audit:read。"""
        async with _test_session_factory() as session:
            test_user = await _ensure_test_user(session)

            async def _override_get_db() -> Any:
                yield session

            async def _override_get_current_user() -> Any:
                return test_user

            fastapi_app.dependency_overrides[get_db] = _override_get_db
            fastapi_app.dependency_overrides[get_current_user] = _override_get_current_user

            async def _read_only(user_id: str, db: object) -> set[str]:
                return {"qa:*:read"}

            transport = ASGITransport(app=fastapi_app)
            with patch(
                "app.platform.permission.deps.get_user_permissions", new=_read_only
            ):
                async with AsyncClient(
                    transport=transport, base_url="http://test"
                ) as ac:
                    resp = await ac.get("/api/v1/qa/audit-logs")
            fastapi_app.dependency_overrides.clear()
            await session.rollback()
        assert resp.status_code == 403
