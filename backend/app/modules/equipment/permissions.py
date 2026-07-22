"""设备模块权限声明。"""

from app.platform.permission.registry import PermissionDef

PERMISSIONS: list[PermissionDef] = [
    # ── 设备台账 ──
    PermissionDef("equipment:asset:read", "查看设备台账", "equipment", "asset", "read"),
    PermissionDef(
        "equipment:asset:create", "创建设备台账", "equipment", "asset", "create"
    ),
    PermissionDef(
        "equipment:asset:update", "编辑设备台账", "equipment", "asset", "update"
    ),
    PermissionDef(
        "equipment:asset:delete", "删除设备台账", "equipment", "asset", "delete"
    ),
    PermissionDef(
        "equipment:asset:import", "导入设备台账", "equipment", "asset", "import"
    ),
    # ── 巡检 ──
    PermissionDef(
        "equipment:inspection:read", "查看巡检", "equipment", "inspection", "read"
    ),
    PermissionDef(
        "equipment:inspection:create", "创建巡检", "equipment", "inspection", "create"
    ),
    PermissionDef(
        "equipment:inspection:update", "编辑巡检", "equipment", "inspection", "update"
    ),
    PermissionDef(
        "equipment:inspection:delete", "删除巡检", "equipment", "inspection", "delete"
    ),
    # ── 维护保养 ──
    PermissionDef(
        "equipment:maintenance:read", "查看维护保养", "equipment", "maintenance", "read"
    ),
    PermissionDef(
        "equipment:maintenance:create",
        "创建维护保养",
        "equipment",
        "maintenance",
        "create",
    ),
    PermissionDef(
        "equipment:maintenance:update",
        "编辑维护保养",
        "equipment",
        "maintenance",
        "update",
    ),
    PermissionDef(
        "equipment:maintenance:delete",
        "删除维护保养",
        "equipment",
        "maintenance",
        "delete",
    ),
    # ── 工单 ──
    PermissionDef(
        "equipment:work_order:read", "查看工单", "equipment", "work_order", "read"
    ),
    PermissionDef(
        "equipment:work_order:create", "创建工单", "equipment", "work_order", "create"
    ),
    PermissionDef(
        "equipment:work_order:update", "编辑工单", "equipment", "work_order", "update"
    ),
    PermissionDef(
        "equipment:work_order:approve", "审批工单", "equipment", "work_order", "approve"
    ),
    # ── 备件 ──
    PermissionDef(
        "equipment:spare_part:read", "查看备件", "equipment", "spare_part", "read"
    ),
    PermissionDef(
        "equipment:spare_part:create", "创建备件", "equipment", "spare_part", "create"
    ),
    PermissionDef(
        "equipment:spare_part:update", "编辑备件", "equipment", "spare_part", "update"
    ),
    PermissionDef(
        "equipment:spare_part:delete", "删除备件", "equipment", "spare_part", "delete"
    ),
    # ── 人员配置 ──
    PermissionDef(
        "equipment:personnel:read", "查看人员配置", "equipment", "personnel", "read"
    ),
    PermissionDef(
        "equipment:personnel:manage", "管理人员配置", "equipment", "personnel", "manage"
    ),
    # ── 仪表盘 ──
    PermissionDef(
        "equipment:stats:read", "查看设备仪表盘", "equipment", "stats", "read"
    ),
]
