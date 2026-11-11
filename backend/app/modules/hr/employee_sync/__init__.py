"""员工档案飞书多维表格同步。

单向同步：飞书多维表格源表（HR 维护）→ 本地 hr.employees（系统唯一数据落点）。
同步时机：每天凌晨 02:00 定时全量对账 + 管理端手动立即同步（无实时事件）。

组件：
- config：绑定配置（SystemSetting KV）+ 脱敏名单白名单字段
- mapping：飞书记录值 ↔ Employee 字段转换
- service：全量对账、脱敏名单维护
- scheduled：每日定时对账任务
- routes：绑定/手动同步 API
"""

from app.modules.hr.employee_sync.config import (
    EmployeeSyncConfig,
    load_config,
    save_config_values,
)

__all__ = [
    "EmployeeSyncConfig",
    "load_config",
    "save_config_values",
]
