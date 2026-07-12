"""后台任务 DB 工具 — 在独立线程事件循环中运行为步 DB 操作。

用于 WebSocket / 后台任务等不在 FastAPI 请求生命周期内的场景，
绕开 ProactorEventLoop 下的 greenlet 上下文冲突。
"""

import asyncio
import threading
from collections.abc import Awaitable, Callable
from typing import Any


async def run_db[T](fn: Callable[[], Awaitable[T]]) -> T:
    """在独立线程的新事件循环中运行 async DB 操作。

    Args:
        fn: 返回 awaitable 的无参工厂函数，例:
            lambda: _do_some_db_work(arg1, arg2)

    Returns:
        异步函数的返回值
    """
    result_holder: list[T] = []
    error_holder: list[Exception] = []

    def _runner() -> None:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            coro = fn()
            result_holder.append(loop.run_until_complete(coro))
        except Exception as exc:
            error_holder.append(exc)
        finally:
            loop.close()

    thread = threading.Thread(target=_runner)
    thread.start()
    thread.join()

    if error_holder:
        raise error_holder[0]
    return result_holder[0]


# 预绑定 async_session_factory，减少样板代码
async def run_db_session[T](
    fn: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any
) -> T:
    """run_db 的快捷版 — 自动传入 async_session_factory。

    回调签名为 async def fn(db: AsyncSession, **extra) -> T:
    """
    from app.core.database import async_session_factory

    async def _inner() -> T:
        async with async_session_factory() as session:
            return await fn(session, *args, **kwargs)

    return await run_db(_inner)
