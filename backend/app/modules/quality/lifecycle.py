"""质量模块后台服务声明：定时任务聚合注册 + 模块专属飞书事件长连接。

（与 quality/feishu/lifecycle.py 的区别：那管单条 WS 的 task 句柄，
这管模块对进程生命周期的整体声明。）
"""

from __future__ import annotations

from app.modules.quality.feishu.lifecycle import start_ws_task, stop_ws_task
from app.modules.quality.scheduled import register_tasks
from app.platform.module_lifecycle import ModuleExtension, ModuleHost


class QualityExtension(ModuleExtension):
    """质量模块对进程生命周期的声明。"""

    code = "quality"

    def register(self, host: ModuleHost) -> None:
        register_tasks(host.scheduler)

    def start(self, host: ModuleHost) -> None:
        # 质量模块专属飞书事件订阅（独立应用凭据，事件处理器注册与断线
        # 自愈收敛在 feishu/lifecycle 内部）。凭证缺失时其内部自行跳过。
        start_ws_task()

    async def stop(self) -> None:
        await stop_ws_task()


QUALITY_EXTENSION = QualityExtension()
