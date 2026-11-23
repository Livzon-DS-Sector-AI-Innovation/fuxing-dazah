"""生产模块后台服务声明：定时任务 + MCP 工具注册触发。

main.py 只认 PRODUCTION_EXTENSION 实例，不再感知本模块内部细节。
"""

from __future__ import annotations

from app.modules.production import mcp_tools  # noqa: F401 — 触发 @mcp.tool() 注册
from app.modules.production.scheduled import (
    BATCH_START_REMINDER_TASK,
    EXECUTION_TIMEOUT_SCAN_TASK,
)
from app.platform.module_lifecycle import ModuleExtension, ModuleHost


class ProductionExtension(ModuleExtension):
    """生产模块对进程生命周期的声明。"""

    code = "production"

    def register(self, host: ModuleHost) -> None:
        host.scheduler.register_task(BATCH_START_REMINDER_TASK)
        # 工序执行超时扫描（与 equipment 的派单超时扫描重名历史见其注释）。
        host.scheduler.register_task(EXECUTION_TIMEOUT_SCAN_TASK)


PRODUCTION_EXTENSION = ProductionExtension()
