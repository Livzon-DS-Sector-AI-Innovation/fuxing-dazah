"""仪表模块后台服务声明：检定到期提醒任务。"""

from __future__ import annotations

from app.modules.meter.scheduler import CALIBRATION_REMINDER_TASK
from app.platform.module_lifecycle import ModuleExtension, ModuleHost


class MeterExtension(ModuleExtension):
    """仪表模块对进程生命周期的声明。"""

    code = "meter"

    def register(self, host: ModuleHost) -> None:
        host.scheduler.register_task(CALIBRATION_REMINDER_TASK)


METER_EXTENSION = MeterExtension()
