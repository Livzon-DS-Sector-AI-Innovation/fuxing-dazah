"""meter API 鉴权测试：未登录 401、无权限 403、破坏性端点权限映射。

conftest 的 autouse fixture 默认放行全部权限；本文件用内层 patch 覆盖
或绕过 client fixture 来构造「匿名 / 已登录无权限」两种场景。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.main import app as fastapi_app
from tests.conftest import _test_session_factory


class TestMeterAuthz:
    async def test_anonymous_get_rejected(self) -> None:
        """不带登录态访问读取端点应 401。"""
        async with _test_session_factory() as session:

            async def _override_get_db() -> Any:
                yield session

            fastapi_app.dependency_overrides[get_db] = _override_get_db
            transport = ASGITransport(app=fastapi_app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/v1/meter/instruments")
            fastapi_app.dependency_overrides.clear()
            await session.rollback()
        assert resp.status_code == 401

    async def test_anonymous_destructive_rejected(self) -> None:
        """匿名调用台账导入（会软删未出现记录）必须 401，不能进入业务逻辑。"""
        async with _test_session_factory() as session:

            async def _override_get_db() -> Any:
                yield session

            fastapi_app.dependency_overrides[get_db] = _override_get_db
            transport = ASGITransport(app=fastapi_app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.post("/api/v1/meter/instruments/import-ledger")
            fastapi_app.dependency_overrides.clear()
            await session.rollback()
        assert resp.status_code == 401

    async def test_logged_in_without_permission_gets_403(
        self, api_context: tuple[AsyncClient, Any]
    ) -> None:
        """已登录但权限为空：写端点 403。"""
        client, _ = api_context

        async def _no_perms(user_id: str, db: object) -> set[str]:
            return set()

        with patch(
            "app.platform.permission.deps.get_user_permissions", new=_no_perms
        ):
            resp = await client.post(
                "/api/v1/meter/instruments",
                json={"asset_number": f"A-{uuid4().hex[:8]}", "instrument_name": "压力表"},
            )
        assert resp.status_code == 403

    async def test_read_code_grants_read_but_not_write(
        self, api_context: tuple[AsyncClient, Any]
    ) -> None:
        """仅持 instrument:read：列表 200，创建 403。"""
        client, _ = api_context

        async def _read_only(user_id: str, db: object) -> set[str]:
            return {"meter:instrument:read"}

        with patch(
            "app.platform.permission.deps.get_user_permissions", new=_read_only
        ):
            ok = await client.get("/api/v1/meter/instruments")
            forbidden = await client.post(
                "/api/v1/meter/instruments",
                json={"asset_number": f"A-{uuid4().hex[:8]}", "instrument_name": "压力表"},
            )
        assert ok.status_code == 200
        assert forbidden.status_code == 403

    async def test_settings_write_requires_config_manage(
        self, api_context: tuple[AsyncClient, Any]
    ) -> None:
        """PUT /settings 需要 meter:config:manage，普通更新权限不够。"""
        client, _ = api_context

        async def _instrument_only(user_id: str, db: object) -> set[str]:
            return {"meter:instrument:update"}

        with patch(
            "app.platform.permission.deps.get_user_permissions",
            new=_instrument_only,
        ):
            resp = await client.put("/api/v1/meter/settings", json={"notify_time": "18:00"})
        assert resp.status_code == 403

    async def test_overview_excludes_ledger_readers(
        self, api_context: tuple[AsyncClient, Any]
    ) -> None:
        """仅持台账读码：总览 403（管理侧数据）；台账页内嵌的到期提醒照常 200。"""
        client, _ = api_context

        async def _ledger_reader(user_id: str, db: object) -> set[str]:
            return {"meter:instrument:read", "meter:gas-detector:read"}

        with patch(
            "app.platform.permission.deps.get_user_permissions", new=_ledger_reader
        ):
            overview = await client.get("/api/v1/meter/overview")
            alerts = await client.get("/api/v1/meter/calibration/alerts")
        assert overview.status_code == 403
        assert alerts.status_code == 200

    async def test_overview_requires_config_manage(
        self, api_context: tuple[AsyncClient, Any]
    ) -> None:
        """总览只认 config:manage；到期提醒属台账页，按台账读码放行。"""
        client, _ = api_context

        async def _wildcard_only(user_id: str, db: object) -> set[str]:
            return {"meter:*:read"}

        async def _config_only(user_id: str, db: object) -> set[str]:
            return {"meter:config:manage"}

        with patch(
            "app.platform.permission.deps.get_user_permissions", new=_wildcard_only
        ):
            wildcard_overview = await client.get("/api/v1/meter/overview")
            wildcard_alerts = await client.get("/api/v1/meter/calibration/alerts")
        with patch(
            "app.platform.permission.deps.get_user_permissions", new=_config_only
        ):
            config_overview = await client.get("/api/v1/meter/overview")
            config_alerts = await client.get("/api/v1/meter/calibration/alerts")
        assert wildcard_overview.status_code == 403
        assert wildcard_alerts.status_code == 200
        assert config_overview.status_code == 200
        # 配置管理员不读台账：台账页的提醒面板对它是隐藏的，接口也不放行
        assert config_alerts.status_code == 403

    async def test_departments_readable_with_config_manage_only(
        self, api_context: tuple[AsyncClient, Any]
    ) -> None:
        """只持 config:manage 也能读部门列表（部门管理页由该精确码放行）。"""
        client, _ = api_context

        async def _config_only(user_id: str, db: object) -> set[str]:
            return {"meter:config:manage"}

        with patch(
            "app.platform.permission.deps.get_user_permissions", new=_config_only
        ):
            resp = await client.get("/api/v1/meter/departments")
        assert resp.status_code == 200
