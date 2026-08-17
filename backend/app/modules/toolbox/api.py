"""工具箱 HTTP 端点：工具列表、分步执行、会话查询、文件下载。

执行编排约定：
- 全部步骤统一 multipart：字段 execution_id(可选) / params(JSON 字符串) / 文件字段名=input key。
- 首次执行（无 execution_id）创建会话；文件落临时目录并登记到会话。
- params 中 file 型参数可传 {"file_ids": [...]} 引用本会话已上传文件，后端解析为本地路径列表。
- file_paths 与 file_ids 恒为 list[str]（单文件也是单元素列表）。
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from redis.asyncio import Redis
from starlette.datastructures import UploadFile

from app.core.redis import get_redis
from app.core.response import error_response, success_response
from app.modules.toolbox import sessions, storage
from app.modules.toolbox.registry import (
    TOOL_IMAGE_URL_PREFIX,
    StepContext,
    Tool,
    ToolError,
    discover_tools,
    get_step,
    get_tool,
    list_tools,
)
from app.modules.toolbox.schemas import ExecutionOut, StepRunResponse, ToolOut
from app.platform.identity.deps import get_current_user
from app.platform.identity.models import User

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100MB

_cleanup_tasks: set[asyncio.Task[None]] = set()


def _spawn_cleanup() -> None:
    """后台触发临时目录清理（节流在 storage 内部），不阻塞当前请求。"""
    task = asyncio.create_task(storage.maybe_cleanup())
    _cleanup_tasks.add(task)
    task.add_done_callback(_cleanup_tasks.discard)


def _tool_to_out(t: Tool) -> dict[str, Any]:
    d = ToolOut.model_validate(t).model_dump(mode="json")
    if t.image:
        d["image"] = f"{TOOL_IMAGE_URL_PREFIX}/{t.image}"
    return d


@router.get("/tools", summary="工具列表")
async def list_tool_endpoints(
    user: User | None = Depends(get_current_user),
) -> JSONResponse:
    """工具箱全部工具元数据（驱动首页卡片与执行页动态表单）。"""
    if user is None:
        return error_response("未登录", status_code=401)
    discover_tools()
    return success_response(data=[_tool_to_out(t) for t in list_tools()])


@router.post("/tools/{tool_id}/steps/{step_id}/run", summary="执行工具步骤")
async def run_step(
    tool_id: str,
    step_id: str,
    request: Request,
    user: User | None = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
) -> JSONResponse:
    """执行某工具某步骤（同步）。multipart：execution_id + params(JSON) + 文件。"""
    if user is None:
        return error_response("未登录", status_code=401)
    # 首次请求可能直接执行步骤（不经过 GET /tools），此处确保工具已发现
    discover_tools()
    tool = get_tool(tool_id)
    step = get_step(tool_id, step_id)
    if tool is None:
        return error_response(f"工具不存在: {tool_id}", status_code=404)
    if step is None:
        return error_response(f"步骤不存在: {step_id}", status_code=404)

    form = await request.form()
    execution_id_raw = form.get("execution_id")
    execution_id = str(execution_id_raw) if execution_id_raw else None

    try:
        params_dict: dict[str, Any] = json.loads(str(form.get("params") or "{}"))
    except json.JSONDecodeError:
        return error_response("params 不是合法 JSON", status_code=400)
    if not isinstance(params_dict, dict):
        return error_response("params 需为 JSON 对象", status_code=400)

    # ── 会话：无则构造（校验通过前不落库，避免校验失败留下孤儿会话），有则校验归属 ──
    is_new = False
    if execution_id:
        exec_data = await sessions.get_execution(redis, execution_id)
        if exec_data is None or exec_data["user_id"] != str(user.id):
            return error_response("执行会话不存在", status_code=404)
        if exec_data["tool_id"] != tool_id:
            return error_response("该执行会话属于其他工具", status_code=400)
        storage.touch_exec_dir(execution_id)
    else:
        exec_data = sessions.new_execution(tool_id, str(user.id))
        execution_id = exec_data["execution_id"]
        is_new = True

    _spawn_cleanup()

    def uploads_for(key: str) -> list[UploadFile]:
        return [v for v in form.getlist(key) if isinstance(v, UploadFile)]

    # ── 第一遍：只校验文件输入（必填、扩展名、引用、数量），不读文件内容 ──
    for inp in step.inputs:
        if inp.type != "file":
            continue
        ref = params_dict.get(inp.key)
        if isinstance(ref, dict) and ref.get("file_ids"):
            for fid in ref["file_ids"]:
                if storage.resolve_file(execution_id, str(fid)) is None:
                    return error_response(f"引用的文件不存在: {inp.label}", status_code=400)
            continue
        up_list = uploads_for(inp.key)
        if not up_list:
            if inp.required:
                return error_response(f"缺少必填文件: {inp.label}", status_code=400)
            continue
        if not inp.multiple and len(up_list) > 1:
            return error_response(f"{inp.label} 只允许上传一个文件", status_code=400)
        if inp.accept:
            allowed = {ext.strip().lower() for ext in inp.accept.split(",")}
            for up in up_list:
                suffix = Path(up.filename or "").suffix.lower()
                if allowed and suffix not in allowed:
                    return error_response(
                        f"文件类型不符: {inp.label} 只接受 {', '.join(sorted(allowed))}", status_code=400
                    )

    # ── 第二遍：读取并落盘（写盘放线程池，避免阻塞事件循环）──
    file_paths: dict[str, list[str]] = {}
    file_ids: dict[str, list[str]] = {}
    registered: list[tuple[str, str, str]] = []  # (input_key, file_id, filename)

    for inp in step.inputs:
        if inp.type != "file":
            continue
        ref = params_dict.get(inp.key)
        if isinstance(ref, dict) and ref.get("file_ids"):
            # 引用本会话已上传文件（{"file_ids": [...]}）
            paths: list[str] = []
            for fid in ref["file_ids"]:
                p = storage.resolve_file(execution_id, str(fid))
                if p is None:
                    return error_response(f"引用的文件不存在: {inp.key}", status_code=400)
                paths.append(str(p))
            file_paths[inp.key] = paths
            continue
        up_list = uploads_for(inp.key)
        if not up_list:
            continue
        saved_paths: list[str] = []
        saved_ids: list[str] = []
        for up in up_list:
            data = await up.read(MAX_UPLOAD_BYTES + 1)
            if len(data) > MAX_UPLOAD_BYTES:
                return error_response("文件超过 100MB 上限", status_code=400)
            fid, path = await asyncio.to_thread(
                storage.save_upload, execution_id, up.filename or "upload.bin", data
            )
            registered.append((inp.key, fid, up.filename or ""))
            saved_paths.append(str(path))
            saved_ids.append(fid)
        file_paths[inp.key] = saved_paths
        file_ids[inp.key] = saved_ids

    # 已有会话的文件登记先落库：工具执行耗时长，失败后客户端仍可引用已上传文件。
    # 新会话推迟到执行成功后一次性落库（客户端失败时拿不到 execution_id，落库只会留孤儿）。
    if registered and not is_new:
        sessions.add_files(exec_data, registered)
        await sessions.save_execution(redis, exec_data)

    # ── 执行 ──
    # prev_outputs 传 JSON 深拷贝：工具可能把引用存进返回结果，若直接引用
    # exec_data["outputs"] 会在会话落库序列化时形成循环引用
    context = StepContext(
        execution_id=execution_id,
        user_id=str(user.id),
        prev_outputs=json.loads(json.dumps(exec_data["outputs"])),
        file_paths=file_paths,
        output_dir=storage.exec_dir(execution_id),
    )
    try:
        result = await tool.func(step_id, params_dict, context)
    except ToolError as e:
        return error_response(str(e), status_code=400)
    except Exception as e:
        # 内部系统：异常消息直接反馈给用户，堆栈仅进日志
        logger.exception("toolbox 工具执行失败 tool=%s step=%s", tool_id, step_id)
        return error_response(f"工具执行失败: {e}", status_code=500)

    sessions.add_files(exec_data, registered)
    sessions.add_step_output(exec_data, step_id, result)
    # 合并保存：重新拉取最新 payload 再合并写入，避免并发步骤盲写互相覆盖
    latest = await sessions.get_execution(redis, execution_id)
    if latest is not None:
        latest["files"].update(exec_data["files"])
        latest["outputs"].update(exec_data["outputs"])
        exec_data = latest
    await sessions.save_execution(redis, exec_data)
    response = StepRunResponse(execution_id=execution_id, data=result, file_ids=file_ids)
    return success_response(data=response.model_dump(mode="json"))


@router.get("/executions/{execution_id}", summary="执行会话状态")
async def get_execution_state(
    execution_id: str,
    user: User | None = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
) -> JSONResponse:
    if user is None:
        return error_response("未登录", status_code=401)
    exec_data = await sessions.get_execution(redis, execution_id)
    if exec_data is None or exec_data["user_id"] != str(user.id):
        return error_response("执行会话不存在", status_code=404)
    return success_response(data=ExecutionOut(**exec_data).model_dump(mode="json"))


@router.get("/executions/{execution_id}/files/{file_id}", summary="下载执行产物")
async def download_file(
    execution_id: str,
    file_id: str,
    user: User | None = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
) -> Response:
    if user is None:
        return error_response("未登录", status_code=401)
    exec_data = await sessions.get_execution(redis, execution_id)
    if exec_data is None or exec_data["user_id"] != str(user.id):
        return error_response("执行会话不存在", status_code=404)
    p = storage.resolve_file(execution_id, file_id)
    if p is None:
        return error_response("文件不存在", status_code=404)
    meta = exec_data.get("files", {}).get(file_id, {})
    filename = meta.get("filename") or p.name
    return FileResponse(p, filename=filename)
