"""平台级飞书集成对进程生命周期的声明：成员同步长循环 + 事件长连接。

main.py 只认本扩展实例；线程/连接的启停细节（含凭证缺失时跳过）收敛在
ws_client / sync 内部，与旧 lifespan 行为等价。
"""

from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.platform.module_lifecycle import ModuleExtension, ModuleHost


class FeishuPlatformExtension(ModuleExtension):
    """平台飞书设施（作为 0 号扩展排在模块清单最前，start 先于各模块）。"""

    code = "feishu"

    def register(self, host: ModuleHost) -> None:
        from app.platform.integrations.feishu.sync import member_sync_loop

        host.add_background_loop("feishu:member_sync", member_sync_loop)

    def start(self, host: ModuleHost) -> None:
        # ── 平台级飞书 WebSocket 长连接（全部模块回调已注册完毕）──
        if not get_settings().FEISHU_WS_ENABLED:
            return
        from app.platform.integrations.feishu.event_handler import set_main_loop
        from app.platform.integrations.feishu.ws_client import start_ws_client

        set_main_loop(asyncio.get_running_loop())
        start_ws_client()

    async def stop(self) -> None:
        from app.platform.integrations.feishu.sync import stop_member_sync_flag
        from app.platform.integrations.feishu.ws_client import stop_ws_client

        stop_member_sync_flag.set()
        # name=None 停止全部实例（含职称评审等命名长连接）。
        stop_ws_client()


FEISHU_PLATFORM_EXTENSION = FeishuPlatformExtension()
