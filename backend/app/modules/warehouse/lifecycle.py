"""仓储模块后台服务声明（接入 main 的模块生命周期契约）。

按 app/platform/module_lifecycle.py 契约把仓储的全部后台服务收敛到模块内部：
- register：定时任务（主仓 8 项 + 五金 7 项）入调度注册表；飞书事件回调注册
  （gateway 的 im/card 处理器、approval_ingest 的审批实例四事件处理器——
  均为导入即注册）；通知总闸应用。
- start：仓储专属飞书 WS 长连接（WAREHOUSE_FEISHU_WS_ENABLED 门控）。
- stop：WS 停止（置 stop-flag，连接自然收尾）。
"""

from __future__ import annotations

import logging

from app.platform.module_lifecycle import ModuleExtension, ModuleHost

logger = logging.getLogger(__name__)


class WarehouseExtension(ModuleExtension):
    """仓储模块对进程生命周期的声明。"""

    code = "warehouse"

    def register(self, host: ModuleHost) -> None:
        from app.modules.warehouse import scheduled as wh_scheduled
        from app.modules.warehouse.hardware.scheduled import (
            register_hardware_tasks,
        )

        # 主仓定时任务（快照/智能扫描/效期冻结/晨报/推送泵/QC 扫描/分析/直读预热）
        for task in (
            wh_scheduled.STOCK_DAILY_SNAPSHOT_TASK,
            wh_scheduled.INTELLIGENCE_SCAN_TASK,
            wh_scheduled.EXPIRY_FREEZE_TASK,
            wh_scheduled.MORNING_REPORT_TASK,
            wh_scheduled.PUSH_CENTER_TICK_TASK,
            wh_scheduled.QC_SCAN_TASK,
            wh_scheduled.ANALYSIS_REPORT_TASK,
            wh_scheduled.DIRECT_CACHE_WARMUP_TASK,
        ):
            host.scheduler.register_task(task)
        # 五金库定时任务（审批轮询/对账/镜像/月度计划/呆滞/温湿度/用量回填/
        # superagent 桥——register_hardware_tasks 内部一并挂载）
        register_hardware_tasks(host.scheduler)

        # 飞书事件回调注册（导入即注册 @on_event）
        import app.modules.warehouse.agent.gateway  # noqa: F401
        import app.modules.warehouse.hardware.approval_ingest  # noqa: F401

        # 仓储通知总闸（WAREHOUSE_NOTIFY_DRY_RUN=true 时未显式传参的发送只落日志）
        from app.modules.warehouse.feishu import notify_gate

        notify_gate.apply_env_notify_gate()

    def start(self, host: ModuleHost) -> None:
        from app.core.config import get_settings

        if not get_settings().WAREHOUSE_FEISHU_WS_ENABLED:
            return
        from app.modules.warehouse.feishu import event_client as wh_event_client

        host.add_background_loop("warehouse_feishu_ws", wh_event_client.start_ws)

    async def stop(self) -> None:
        from app.modules.warehouse.feishu import event_client as wh_event_client

        await wh_event_client.stop_ws()


WAREHOUSE_EXTENSION = WarehouseExtension()
