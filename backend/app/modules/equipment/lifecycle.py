"""设备模块后台服务声明：定时任务/生成器、飞书回调、维护计划长循环。

main.py 只认 EQUIPMENT_EXTENSION 实例，不再感知本模块内部细节。
"""

from __future__ import annotations

from app.modules.equipment import mcp_tools  # noqa: F401 — 触发 @mcp.tool() 注册
from app.modules.equipment.feishu.callbacks import register_feishu_callbacks
from app.modules.equipment.scheduled import (
    AUTO_CLOSE_TASK,
    TIMEOUT_SCAN_TASK,
    InspectionScheduleGenerator,
)
from app.modules.equipment.scheduler import (
    maintenance_plan_loop,
    stop_maintenance_plan_flag,
)
from app.platform.module_lifecycle import ModuleExtension, ModuleHost


class EquipmentExtension(ModuleExtension):
    """设备模块对进程生命周期的声明。"""

    code = "equipment"

    def register(self, host: ModuleHost) -> None:
        host.scheduler.register_generator(InspectionScheduleGenerator())
        host.scheduler.register_task(AUTO_CLOSE_TASK)
        # 派单超时监控：未指派/已指派未开工超时提醒设备主管。
        # （production 侧有同名 TIMEOUT_SCAN_TASK——分属各自模块后不再需要
        # 在 main 里起别名消歧，注册重名时 SchedulerRegistry 自会报错。）
        host.scheduler.register_task(TIMEOUT_SCAN_TASK)
        register_feishu_callbacks()
        host.add_background_loop(
            "equipment:maintenance_plan",
            maintenance_plan_loop,
        )

    async def stop(self) -> None:
        stop_maintenance_plan_flag.set()


EQUIPMENT_EXTENSION = EquipmentExtension()
