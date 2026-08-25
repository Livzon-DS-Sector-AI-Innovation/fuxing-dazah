"""工具箱使用权限（tool_grants）与鉴权测试。"""

import json
import uuid
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, Protocol

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.toolbox import api
from app.modules.toolbox.models import ToolGrant
from app.modules.toolbox.registry import StepContext, ToolStep, tool
from app.platform.identity.models import User
from tests.modules.toolbox.conftest import FakeRedis

TOOL_ID = "t-grant"

MakeUser = Callable[[str], Awaitable[User]]
GrantsClient = tuple[AsyncClient, dict[str, SimpleNamespace]]


class AddGrant(Protocol):
    async def __call__(
        self, user: User, tool_id: str, *, can_use: bool, can_config: bool
    ) -> None: ...


@tool(
    id=TOOL_ID,
    name="授权测试工具",
    description="使用权限集成测试",
    steps=[ToolStep(id="s1", name="执行", description="", inputs=[])],
)
async def _grant_tool_run(
    step_id: str, params: dict[str, Any], context: StepContext
) -> dict[str, Any]:
    return {"ok": True}


@pytest.fixture
async def make_user(db_session: AsyncSession) -> MakeUser:
    """在回滚测试会话中创建 identity 用户。"""

    async def _make(name: str) -> User:
        user = User(name=name, employee_no=f"tg-{uuid.uuid4().hex[:10]}")
        db_session.add(user)
        await db_session.flush()
        return user

    return _make


@pytest.fixture
async def add_grant(db_session: AsyncSession) -> AddGrant:
    """写入一条授权行。"""

    async def _add(
        user: User, tool_id: str, *, can_use: bool, can_config: bool
    ) -> None:
        db_session.add(
            ToolGrant(
                user_id=user.id,
                tool_id=tool_id,
                can_use=can_use,
                can_config=can_config,
            )
        )
        await db_session.flush()

    return _add


@pytest.fixture
def grants_client(
    fake_redis: FakeRedis,
    db_session: AsyncSession,
) -> GrantsClient:
    """测试应用：切换当前用户/管理员，注入 FakeRedis 与回滚测试会话。"""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(api.router)

    state: dict[str, SimpleNamespace] = {}

    async def fake_user_dep() -> SimpleNamespace | None:
        return state.get("user")

    async def fake_redis_dep() -> FakeRedis:
        return fake_redis

    async def fake_db_dep() -> Any:
        yield db_session

    async def fake_admin_dep() -> SimpleNamespace | None:
        return state.get("admin")

    app.dependency_overrides[api.get_current_user] = fake_user_dep  # type: ignore[attr-defined]
    app.dependency_overrides[api.get_redis] = fake_redis_dep  # type: ignore[attr-defined]
    app.dependency_overrides[api.get_db] = fake_db_dep  # type: ignore[attr-defined]
    app.dependency_overrides[api.require_admin] = fake_admin_dep  # type: ignore[attr-defined]
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return client, state


async def test_default_open_run_and_list(
    grants_client: GrantsClient,
    make_user: MakeUser,
) -> None:
    """无授权记录的工具默认开放：任意登录用户可用、可配置标志为 False。"""
    client, state = grants_client
    user1 = await make_user("u1")
    state["user"] = SimpleNamespace(id=str(user1.id))

    resp = await client.post(f"/tools/{TOOL_ID}/steps/s1/run", data={"params": "{}"})
    assert resp.status_code == 200, resp.text

    tools = (await client.get("/tools")).json()["data"]
    grant_tool = next(t for t in tools if t["id"] == TOOL_ID)
    assert grant_tool["can_use"] is True
    assert grant_tool["can_config"] is False


async def test_restricted_tool_visible_but_blocked(
    grants_client: GrantsClient,
    make_user: MakeUser,
    add_grant: AddGrant,
) -> None:
    """配置名单后：名单外用户仍能看到卡片（can_use=False）但 run 403；名单内用户可 run。"""
    client, state = grants_client
    u1 = await make_user("u1")
    u2 = await make_user("u2")
    await add_grant(u2, TOOL_ID, can_use=True, can_config=False)

    state["user"] = SimpleNamespace(id=str(u1.id))
    tools = (await client.get("/tools")).json()["data"]
    grant_tool = next(t for t in tools if t["id"] == TOOL_ID)
    assert grant_tool["can_use"] is False
    assert grant_tool["can_config"] is False

    run = await client.post(f"/tools/{TOOL_ID}/steps/s1/run", data={"params": "{}"})
    assert run.status_code == 403

    state["user"] = SimpleNamespace(id=str(u2.id))
    run2 = await client.post(f"/tools/{TOOL_ID}/steps/s1/run", data={"params": "{}"})
    assert run2.status_code == 200, run2.text
    tools2 = (await client.get("/tools")).json()["data"]
    grant_tool2 = next(t for t in tools2 if t["id"] == TOOL_ID)
    assert grant_tool2["can_use"] is True


async def test_config_user_implies_use(
    grants_client: GrantsClient,
    make_user: MakeUser,
    add_grant: AddGrant,
) -> None:
    """配置名单成员隐含使用权限。"""
    client, state = grants_client
    u = await make_user("config-user")
    await add_grant(u, TOOL_ID, can_use=False, can_config=True)

    state["user"] = SimpleNamespace(id=str(u.id))
    run = await client.post(f"/tools/{TOOL_ID}/steps/s1/run", data={"params": "{}"})
    assert run.status_code == 200, run.text
    tools = (await client.get("/tools")).json()["data"]
    grant_tool = next(t for t in tools if t["id"] == TOOL_ID)
    assert grant_tool["can_use"] is True
    assert grant_tool["can_config"] is True


async def test_use_only_user_cannot_read_config(
    grants_client: GrantsClient,
    make_user: MakeUser,
    add_grant: AddGrant,
) -> None:
    """仅使用名单成员不能读写工具配置（403）。"""
    client, state = grants_client
    u1 = await make_user("u1")
    await add_grant(u1, "attendance-check", can_use=True, can_config=False)

    state["user"] = SimpleNamespace(id=str(u1.id))
    resp = await client.get("/tools/attendance-check/config")
    assert resp.status_code == 403
    resp = await client.put("/tools/attendance-check/config", json={"offset_minutes": 2})
    assert resp.status_code == 403

    tools = (await client.get("/tools")).json()["data"]
    tool = next(t for t in tools if t["id"] == "attendance-check")
    assert tool["can_use"] is True
    assert tool["can_config"] is False


async def test_admin_bypass_everything(
    grants_client: GrantsClient,
    make_user: MakeUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """超管（permission:role:manage）不受授权限制，全工具可见且 can 标志全 True。"""
    client, state = grants_client
    u1 = await make_user("u1")
    state["user"] = SimpleNamespace(id=str(u1.id))

    import app.modules.toolbox.service as service_mod

    async def _admin_perms(_user_id: str, _db: object) -> set[str]:
        return {"permission:role:manage"}

    monkeypatch.setattr(service_mod, "get_user_permissions", _admin_perms)

    run = await client.post(f"/tools/{TOOL_ID}/steps/s1/run", data={"params": "{}"})
    assert run.status_code == 200, run.text

    tools = (await client.get("/tools")).json()["data"]
    ids = {t["id"] for t in tools}
    assert TOOL_ID in ids and "attendance-check" in ids
    grant_tool = next(t for t in tools if t["id"] == TOOL_ID)
    assert grant_tool["can_use"] is True
    assert grant_tool["can_config"] is True


async def test_grant_management_endpoints(
    grants_client: GrantsClient,
    make_user: MakeUser,
) -> None:
    """管理端点：概览、整体替换、清空恢复默认、无效输入校验。"""
    client, state = grants_client
    admin = await make_user("admin")
    u1 = await make_user("u1")
    u2 = await make_user("u2")
    state["admin"] = SimpleNamespace(id=str(admin.id))

    # 概览：全部工具、空名单
    resp = await client.get("/tool-grants")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    ids = {g["tool_id"] for g in data}
    assert TOOL_ID in ids and "attendance-check" in ids
    target = next(g for g in data if g["tool_id"] == TOOL_ID)
    assert target["use_users"] == []
    assert target["config_users"] == []

    # 整体替换名单（配置名单成员隐含使用权限 → u2 也出现在 use_users）
    resp = await client.put(
        f"/tools/{TOOL_ID}/grants",
        json={"use_user_ids": [str(u1.id)], "config_user_ids": [str(u2.id)]},
    )
    assert resp.status_code == 200, resp.text
    target = resp.json()["data"]
    assert {u["user_id"] for u in target["use_users"]} == {str(u1.id), str(u2.id)}
    assert [u["user_id"] for u in target["config_users"]] == [str(u2.id)]
    assert {u["name"] for u in target["use_users"]} == {u1.name, u2.name}
    assert target["config_users"][0]["name"] == u2.name

    # 回读一致
    data2 = (await client.get("/tool-grants")).json()["data"]
    target2 = next(g for g in data2 if g["tool_id"] == TOOL_ID)
    assert len(target2["use_users"]) == 2
    assert len(target2["config_users"]) == 1

    # 清空名单 → 恢复默认开放
    resp = await client.put(
        f"/tools/{TOOL_ID}/grants",
        json={"use_user_ids": [], "config_user_ids": []},
    )
    assert resp.status_code == 200
    data3 = (await client.get("/tool-grants")).json()["data"]
    target3 = next(g for g in data3 if g["tool_id"] == TOOL_ID)
    assert target3["use_users"] == []
    assert target3["config_users"] == []

    # 无效用户 → 400
    resp = await client.put(
        f"/tools/{TOOL_ID}/grants",
        json={"use_user_ids": [str(uuid.uuid4())], "config_user_ids": []},
    )
    assert resp.status_code == 400
    assert "用户不存在" in resp.json()["message"]

    # 未知工具 → 404
    resp = await client.put(
        "/tools/nope/grants",
        json={"use_user_ids": [], "config_user_ids": []},
    )
    assert resp.status_code == 404


async def test_config_check_before_existence(
    grants_client: GrantsClient,
    make_user: MakeUser,
    add_grant: AddGrant,
) -> None:
    """授权校验先于配置存在性：名单外用户探测未配置工具也得到 403 而非 404。"""
    client, state = grants_client
    u1 = await make_user("u1")
    u2 = await make_user("u2")
    await add_grant(u1, "attendance-check", can_use=True, can_config=False)

    # 不写入任何配置：工具受限且未配置时，名单外用户仍应 403

    state["user"] = SimpleNamespace(id=str(u2.id))
    resp = await client.get("/tools/attendance-check/config")
    assert resp.status_code == 403


async def test_execution_access_checked_against_grants(
    grants_client: GrantsClient,
    make_user: MakeUser,
    add_grant: AddGrant,
) -> None:
    """被移出使用名单后，凭旧 execution_id 不能轮询状态/下载产物（403）。"""
    client, state = grants_client
    u1 = await make_user("u1")
    u2 = await make_user("u2")
    state["user"] = SimpleNamespace(id=str(u1.id))
    run = await client.post(f"/tools/{TOOL_ID}/steps/s1/run", data={"params": "{}"})
    assert run.status_code == 200, run.text
    eid = run.json()["data"]["execution_id"]

    # 工具进入限制模式：u2 在名单内，u1 不在
    await add_grant(u2, TOOL_ID, can_use=True, can_config=False)

    resp = await client.get(f"/executions/{eid}")
    assert resp.status_code == 403
    resp2 = await client.get(f"/executions/{eid}/files/whatever")
    assert resp2.status_code == 403

    # 名单内用户仍可访问（但非会话归属者 → 404）
    state["user"] = SimpleNamespace(id=str(u2.id))
    resp3 = await client.get(f"/executions/{eid}")
    assert resp3.status_code == 404


async def test_orphan_grants_visible_and_clearable(
    grants_client: GrantsClient,
    make_user: MakeUser,
    db_session: AsyncSession,
) -> None:
    """不在注册表中的工具授权行仍出现在概览末尾，且可清空；纯未知 ID 仍 404。"""
    client, state = grants_client
    admin = await make_user("admin")
    u1 = await make_user("u1")
    state["admin"] = SimpleNamespace(id=str(admin.id))

    # 直接落一条孤儿授权行（工具已从注册表消失的场景）
    db_session.add(
        ToolGrant(user_id=u1.id, tool_id="ghost-tool", can_use=True, can_config=False)
    )
    await db_session.flush()

    data = (await client.get("/tool-grants")).json()["data"]
    ghost = next(g for g in data if g["tool_id"] == "ghost-tool")
    assert ghost["tool_name"] == "ghost-tool"
    assert {u["user_id"] for u in ghost["use_users"]} == {str(u1.id)}

    # 清空孤儿授权行：允许对未注册但存在授权行的工具提交
    resp = await client.put(
        "/tools/ghost-tool/grants",
        json={"use_user_ids": [], "config_user_ids": []},
    )
    assert resp.status_code == 200, resp.text

    data2 = (await client.get("/tool-grants")).json()["data"]
    assert not any(g["tool_id"] == "ghost-tool" for g in data2)

    # 纯未知 ID 仍 404 防手误
    resp = await client.put(
        "/tools/nope/grants",
        json={"use_user_ids": [], "config_user_ids": []},
    )
    assert resp.status_code == 404


async def test_grant_user_in_both_lists(
    grants_client: GrantsClient,
    make_user: MakeUser,
) -> None:
    """同一用户同时在使用名单与配置名单：两个名单都出现。"""
    client, state = grants_client
    admin = await make_user("admin")
    u1 = await make_user("u1")
    state["admin"] = SimpleNamespace(id=str(admin.id))

    resp = await client.put(
        f"/tools/{TOOL_ID}/grants",
        json={"use_user_ids": [str(u1.id)], "config_user_ids": [str(u1.id)]},
    )
    assert resp.status_code == 200
    target = resp.json()["data"]
    assert [u["user_id"] for u in target["use_users"]] == [str(u1.id)]
    assert [u["user_id"] for u in target["config_users"]] == [str(u1.id)]
