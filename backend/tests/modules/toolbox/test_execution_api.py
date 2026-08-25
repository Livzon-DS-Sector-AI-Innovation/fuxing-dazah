"""工具箱执行端点集成测试（假工具 + FakeRedis 见 conftest）。"""

import json
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.modules.toolbox import api, storage
from app.modules.toolbox.registry import StepContext, ToolInput, ToolStep, tool
from app.modules.toolbox.sessions import _key
from tests.modules.toolbox.conftest import FakeRedis


@pytest.fixture
def client(fake_redis: FakeRedis, fake_user: SimpleNamespace) -> AsyncClient:
    """测试应用：挂 toolbox router，注入 FakeRedis 与假用户。"""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(api.router)

    async def fake_user_dep() -> SimpleNamespace:
        return fake_user

    async def fake_redis_dep() -> FakeRedis:
        return fake_redis

    app.dependency_overrides[api.get_current_user] = fake_user_dep  # type: ignore[attr-defined]
    app.dependency_overrides[api.get_redis] = fake_redis_dep  # type: ignore[attr-defined]
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    client.app = app  # type: ignore[attr-defined]  # 测试便利：暴露 app 以改 dependency_overrides
    return client


def _register_fake_tool() -> None:
    @tool(
        id="t-fake",
        name="假工具",
        description="集成测试",
        steps=[
            ToolStep(
                id="s1",
                name="上传",
                description="",
                inputs=[
                    ToolInput(key="doc", label="文档", type="file", accept=".docx", required=True),
                ],
            ),
            ToolStep(
                id="s2",
                name="汇总",
                description="",
                inputs=[
                    ToolInput(key="doc", label="文档", type="file", from_step="s1", from_key="doc"),
                ],
            ),
        ],
    )
    async def _func(
        step_id: str, params: dict[str, Any], context: StepContext
    ) -> dict[str, Any]:
        if step_id == "s1":
            return {"ok": True, "prev": context.prev_outputs, "paths": context.file_paths.get("doc", [])}
        return {"sum": 2, "prev_s1": context.prev_outputs.get("s1")}


_register_fake_tool()


def _register_multi_tool() -> None:
    @tool(
        id="t-fake-multi",
        name="多文件工具",
        description="多文件集成测试",
        steps=[
            ToolStep(
                id="m1",
                name="批量上传",
                description="",
                inputs=[
                    ToolInput(key="docs", label="文档集", type="file", accept=".docx", required=True, multiple=True),
                ],
            ),
        ],
    )
    async def _func(
        step_id: str, params: dict[str, Any], context: StepContext
    ) -> dict[str, Any]:
        return {"n": len(context.file_paths.get("docs", []))}


_register_multi_tool()


def _register_broken_tool() -> None:
    @tool(
        id="t-broken",
        name="会失败的工具",
        description="未知异常透传测试",
        steps=[ToolStep(id="b1", name="执行", description="", inputs=[])],
    )
    async def _func(
        step_id: str, params: dict[str, Any], context: StepContext
    ) -> dict[str, Any]:
        raise ValueError("模拟的内部错误详情")


_register_broken_tool()


async def test_run_unknown_exception_message_passthrough(client: AsyncClient) -> None:
    """未知异常的消息直接反馈给用户（不再用通用提示掩盖）。"""
    resp = await client.post("/tools/t-broken/steps/b1/run", data={"params": "{}"})
    assert resp.status_code == 500
    assert "模拟的内部错误详情" in resp.json()["message"]


async def test_list_tools(client: AsyncClient) -> None:
    resp = await client.get("/tools")
    assert resp.status_code == 200
    tools = resp.json()["data"]
    fake = next(t for t in tools if t["id"] == "t-fake")
    assert fake["name"] == "假工具"
    assert fake["steps"][0]["inputs"][0]["accept"] == ".docx"


async def test_run_step1_creates_execution_and_saves_file(
    client: AsyncClient, fake_redis: FakeRedis
) -> None:
    resp = await client.post(
        "/tools/t-fake/steps/s1/run",
        data={"params": "{}"},
        files={"doc": ("a.docx", b"fake-docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["execution_id"]
    assert body["data"]["ok"] is True
    assert body["data"]["paths"][0].endswith(".docx")
    assert body["file_ids"]["doc"]  # 恒为列表（单文件也是单元素列表）
    assert len(body["file_ids"]["doc"]) == 1
    # 会话已记录输出与文件
    exec_data = json.loads(fake_redis.store[_key(body["execution_id"])])
    assert exec_data["user_id"] == "user-1"
    assert exec_data["outputs"]["s1"]["ok"] is True


async def test_run_step2_gets_prev_outputs_and_references_file(client: AsyncClient) -> None:
    first = await client.post(
        "/tools/t-fake/steps/s1/run",
        data={"params": "{}"},
        files={"doc": ("a.docx", b"fake-docx", "application/octet-stream")},
    )
    eid = first.json()["data"]["execution_id"]
    fids = first.json()["data"]["file_ids"]["doc"]
    second = await client.post(
        "/tools/t-fake/steps/s2/run",
        data={"execution_id": eid, "params": json.dumps({"doc": {"file_ids": fids}})},
    )
    assert second.status_code == 200, second.text
    data = second.json()["data"]
    assert data["data"]["prev_s1"]["ok"] is True


async def test_run_unknown_tool_404(client: AsyncClient) -> None:
    resp = await client.post("/tools/nope/steps/s1/run", data={"params": "{}"})
    assert resp.status_code == 404


async def test_run_wrong_file_extension_rejected(client: AsyncClient) -> None:
    resp = await client.post(
        "/tools/t-fake/steps/s1/run",
        data={"params": "{}"},
        files={"doc": ("a.exe", b"x", "application/octet-stream")},
    )
    assert resp.status_code == 400
    assert "docx" in resp.json()["message"]


async def test_others_execution_returns_404(client: AsyncClient) -> None:
    # 第二次以 user-2 身份访问 user-1 的会话 → 404
    first = await client.post(
        "/tools/t-fake/steps/s1/run",
        data={"params": "{}"},
        files={"doc": ("a.docx", b"x", "application/octet-stream")},
    )
    eid = first.json()["data"]["execution_id"]

    async def fake_user2() -> SimpleNamespace:
        return SimpleNamespace(id="user-2")

    client.app.dependency_overrides[api.get_current_user] = fake_user2  # type: ignore[attr-defined]
    resp = await client.get(f"/executions/{eid}")
    assert resp.status_code == 404


async def test_unauthenticated_gets_401(client: AsyncClient) -> None:
    # 建立执行会话后，无用户身份访问会话与文件 → 401
    first = await client.post(
        "/tools/t-fake/steps/s1/run",
        data={"params": "{}"},
        files={"doc": ("a.docx", b"x", "application/octet-stream")},
    )
    eid = first.json()["data"]["execution_id"]

    async def no_user() -> None:
        return None

    client.app.dependency_overrides[api.get_current_user] = no_user  # type: ignore[attr-defined]
    resp = await client.get(f"/executions/{eid}")
    assert resp.status_code == 401
    resp2 = await client.get(f"/executions/{eid}/files/x")
    assert resp2.status_code == 401


async def test_run_upload_over_size_limit_rejected(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api, "MAX_UPLOAD_BYTES", 10)
    resp = await client.post(
        "/tools/t-fake/steps/s1/run",
        data={"params": "{}"},
        files={"doc": ("a.docx", b"x" * 11, "application/octet-stream")},
    )
    assert resp.status_code == 400


async def test_run_params_not_json_object_rejected(client: AsyncClient) -> None:
    resp = await client.post(
        "/tools/t-fake/steps/s1/run",
        data={"params": "[1,2]"},
    )
    assert resp.status_code == 400
    assert "JSON" in resp.json()["message"]


async def test_run_multiple_files_registers_all(
    client: AsyncClient, fake_redis: FakeRedis
) -> None:
    resp = await client.post(
        "/tools/t-fake-multi/steps/m1/run",
        data={"params": "{}"},
        files=[
            ("docs", ("a.docx", b"aaa", "application/octet-stream")),
            ("docs", ("b.docx", b"bbbb", "application/octet-stream")),
        ],
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert len(data["file_ids"]["docs"]) == 2
    assert data["data"]["n"] == 2
    # 两个文件都落盘且登记到会话
    for fid in data["file_ids"]["docs"]:
        assert storage.resolve_file(data["execution_id"], fid) is not None
    exec_data = json.loads(fake_redis.store[_key(data["execution_id"])])
    assert len(exec_data["files"]) == 2


async def test_run_execution_id_tool_mismatch_400(client: AsyncClient) -> None:
    first = await client.post(
        "/tools/t-fake/steps/s1/run",
        data={"params": "{}"},
        files={"doc": ("a.docx", b"x", "application/octet-stream")},
    )
    eid = first.json()["data"]["execution_id"]
    second = await client.post(
        "/tools/t-fake-multi/steps/m1/run",
        data={"execution_id": eid, "params": "{}"},
    )
    assert second.status_code == 400
    assert "其他工具" in second.json()["message"]


async def test_list_tools_unauthenticated_401(client: AsyncClient) -> None:
    """未登录访问工具列表 → 401（spec 3.3：工具箱端点需要登录态）。"""

    async def fake_anon() -> None:
        return None

    client.app.dependency_overrides[api.get_current_user] = fake_anon  # type: ignore[attr-defined]
    resp = await client.get("/tools")
    assert resp.status_code == 401
