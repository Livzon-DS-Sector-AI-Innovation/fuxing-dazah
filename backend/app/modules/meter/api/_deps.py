"""meter API 权限依赖实例。

require_permission 是工厂，每次调用生成新闭包，依赖实例必须在此集中创建、
各端点引用同一对象，便于统一审计与测试 patch。读取类同时放行
``meter:*:read``（模块通配读取码）与对应资源读取码：管理员习惯只授
通配码，细分角色只授资源码，两种授权方式都应能读。
"""

from __future__ import annotations

from app.platform.permission.deps import require_permission

# 跨资源读取（总览/提醒/报告元数据/部门列表等同时覆盖两类台账的端点）
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

# AI 提取日期会回写器具/探测器的检定日期，任一台账的更新权限即可
ledger_date_write = require_permission(
    "meter:instrument:update", "meter:gas-detector:update"
)
