"""质量飞书 WS 生命周期聚合：start/stop 各一行，main.py 不再散落 task 管理。

事件处理器注册（fill_service 导入副作用）与断线自愈逻辑均收敛在此处；
main.py 仅调用 start_ws_task() / await stop_ws_task()。
"""

import asyncio

_ws_task: asyncio.Task[None] | None = None


def start_ws_task() -> None:
    """启动质量飞书事件监听（后台任务，含事件处理器注册）。"""
    global _ws_task
    from app.modules.quality.feishu import (
        event_client,
        fill_service,  # noqa: F401 注册事件处理器
    )

    _ws_task = asyncio.create_task(event_client.start_ws())


async def stop_ws_task() -> None:
    """停止质量飞书事件监听。"""
    global _ws_task
    from app.modules.quality.feishu import event_client

    await event_client.stop_ws()
    if _ws_task:
        _ws_task.cancel()
