"""人事提醒框架：聚合注册全部提醒任务，main.py 一行挂载（仿 quality 模式）。

新增提醒类型的步骤：
1. 在本包写一个 *_scheduled.py：扫描函数 + TaskDefinition
   （配置统一走 reminder.config.load_reminder_config，键 hr_reminder.<type>.*）
2. 在下方 register_reminder_tasks() 里登记一行
3. 前端 ReminderSettingsCard 加对应配置项

已有提醒：转正提醒（probation_scheduled，每天 09:00）、合同到期提醒
（contract_scheduled，每天 09:10）。
"""

from app.platform.scheduler import SchedulerRegistry


def register_reminder_tasks(registry: SchedulerRegistry) -> None:
    """聚合注册人事提醒任务；接收人未配置时各任务仅记日志不推送。"""
    from app.modules.hr.probation_scheduled import PROBATION_REMINDER_TASK
    from app.modules.hr.reminder.contract_scheduled import CONTRACT_REMINDER_TASK

    registry.register_task(PROBATION_REMINDER_TASK)
    registry.register_task(CONTRACT_REMINDER_TASK)
