"""模块生命周期契约：模块后台服务自注册，main 只按清单驱动阶段。

背景：此前 main.py 的 lifespan 逐个 import 各模块的任务对象、飞书回调与
WS 客户端并手工编排启停顺序，每加一个后台服务都要改全局代码，违背
"所有变动尽量收敛在模块内部"的仓库约定。本契约把组合方向反转：模块在
自己的 lifecycle.py 里实现 ModuleExtension，向 ModuleHost 声明服务；
main.py 只持有一份扩展实例清单。

阶段顺序（与旧 lifespan 语义保持一致）：
1. register —— 纯注册：定时任务/生成器入 SchedulerRegistry、飞书事件回调
   入注册表、长循环声明。不做 I/O，不启动任何东西。
2. start —— 模块自管资源启动（模块专属 WS 等）。此时全部模块的回调注册
   已完成，平台 WS 可安全启动。
3. 框架启动统一调度引擎（所有任务/生成器均已入册）。
关闭按逆序：各扩展 stop → 引擎停并等待收尾 → 长循环取消。
（飞书 WS 只收事件、发消息走 HTTP API，先停 WS 不影响引擎收尾期的外发。）

扩展清单放在 main.py 而非 shared/module_registry.py：后者被十余个模块的
api 层反向引用，顶部 import 各模块 lifecycle 会构成循环导入。
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC
from collections.abc import AsyncGenerator, Callable, Coroutine, Sequence
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import Any

from app.platform.scheduler import SchedulerEngine, SchedulerRegistry

logger = logging.getLogger(__name__)

# 长循环工厂：无参协程，循环自身负责退出语义（stop-flag / 周期扫描）。
# 注：须是 Coroutine 而非更宽的 Awaitable——asyncio.create_task 的签名
# 只接受协程（pyright 会拦）。
LoopFactory = Callable[[], Coroutine[Any, Any, None]]


@dataclass
class ModuleHost:
    """模块注册后台服务时可见的宿主能力视图。"""

    scheduler: SchedulerRegistry
    # 长循环声明（name, factory），框架统一启动、关闭时统一取消兜底。
    _loops: list[tuple[str, LoopFactory]] = field(
        default_factory=list,
        init=False,
        repr=False,
    )
    _loop_tasks: list[asyncio.Task[None]] = field(
        default_factory=list,
        init=False,
        repr=False,
    )

    def add_background_loop(self, name: str, factory: LoopFactory) -> None:
        """声明一个随进程生命周期的长循环。

        旧式 stop-flag 循环（模块内 asyncio.Event）无需改造：flag 由模块
        自己的 stop() 置位实现优雅退出，框架的取消只是兜底。
        """
        self._loops.append((name, factory))

    # ── 框架内部：阶段驱动 ──────────────────────────────────────

    def _start_loops(self) -> None:
        for name, factory in self._loops:
            # create_task 而非 ensure_future：只有前者支持 name 定位任务。
            self._loop_tasks.append(asyncio.create_task(factory(), name=name))

    async def _cancel_loops(self) -> None:
        for task in self._loop_tasks:
            task.cancel()
        for task in self._loop_tasks:
            # stop-flag 优雅退出为主，这里的异常（含取消）只做吞并收尾。
            with suppress(asyncio.CancelledError, Exception):
                await task


class ModuleExtension(ABC):
    """模块后台服务的生命周期入口，实例须无状态、进程内单例复用。"""

    #: 模块代码，用于日志定位（与 module_registry 的 code 对齐）。
    code: str = ""

    def register(self, host: ModuleHost) -> None:
        """纯注册阶段：定时任务/生成器、飞书事件回调、长循环声明。默认无操作。"""

    def start(self, host: ModuleHost) -> None:
        """模块自管资源启动（如模块专属 WS）。全部 register 已完成。默认无操作。"""

    async def stop(self) -> None:
        """进程关闭时的模块侧清理（置 stop-flag、停模块专属 WS）。默认无操作。"""


@asynccontextmanager
async def run_module_lifecycles(
    extensions: Sequence[ModuleExtension],
) -> AsyncGenerator[ModuleHost, None]:
    """按契约驱动全部扩展的启停（阶段顺序见模块文档字符串）。"""
    host = ModuleHost(scheduler=SchedulerRegistry())
    engine = SchedulerEngine(host.scheduler)
    engine_task: asyncio.Task[None] | None = None
    try:
        for ext in extensions:
            logger.debug("Registering module extension: %s", ext.code)
            ext.register(host)
        host._start_loops()
        for ext in extensions:
            logger.debug("Starting module extension: %s", ext.code)
            ext.start(host)
        engine_task = asyncio.create_task(engine.run(), name="scheduler-engine")
        logger.info("Background tasks started")
        yield host
    finally:
        # 单个模块的清理失败不阻断其余模块收尾。
        for ext in reversed(extensions):
            try:
                await ext.stop()
            except Exception:
                logger.exception("Extension '%s' stop failed", ext.code)
        engine.stop()
        if engine_task is not None:
            with suppress(TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(engine_task, timeout=10)
        await host._cancel_loops()
        logger.info("Background tasks stopped")
