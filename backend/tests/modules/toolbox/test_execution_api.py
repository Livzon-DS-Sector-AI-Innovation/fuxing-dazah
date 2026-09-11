"""工具箱执行端点集成测试（假工具 + FakeRedis 见 conftest）。"""

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.toolbox import api, storage
from app.modules.toolbox.registry import (
    StepContext,
    ToolError,
    ToolInput,
    ToolStep,
    tool,
)
from app.modules.toolbox.sessions import _key
from tests.modules.toolbox.conftest import FakeRedis


@pytest.fixture
def client(
    fake_redis: FakeRedis,
    fake_user: SimpleNamespace,
    db_session: AsyncSession,
) -> AsyncClient:
    """测试应用：挂 toolbox router，注入 FakeRedis、假用户与回滚测试会话。"""
    from fastapi import FastAPI

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


def _register_background_tools() -> None:
    """后台执行工具：成功版（上报进度后延迟返回）与失败版（ToolError）。"""

    @tool(
        id="t-bg",
        name="后台工具",
        description="后台执行测试",
        background=True,
        steps=[ToolStep(id="b1", name="执行", description="", inputs=[])],
    )
    async def _func(
        step_id: str, params: dict[str, Any], context: StepContext
    ) -> dict[str, Any]:
        if context.report_progress:
            context.report_progress(30, "进行中")
        await asyncio.sleep(0.05)
        return {"ok": True}

    @tool(
        id="t-bg-fail",
        name="后台失败工具",
        description="后台执行失败测试",
        background=True,
        steps=[ToolStep(id="b1", name="执行", description="", inputs=[])],
    )
    async def _fail_func(
        step_id: str, params: dict[str, Any], context: StepContext
    ) -> dict[str, Any]:
        raise ToolError("后台预期内失败")


_register_background_tools()


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
    client: AsyncClient, fake_redis: FakeRedis, fake_user: SimpleNamespace
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
    assert exec_data["user_id"] == str(fake_user.id)
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

    client.app.dependency_overrides[api.get_current_user] = fake_anon
    resp = await client.get("/tools")
    assert resp.status_code == 401


async def _wait_step_done(fake_redis: FakeRedis, execution_id: str, step_id: str) -> dict[str, Any]:
    """轮询 FakeRedis 直到后台任务写入 outputs（或超时失败）。"""
    for _ in range(200):
        raw = fake_redis.store.get(_key(execution_id))
        if raw:
            data = json.loads(raw)
            if data.get("progress", {}).get(step_id, {}).get("status") in ("done", "failed"):
                return data
        await asyncio.sleep(0.01)
    raise AssertionError("后台任务未在预期时间内完成")


async def test_background_tool_returns_running_then_completes(
    client: AsyncClient, fake_redis: FakeRedis
) -> None:
    """background 工具：run 立即返回 running + 会话落库；完成后 outputs 与进度落库。"""
    resp = await client.post("/tools/t-bg/steps/b1/run", data={"params": "{}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["status"] == "running"
    assert body["data"] == {}
    execution_id = body["execution_id"]

    exec_data = await _wait_step_done(fake_redis, execution_id, "b1")
    assert exec_data["outputs"]["b1"] == {"ok": True}
    progress = exec_data["progress"]["b1"]
    assert progress["status"] == "done"
    assert progress["percent"] == 100
    # 会话端点透出进度与结果（前端轮询依据）
    state = await client.get(f"/executions/{execution_id}")
    assert state.status_code == 200
    payload = state.json()["data"]
    assert payload["progress"]["b1"]["status"] == "done"
    assert payload["outputs"]["b1"]["ok"] is True


async def test_background_tool_reports_progress_updates(
    client: AsyncClient, fake_redis: FakeRedis
) -> None:
    """工具内 report_progress 调用写入会话进度（run_coroutine_threadsafe 链路）。"""
    resp = await client.post("/tools/t-bg/steps/b1/run", data={"params": "{}"})
    execution_id = resp.json()["data"]["execution_id"]

    seen: list[int] = []
    for _ in range(200):
        raw = fake_redis.store.get(_key(execution_id))
        if raw:
            progress = json.loads(raw).get("progress", {}).get("b1", {})
            seen.append(progress.get("percent", 0))
            if progress.get("status") in ("done", "failed"):
                break
        await asyncio.sleep(0.01)
    # 至少观察到一次中间进度（30%），终态 100
    assert 30 in seen
    assert seen[-1] == 100


async def test_background_tool_failure_marks_progress_failed(
    client: AsyncClient, fake_redis: FakeRedis
) -> None:
    """后台 ToolError → 进度 failed + error 消息，outputs 不写入。"""
    resp = await client.post("/tools/t-bg-fail/steps/b1/run", data={"params": "{}"})
    execution_id = resp.json()["data"]["execution_id"]

    exec_data = await _wait_step_done(fake_redis, execution_id, "b1")
    progress = exec_data["progress"]["b1"]
    assert progress["status"] == "failed"
    assert progress["error"] == "后台预期内失败"
    assert "b1" not in exec_data["outputs"]


async def test_background_tool_rejects_duplicate_running_step(client: AsyncClient) -> None:
    """同一步骤执行中重复提交 → 400（会话 progress 仍为 running 时拦截）。"""
    first = await client.post("/tools/t-bg/steps/b1/run", data={"params": "{}"})
    assert first.status_code == 200
    execution_id = first.json()["data"]["execution_id"]

    # 后台任务约 0.05s：立刻重复提交应被 400 拦截
    second = await client.post(
        "/tools/t-bg/steps/b1/run",
        data={"execution_id": execution_id, "params": "{}"},
    )
    assert second.status_code == 400
    assert "正在执行中" in second.json()["message"]


async def test_list_executions_empty(client: AsyncClient) -> None:
    resp = await client.get("/executions")
    assert resp.status_code == 200
    assert resp.json()["data"] == []


async def test_list_executions_tracks_background_lifecycle(
    client: AsyncClient, fake_redis: FakeRedis
) -> None:
    """background 执行登记进用户历史：running → done 状态随任务流转。"""
    resp = await client.post("/tools/t-bg/steps/b1/run", data={"params": "{}"})
    eid = resp.json()["data"]["execution_id"]

    items = (await client.get("/executions")).json()["data"]
    assert len(items) == 1
    assert items[0]["execution_id"] == eid
    assert items[0]["tool_id"] == "t-bg"
    assert items[0]["status"] == "running"
    assert items[0]["percent"] == 0

    await _wait_step_done(fake_redis, eid, "b1")
    items = (await client.get("/executions")).json()["data"]
    assert items[0]["status"] == "done"
    assert items[0]["percent"] == 100


async def test_list_executions_only_own(client: AsyncClient) -> None:
    """执行历史按用户隔离：他人看不到我的会话。"""
    resp = await client.post("/tools/t-bg/steps/b1/run", data={"params": "{}"})
    assert resp.status_code == 200

    async def fake_user2() -> SimpleNamespace:
        return SimpleNamespace(id="user-2")

    client.app.dependency_overrides[api.get_current_user] = fake_user2
    items = (await client.get("/executions")).json()["data"]
    assert items == []


async def test_list_executions_unauthenticated_401(client: AsyncClient) -> None:
    async def fake_anon() -> None:
        return None

    client.app.dependency_overrides[api.get_current_user] = fake_anon
    resp = await client.get("/executions")
    assert resp.status_code == 401
