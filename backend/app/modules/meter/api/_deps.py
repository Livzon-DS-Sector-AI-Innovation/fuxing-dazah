"""meter API 权限依赖实例。

require_permission 是工厂，每次调用生成新闭包，依赖实例必须在此集中创建、
各端点引用同一对象，便于统一审计与测试 patch。台账读取类同时放行
``meter:*:read``（模块通配读取码）与对应资源读取码：管理员习惯只授
通配码，细分角色只授资源码，两种授权方式都应能读（管理侧的总览除外，
见 overview_read 注释）。
"""

from __future__ import annotations

from app.platform.permission.deps import require_permission

# 跨资源读取（提醒/报告元数据/部门列表等同时覆盖两类台账的端点）
read_any = require_permission(
    "meter:*:read", "meter:instrument:read", "meter:gas-detector:read"
)
instrument_read = require_permission("meter:*:read", "meter:instrument:read")
instrument_create = require_permission("meter:instrument:create")
instrument_update = require_permission("meter:instrument:update")
instrument_delete = require_permission("meter:instrument:delete")

gas_detector_read = require_permission("meter:*:read", "meter:gas-detector:read")
gas_detector_create = require_permission("meter:gas-detector:create")
gas_detector_update = require_permission("meter:gas-detector:update")
gas_detector_delete = require_permission("meter:gas-detector:delete")

report_upload = require_permission("meter:report:upload")
report_delete = require_permission("meter:report:delete")
config_manage = require_permission("meter:config:manage")

# 总览是管理侧数据：只有配置管理员看得到。通配读码和资源读码都只是台账查询角色，
# 一律不放行（菜单与 /meter 页面同口径，否则前端隐藏了入口、API 却仍能读到）
overview_read = require_permission("meter:config:manage")

# 部门列表/负责人候选：部门管理页由 config:manage 放行，台账读者也要用它做部门筛选
departments_read = require_permission(
    "meter:config:manage",
    "meter:*:read",
    "meter:instrument:read",
    "meter:gas-detector:read",
)

# AI 提取日期会回写器具/探测器的检定日期，任一台账的更新权限即可
ledger_date_write = require_permission(
    "meter:instrument:update", "meter:gas-detector:update"
)
