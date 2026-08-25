"""工具箱执行会话：Redis 存储，24h TTL，无数据库表。

key: toolbox:exec:{execution_id}
value: {"execution_id", "tool_id", "user_id", "outputs": {step_id: output}, "files": {file_id: meta}, "created_at"}

会话 payload 在调用方内存与 Redis 间传递：写函数直接接收 payload 并落库，
调用方按需在写后 flush 一次，避免每步多次 GET+SET。
"""

import json
import time
import uuid
from typing import Any

import redis.asyncio as redis

EXEC_TTL = 24 * 3600
KEY_PREFIX = "toolbox:exec:"


def _key(execution_id: str) -> str:
    return f"{KEY_PREFIX}{execution_id}"


def new_execution(tool_id: str, user_id: str) -> dict[str, Any]:
    """构造新会话 payload（不落库），由调用方持有并 set。"""
    return {
        "execution_id": uuid.uuid4().hex,
        "tool_id": tool_id,
        "user_id": user_id,
        "outputs": {},
        "files": {},
        "created_at": time.time(),
    }


async def save_execution(r: redis.Redis, exec_data: dict[str, Any]) -> None:
    await r.set(
        _key(exec_data["execution_id"]),
        json.dumps(exec_data, ensure_ascii=False),
        ex=EXEC_TTL,
    )


async def get_execution(r: redis.Redis, execution_id: str) -> dict[str, Any] | None:
    raw = await r.get(_key(execution_id))
    if raw is None:
        return None
    exec_data: dict[str, Any] = json.loads(raw)
    return exec_data


def add_step_output(exec_data: dict[str, Any], step_id: str, output: dict[str, Any]) -> None:
    exec_data["outputs"][step_id] = output


def add_files(
    exec_data: dict[str, Any],
    entries: list[tuple[str, str, str]],  # (input_key, file_id, filename)
) -> None:
    for input_key, file_id, filename in entries:
        exec_data["files"][file_id] = {"input_key": input_key, "filename": filename}
