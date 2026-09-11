"""工具箱执行会话：Redis 存储，24h TTL，无数据库表。

key: toolbox:exec:{execution_id}
value: {"execution_id", "tool_id", "user_id", "outputs": {step_id: output},
        "files": {file_id: meta}, "progress": {step_id: {...}}, "created_at"}

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
# 用户执行历史索引（set）：member 为 execution_id，供执行列表端点查询；
# 过期会话在读取时自动跳过，索引键 TTL 与会话一致并在每次登记时续期
USER_INDEX_PREFIX = "toolbox:user_execs:"

# 本进程启动时间：后台任务运行于进程内 asyncio task，不跨重启存活。
# updated_at 早于该时间点的 running 标记必然由已死进程写入（孤儿），
# 可安全判失败/允许重新占位。
PROCESS_START = time.time()


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
        "progress": {},
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


async def remember_execution(r: redis.Redis, user_id: str, execution_id: str) -> None:
    """把执行会话登记进用户执行历史索引（仅 background 工具调用）。"""
    key = f"{USER_INDEX_PREFIX}{user_id}"
    await r.sadd(key, execution_id)  # type: ignore[misc]  # redis 类型标注为 Awaitable | 值联合
    await r.expire(key, EXEC_TTL)


async def merge_add_files(
    r: redis.Redis,
    execution_id: str,
    entries: list[tuple[str, str, str]],  # (input_key, file_id, filename)
) -> None:
    """合并登记文件到最新 payload：基于旧快照盲写会抹掉并发步骤的产出。"""
    latest = await get_execution(r, execution_id)
    if latest is None:
        return
    add_files(latest, entries)
    await save_execution(r, latest)


async def claim_step_running(
    r: redis.Redis,
    exec_data: dict[str, Any],
    step_id: str,
    entries: list[tuple[str, str, str]],
) -> bool:
    """把步骤标记为 running 并合并登记文件，成功返回 True。

    原子性用步骤级 SET NX 锁串行化「检查→写入」窗口：并发重复提交
    只有一个能走到 payload 检查；锁在 claim 结束即释放，running 的
    持续防重仍由 payload 里的 progress.status=running 承担（读取时校验）。
    本进程启动前遗留的 running 视为孤儿（任务不跨进程存活），允许覆盖。
    会话 key 尚未落库（新会话首跑）时以传入的 exec_data 为基底。
    """
    execution_id = exec_data["execution_id"]
    lock_key = f"{_key(execution_id)}:claim:{step_id}"
    if await r.set(lock_key, "1", nx=True, ex=30) is None:
        return False
    try:
        latest = await get_execution(r, execution_id)
        base = latest if latest is not None else exec_data
        prev = base.get("progress", {}).get(step_id) or {}
        if prev.get("status") == "running" and float(prev.get("updated_at") or 0) >= PROCESS_START:
            return False
        add_files(base, entries)
        set_progress(base, step_id, percent=0, message="任务已启动")
        await save_execution(r, base)
        return True
    finally:
        await r.delete(lock_key)


async def clear_step_running(r: redis.Redis, execution_id: str, step_id: str) -> None:
    """撤销 running 标记（claim 成功后、任务启动前失败的回滚），避免会话假死。"""
    exec_data = await get_execution(r, execution_id)
    if exec_data is None:
        return
    if exec_data.get("progress", {}).get(step_id, {}).get("status") == "running":
        exec_data["progress"].pop(step_id, None)
        await save_execution(r, exec_data)


def reap_orphaned_running(exec_data: dict[str, Any]) -> bool:
    """标记本进程启动前遗留的 running 步骤为 failed，返回是否有变更。

    服务重启后旧进程的 asyncio 任务已死，会话却仍显示执行中；
    读取时惰性收割，用户看到失败原因并可重新提交。
    """
    changed = False
    for p in exec_data.get("progress", {}).values():
        if p.get("status") == "running" and float(p.get("updated_at") or 0) < PROCESS_START:
            p.update(
                {
                    "status": "failed",
                    "message": "任务中断",
                    "error": "服务重启导致任务中断，请重新执行",
                }
            )
            changed = True
    return changed


async def list_user_executions(r: redis.Redis, user_id: str) -> list[dict[str, Any]]:
    """取回用户全部现存会话 payload（已过期的自动跳过）；排序由调用方负责。"""
    ids = await r.smembers(f"{USER_INDEX_PREFIX}{user_id}")  # type: ignore[misc]  # 同上
    out: list[dict[str, Any]] = []
    for raw in ids:
        exec_id = raw.decode() if isinstance(raw, bytes) else str(raw)
        exec_data = await get_execution(r, exec_id)
        if exec_data is not None:
            out.append(exec_data)
    return out


def set_progress(
    exec_data: dict[str, Any],
    step_id: str,
    percent: int = 0,
    message: str = "",
    status: str = "running",
    error: str | None = None,
) -> None:
    """更新某步骤执行进度（background 工具专用，由调用方落库）。

    status: running=执行中 / done=完成（outputs 已写入）/ failed=失败（error 为原因）。
    """
    exec_data.setdefault("progress", {})[step_id] = {
        "percent": percent,
        "message": message,
        "status": status,
        "error": error,
        "updated_at": time.time(),
    }
