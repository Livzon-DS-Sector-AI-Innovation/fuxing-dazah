"""飞书 WebSocket 长连接客户端。

通过 lark-oapi SDK 的 ws.Client 建立长连接，接收飞书事件推送。
注意：lark_oapi SDK 的 ws.Client 使用模块级全局 loop 变量（ws/client.py 中
start()/_connect() 等全部裸名解析），多线程并发实例会互相覆盖 loop 导致
RuntimeError: This event loop is already running。因此本模块坚持单实例原则：
同一时刻只允许一个 SDK WS 客户端运行，后续启动请求直接跳过。
"""

import asyncio
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

_ws_threads: dict[str, threading.Thread] = {}
_stop_flags: dict[str, threading.Event] = {}

# SDK 模块级 loop 全局变量互斥（单实例原则，见模块 docstring）
_sdk_guard = threading.Lock()
_sdk_active = False


def _try_acquire_sdk() -> bool:
    """尝试取得 lark_oapi SDK 客户端独占权（已有实例运行则返回 False）。"""
    global _sdk_active
    with _sdk_guard:
        if _sdk_active:
            return False
        _sdk_active = True
        return True


def _release_sdk() -> None:
    global _sdk_active
    with _sdk_guard:
        _sdk_active = False


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
    """在独立线程中创建 event loop 并运行 WS client。

    单实例原则：SDK 模块级 loop 全局变量不支持并发实例，
    已有客户端运行时本线程直接退出。
    """
    if not _try_acquire_sdk():
        logger.warning(
            "[%s] 已有飞书 WS 客户端在运行（SDK 模块级 loop 全局变量不支持多实例并发），跳过启动",
            name,
        )
        return

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
        _release_sdk()
