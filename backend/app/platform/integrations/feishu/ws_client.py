"""飞书 WebSocket 长连接客户端。

通过 lark-oapi SDK 的 ws.Client 建立长连接，接收飞书事件推送。
支持多实例运行：每个实例在独立线程 + 独立 event loop 中运行。
"""

import asyncio
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

_ws_threads: dict[str, threading.Thread] = {}
_stop_flags: dict[str, threading.Event] = {}


def start_ws_client(
    app_id: str | None = None,
    app_secret: str | None = None,
    event_handler: Any = None,
    name: str = "feishu-ws",
) -> None:
    """启动飞书 WebSocket 长连接（非阻塞，在后台线程运行）。

    Args:
        app_id: 飞书应用 ID，默认使用全局 FEISHU_APP_ID
        app_secret: 飞书应用密钥，默认使用全局 FEISHU_APP_SECRET
        event_handler: 事件处理器，默认使用全局 build_event_handler()
        name: 线程名称，用于区分多个 WS 实例
    """
    from app.core.config import get_settings

    settings = get_settings()
    resolved_app_id = app_id or settings.FEISHU_APP_ID
    resolved_app_secret = app_secret or settings.FEISHU_APP_SECRET

    if not resolved_app_id or not resolved_app_secret:
        logger.warning(
            "[%s] 飞书 APP_ID/APP_SECRET 未配置，跳过长连接启动", name,
        )
        return

    stop_flag = threading.Event()
    _stop_flags[name] = stop_flag

    thread = threading.Thread(
        target=_run_ws_in_thread,
        args=(resolved_app_id, resolved_app_secret, event_handler, name, stop_flag),
        name=name,
        daemon=True,
    )
    _ws_threads[name] = thread
    thread.start()
    logger.info("[%s] 飞书 WebSocket 长连接线程已启动", name)


def stop_ws_client(name: str | None = None) -> None:
    """停止飞书 WebSocket 长连接。

    Args:
        name: 指定实例名称。为 None 时停止所有实例。
    """
    if name:
        flag = _stop_flags.pop(name, None)
        if flag:
            flag.set()
        _ws_threads.pop(name, None)
        logger.info("[%s] 飞书 WebSocket 长连接已请求停止", name)
    else:
        for n, flag in _stop_flags.items():
            flag.set()
            logger.info("[%s] 飞书 WebSocket 长连接已请求停止", n)
        _stop_flags.clear()
        _ws_threads.clear()


def _run_ws_in_thread(
    app_id: str,
    app_secret: str,
    event_handler: Any,
    name: str,
    stop_flag: threading.Event,
) -> None:
    """在独立线程中创建 event loop 并运行 WS client。"""
    import lark_oapi as lark
    import lark_oapi.ws as lark_ws

    if event_handler is None:
        from app.platform.integrations.feishu.event_handler import (
            build_event_handler,
        )

        event_handler = build_event_handler()

    # SDK 使用模块级 loop 变量，需替换为本线程的 loop
    thread_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(thread_loop)
    lark_ws.client.loop = thread_loop

    ws = lark_ws.Client(
        app_id=app_id,
        app_secret=app_secret,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
        auto_reconnect=True,
    )

    try:
        logger.info("[%s] 飞书 WebSocket 客户端正在连接...", name)
        ws.start()
    except Exception:
        logger.exception("[%s] 飞书 WebSocket 客户端异常退出", name)
    finally:
        thread_loop.close()
