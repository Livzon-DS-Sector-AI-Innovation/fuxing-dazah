"""Safety API — 飞书事件订阅管理端点（WebSocket 状态查询 / 手动恢复）。"""

from fastapi import APIRouter

from app.core.response import ApiResponse
from app.modules.safety.feishu.event_client import get_ws_status, restart_ws

feishu_router = APIRouter()


@feishu_router.get("/feishu/ws/status", response_model=ApiResponse, summary="查询飞书 WebSocket 连接状态")
async def ws_status():
    """查询安全模块飞书事件订阅的 WebSocket 连接状态。

    Returns:
        connected: WebSocket 是否存活
        subscription_ok: Bitable 文档事件订阅是否成功
        registered_events: 已注册的事件类型
        frame_stats: 帧活动统计（received/control/data/event/error）
        last_pong_seconds_ago: 距最后一次 PONG 的秒数
        pong_watchdog_healthy: PONG 看门狗是否健康
    """
    status = await get_ws_status()
    return ApiResponse(data=status)


@feishu_router.post("/feishu/ws/restart", response_model=ApiResponse, summary="手动恢复飞书 WebSocket 连接")
async def ws_restart():
    """手动恢复安全模块飞书事件订阅的 WebSocket 连接。

    当 WS 连接因重试次数耗尽而自动退出时，调用此端点重新启动。
    正常运行时调用无害（会先关闭旧连接再建新连接）。
    """
    result = await restart_ws()
    return ApiResponse(data=result, message=result.get("message", ""))
