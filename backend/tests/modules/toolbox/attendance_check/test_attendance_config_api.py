"""工具箱工具配置读写端点测试（配置读写已加鉴权，这里以超管身份覆盖）。"""

from types import SimpleNamespace
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.toolbox import api
from app.modules.toolbox.repository import get_tool_config
from tests.modules.toolbox.conftest import FakeRedis


@pytest.fixture
def client(
    fake_redis: FakeRedis,
    fake_user: SimpleNamespace,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncClient:
    """测试应用：挂 toolbox router，注入 FakeRedis、超管假用户与回滚测试会话。"""
    from fastapi import FastAPI

    # 配置读写端点要求 can_config；以超管身份（拥有 permission:role:manage）放行
    import app.modules.toolbox.service as service_mod

    async def _admin_perms(_user_id: str, _db: object) -> set[str]:
        return {"permission:role:manage"}

    monkeypatch.setattr(service_mod, "get_user_permissions", _admin_perms)

    app = FastAPI()
    app.include_router(api.router)

    async def fake_user_dep() -> SimpleNamespace:
        return fake_user

    async def fake_redis_dep() -> FakeRedis:
        return fake_redis

    async def fake_db_dep() -> Any:
        yield db_session

    app.dependency_overrides[api.get_current_user] = fake_user_dep  # type: ignore[attr-defined]
    app.dependency_overrides[api.get_redis] = fake_redis_dep  # type: ignore[attr-defined]
    app.dependency_overrides[api.get_db] = fake_db_dep  # type: ignore[attr-defined]
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


CONFIG = {
    "feishu": {"app_id": "cli_test", "app_secret": "secret"},
    "bitable": {"app_token": "tok", "attendance_result_table_id": "tbl1"},
    "offset_minutes": 180,
    "overtime_gap_minutes": 60,
}


async def test_get_config_returns_db_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.modules.toolbox.repository import upsert_tool_config

    await upsert_tool_config(db_session, "attendance-check", CONFIG)

    resp = await client.get("/tools/attendance-check/config")
    assert resp.status_code == 200
    assert resp.json()["data"] == CONFIG


async def test_get_config_missing_row_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    resp = await client.get("/tools/attendance-check/config")
    assert resp.status_code == 404


async def test_put_config_upserts_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.modules.toolbox.repository import upsert_tool_config

    await upsert_tool_config(db_session, "attendance-check", CONFIG)

    new_config = {**CONFIG, "offset_minutes": 60}
    resp = await client.put("/tools/attendance-check/config", json=new_config)
    assert resp.status_code == 200
    row = await get_tool_config(db_session, "attendance-check")
    assert row is not None and row.config == new_config


async def test_put_config_creates_row_when_missing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """数据库无行时 PUT 允许首次创建（原文件版要求文件已存在）。"""
    resp = await client.put("/tools/attendance-check/config", json=CONFIG)
    assert resp.status_code == 200
    row = await get_tool_config(db_session, "attendance-check")
    assert row is not None and row.config == CONFIG


async def test_put_config_invalid_json_400(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.modules.toolbox.repository import upsert_tool_config

    await upsert_tool_config(db_session, "attendance-check", CONFIG)

    resp = await client.put(
        "/tools/attendance-check/config",
        content=b"{not-json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    # 原有配置未被破坏
    row = await get_tool_config(db_session, "attendance-check")
    assert row is not None and row.config == CONFIG


async def test_put_config_non_object_400(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.modules.toolbox.repository import upsert_tool_config

    await upsert_tool_config(db_session, "attendance-check", CONFIG)

    resp = await client.put("/tools/attendance-check/config", json=[1, 2, 3])
    assert resp.status_code == 400
    row = await get_tool_config(db_session, "attendance-check")
    assert row is not None and row.config == CONFIG
