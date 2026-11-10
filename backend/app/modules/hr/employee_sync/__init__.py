"""员工档案飞书多维表格同步。

单向同步：飞书多维表格源表（HR 维护）→ 本地 hr.employees（系统唯一数据落点）。
同时在同一 Base 内自动维护脱敏副本表「员工档案（培训专用·脱敏）」，
只含培训管理所需的白名单列，不出现身份证/学校/专业等个人敏感信息。

组件：
- config：绑定配置（SystemSetting KV）+ 脱敏表白名单
- mapping：飞书记录值 ↔ Employee 字段转换
- service：全量对账、事件应用、脱敏表维护
- handler：WS 实时事件处理（注册到平台事件总线）
- scheduled：5 分钟兜底对账任务
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
