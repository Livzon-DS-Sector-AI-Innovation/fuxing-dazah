"""run_module_lifecycles 框架契约测试：阶段顺序、长循环收尾、stop 隔离。

框架是全部模块后台服务的宿主，顺序语义（register 全部完成才 start、
stop 逆序、引擎最后启停）回归破坏时很难从业务症状定位，在此钉死。
"""

from __future__ import annotations

import asyncio

from app.platform.module_lifecycle import (
    ModuleExtension,
    ModuleHost,
    run_module_lifecycles,
)
from app.platform.scheduler import ScheduleConfig, TaskDefinition


class _RecordingExtension(ModuleExtension):
    """把生命周期调用记录到共享事件列表的假扩展。"""

    def __init__(self, code: str, events: list[str]) -> None:
        self.code = code
        self._events = events

    def register(self, host: ModuleHost) -> None:
        self._events.append(f"register:{self.code}")

    def start(self, host: ModuleHost) -> None:
        self._events.append(f"start:{self.code}")

    async def stop(self) -> None:
        self._events.append(f"stop:{self.code}")


async def test_phase_order_register_all_then_start_then_stop_reversed() -> None:
    """register 全部完成才进入 start；关闭按扩展逆序 stop。"""
    events: list[str] = []
    extensions = (
        _RecordingExtension("platform", events),
        _RecordingExtension("equipment", events),
        _RecordingExtension("hr", events),
    )

    async with run_module_lifecycles(extensions):
        events.append("running")

    assert events == [
        "register:platform",
        "register:equipment",
        "register:hr",
        "start:platform",
        "start:equipment",
        "start:hr",
        "running",
        "stop:hr",
        "stop:equipment",
        "stop:platform",
    ]


async def test_background_loop_started_and_cancelled_on_exit() -> None:
    """add_background_loop 声明的长循环随上下文启动，退出时被取消收尾。"""

    async def _loop() -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            events.append("loop:cancelled")
            raise

    events: list[str] = []

    class _LoopExtension(ModuleExtension):
        code = "loop-mod"

        def register(self, host: ModuleHost) -> None:
            host.add_background_loop("test:loop", _loop)

    async with run_module_lifecycles((_LoopExtension(),)):
        await asyncio.sleep(0)  # 让出控制权，长循环得以真正启动

    assert events == ["loop:cancelled"]


async def test_scheduler_registry_visible_to_extensions() -> None:
    """扩展经 host.scheduler 注册的任务进入统一调度引擎注册表。"""

    async def _coro() -> None:  # pragma: no cover - 不会真正执行
        return None

    task = TaskDefinition(
        name="platform.test_task",
        schedule=ScheduleConfig(),
        coro=_coro,
        module="platform",
    )

    class _TaskExtension(ModuleExtension):
        code = "task-mod"

        def register(self, host: ModuleHost) -> None:
            host.scheduler.register_task(task)

    async with run_module_lifecycles((_TaskExtension(),)) as host:
        # register 阶段先于引擎启动，yield 时任务已入册。
        assert "platform.test_task" in host.scheduler.tasks


async def test_stop_failure_does_not_block_other_extensions() -> None:
    """单个扩展 stop 抛异常不阻断其余扩展与整体收尾。"""
    events: list[str] = []

    class _BoomExtension(ModuleExtension):
        code = "boom"

        async def stop(self) -> None:
            raise RuntimeError("stop failed")

    class _OkExtension(ModuleExtension):
        code = "ok"

        async def stop(self) -> None:
            events.append("stop:ok")

    async with run_module_lifecycles((_BoomExtension(), _OkExtension())):
        pass

    assert events == ["stop:ok"]
