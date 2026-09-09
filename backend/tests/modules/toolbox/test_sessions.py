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


async def test_claim_step_running_merges_latest_payload(fake_redis: redis.Redis) -> None:
    """claim 基于最新 payload 合并：不覆盖并发步骤已写入的产出。"""
    exec_data = sessions.new_execution("t1", "user-1")
    await sessions.save_execution(fake_redis, exec_data)
    # 模拟并发步骤在 claim 前写入产出（调用方持有的 exec_data 是旧快照，没有该产出）
    latest = await sessions.get_execution(fake_redis, exec_data["execution_id"])
    sessions.add_step_output(latest, "other_step", {"text": "并发产出"})
    await sessions.save_execution(fake_redis, latest)

    ok = await sessions.claim_step_running(
        fake_redis, exec_data, "s1", [("files", "f-1", "a.docx")],
    )
    assert ok
    loaded = await sessions.get_execution(fake_redis, exec_data["execution_id"])
    assert loaded is not None
    assert loaded["outputs"]["other_step"] == {"text": "并发产出"}
    assert loaded["progress"]["s1"]["status"] == "running"
    assert loaded["files"]["f-1"]["filename"] == "a.docx"


async def test_claim_step_running_rejects_live_duplicate(fake_redis: redis.Redis) -> None:
    """本进程 running 步骤拒绝重复 claim；旧进程（重启前）的 running 允许覆盖。"""
    exec_data = sessions.new_execution("t1", "user-1")
    assert await sessions.claim_step_running(fake_redis, exec_data, "s1", [])
    assert not await sessions.claim_step_running(fake_redis, exec_data, "s1", [])
    # 模拟重启遗留：updated_at 早于 PROCESS_START
    exec_data["progress"]["s1"]["updated_at"] = sessions.PROCESS_START - 1
    await sessions.save_execution(fake_redis, exec_data)
    assert await sessions.claim_step_running(fake_redis, exec_data, "s1", [])


async def test_reap_orphaned_running(fake_redis: redis.Redis) -> None:
    exec_data = sessions.new_execution("t1", "user-1")
    sessions.set_progress(exec_data, "s1", percent=42, message="翻译中")
    exec_data["progress"]["s1"]["updated_at"] = sessions.PROCESS_START - 1  # 旧进程写入
    sessions.set_progress(exec_data, "s2", percent=10, message="进行中")  # 本进程写入
    assert sessions.reap_orphaned_running(exec_data)
    assert exec_data["progress"]["s1"]["status"] == "failed"
    assert exec_data["progress"]["s2"]["status"] == "running"
    assert not sessions.reap_orphaned_running(exec_data)


async def test_clear_step_running_rollback(fake_redis: redis.Redis) -> None:
    exec_data = sessions.new_execution("t1", "user-1")
    assert await sessions.claim_step_running(fake_redis, exec_data, "s1", [])
    await sessions.clear_step_running(fake_redis, exec_data["execution_id"], "s1")
    loaded = await sessions.get_execution(fake_redis, exec_data["execution_id"])
    assert loaded is not None
    assert "s1" not in loaded["progress"]
