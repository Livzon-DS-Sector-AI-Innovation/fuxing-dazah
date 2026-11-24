"""能源模块后台服务声明：定时任务聚合注册（register_tasks 模式）。"""

from __future__ import annotations

from app.modules.energy.scheduler import register_tasks
from app.platform.module_lifecycle import ModuleExtension, ModuleHost


class EnergyExtension(ModuleExtension):
    """能源模块对进程生命周期的声明。"""

    code = "energy"

    def register(self, host: ModuleHost) -> None:
        register_tasks(host.scheduler)


ENERGY_EXTENSION = EnergyExtension()
