"""工具箱 Redis 会话测试（FakeRedis 见 conftest，不依赖真实 Redis）。"""

import json
from typing import cast

import redis.asyncio as redis

from app.modules.toolbox import sessions
from app.modules.toolbox.sessions import EXEC_TTL
from tests.modules.toolbox.conftest import FakeRedis


async def test_new_and_save_execution(fake_redis: redis.Redis) -> None:
    exec_data = sessions.new_execution("t1", "user-1")
    await sessions.save_execution(fake_redis, exec_data)
    loaded = await sessions.get_execution(fake_redis, exec_data["execution_id"])
    assert loaded is not None
    assert loaded["tool_id"] == "t1"
    assert loaded["user_id"] == "user-1"
    assert loaded["outputs"] == {}
    assert cast(FakeRedis, fake_redis).ttls[sessions._key(exec_data["execution_id"])] == EXEC_TTL


async def test_add_step_output_persists(fake_redis: redis.Redis) -> None:
    exec_data = sessions.new_execution("t1", "user-1")
    sessions.add_step_output(exec_data, "s1", {"text": "结果"})
    await sessions.save_execution(fake_redis, exec_data)
    loaded = await sessions.get_execution(fake_redis, exec_data["execution_id"])
    assert loaded is not None
    assert loaded["outputs"]["s1"] == {"text": "结果"}


async def test_add_files_persists(fake_redis: redis.Redis) -> None:
    exec_data = sessions.new_execution("t1", "user-1")
    sessions.add_files(exec_data, [("files", "f-1", "a.docx"), ("files", "f-2", "b.docx")])
    await sessions.save_execution(fake_redis, exec_data)
    loaded = await sessions.get_execution(fake_redis, exec_data["execution_id"])
    assert loaded is not None
    assert loaded["files"]["f-1"] == {"input_key": "files", "filename": "a.docx"}
    assert loaded["files"]["f-2"] == {"input_key": "files", "filename": "b.docx"}


async def test_get_missing_execution_returns_none(fake_redis: redis.Redis) -> None:
    assert await sessions.get_execution(fake_redis, "nope") is None


async def test_payload_is_json_serializable(fake_redis: redis.Redis) -> None:
    exec_data = sessions.new_execution("t1", "user-1")
    sessions.add_step_output(exec_data, "s1", {"rows": [["a", "b"]], "n": 1})
    await sessions.save_execution(fake_redis, exec_data)
    raw = cast(FakeRedis, fake_redis).store[sessions._key(exec_data["execution_id"])]
    json.loads(raw)  # 不抛异常即通过
