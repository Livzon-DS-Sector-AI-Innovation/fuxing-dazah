"""飞书 WebSocket 长连接客户端。

通过 lark-oapi SDK 的 ws.Client 建立长连接，接收飞书事件推送。
在独立线程 + 独立 event loop 中运行（SDK 的 start() 是阻塞调用）。
"""

import asyncio
import logging
import threading

logger = logging.getLogger(__name__)

_ws_thread: threading.Thread | None = None
_stop_flag: threading.Event | None = None


def start_ws_client() -> None:
    """启动飞书 WebSocket 长连接（非阻塞，在后台线程运行）。"""
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.FEISHU_APP_ID or not settings.FEISHU_APP_SECRET:
        logger.warning("飞书 APP_ID/APP_SECRET 未配置，跳过长连接启动")
        return

    global _ws_thread, _stop_flag
    _stop_flag = threading.Event()
    _ws_thread = threading.Thread(
        target=_run_ws_in_thread,
        name="feishu-ws",
        daemon=True,
    )
    _ws_thread.start()
    logger.info("飞书 WebSocket 长连接线程已启动")


def stop_ws_client() -> None:
    """停止飞书 WebSocket 长连接。"""
    global _stop_flag, _ws_thread
    if _stop_flag:
        _stop_flag.set()
    _ws_thread = None
    logger.info("飞书 WebSocket 长连接已请求停止")


def _run_ws_in_thread() -> None:
    """在独立线程中创建 event loop 并运行 WS client。"""
    import lark_oapi as lark
    import lark_oapi.ws as lark_ws

    from app.core.config import get_settings
    from app.platform.integrations.feishu.event_handler import build_event_handler

    # SDK 使用模块级 loop 变量，需替换为本线程的 loop
    thread_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(thread_loop)
    lark_ws.client.loop = thread_loop

    settings = get_settings()
    event_handler = build_event_handler()

    ws = lark_ws.Client(
        app_id=settings.FEISHU_APP_ID,
        app_secret=settings.FEISHU_APP_SECRET,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
        auto_reconnect=True,
    )

    try:
        logger.info("飞书 WebSocket 客户端正在连接...")
        ws.start()
    except Exception:
        logger.exception("飞书 WebSocket 客户端异常退出")
    finally:
        thread_loop.close()
