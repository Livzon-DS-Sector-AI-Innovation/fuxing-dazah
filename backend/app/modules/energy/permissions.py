"""能源管理模块权限声明。

权限编码规范: energy:<resource>:<action>
- read: 查看/读取
- create: 新增
- update: 编辑/修改
- delete: 删除
- trigger: 触发执行
"""

from app.platform.permission.registry import PermissionDef

PERMISSIONS: list[PermissionDef] = [
    # ── 数据源配置 ──
    PermissionDef(
        code="energy:device:read",
        name="查看数据源配置",
        module="energy",
        resource="device",
        action="read",
        description="查看能源数据源配置列表和详情",
    ),
    PermissionDef(
        code="energy:device:create",
        name="新增数据源配置",
        module="energy",
        resource="device",
        action="create",
        description="新增能源数据源配置",
    ),
    PermissionDef(
        code="energy:device:update",
        name="编辑数据源配置",
        module="energy",
        resource="device",
        action="update",
        description="编辑能源数据源配置",
    ),
    PermissionDef(
        code="energy:device:delete",
        name="删除数据源配置",
        module="energy",
        resource="device",
        action="delete",
        description="删除能源数据源配置",
    ),

    # ── 能源类型可视化配置 ──
    PermissionDef(
        code="energy:type_config:read",
        name="查看能源类型配置",
        module="energy",
        resource="type_config",
        action="read",
        description="查看能源类型可视化配置列表和详情",
    ),
    PermissionDef(
        code="energy:type_config:create",
        name="新增能源类型配置",
        module="energy",
        resource="type_config",
        action="create",
        description="新增能源类型可视化配置",
    ),
    PermissionDef(
        code="energy:type_config:update",
        name="编辑能源类型配置",
        module="energy",
        resource="type_config",
        action="update",
        description="编辑能源类型可视化配置",
    ),
    PermissionDef(
        code="energy:type_config:delete",
        name="删除能源类型配置",
        module="energy",
        resource="type_config",
        action="delete",
        description="删除能源类型可视化配置",
    ),

    # ── 能源总览与数据 ──
    PermissionDef(
        code="energy:overview:read",
        name="查看能源总览与数据",
        module="energy",
        resource="overview",
        action="read",
        description="查看能源总览、能耗数据、历史明细和统计",
    ),
    PermissionDef(
        code="energy:overview:delete",
        name="删除能耗数据",
        module="energy",
        resource="overview",
        action="delete",
        description="删除能耗采集历史记录",
    ),

    # ── 采集管理 ──
    PermissionDef(
        code="energy:collect:trigger",
        name="管理采集任务",
        module="energy",
        resource="collect",
        action="trigger",
        description="手动触发采集和修改自动采集设置",
    ),

    # ── 采集日志 ──
    PermissionDef(
        code="energy:collect_log:read",
        name="查看采集日志",
        module="energy",
        resource="collect_log",
        action="read",
        description="查看采集日志列表和详情",
    ),
    PermissionDef(
        code="energy:collect_log:delete",
        name="清空采集日志",
        module="energy",
        resource="collect_log",
        action="delete",
        description="清空采集日志历史记录",
    ),

    # ── 预警管理 ──
    PermissionDef(
        code="energy:alert:read",
        name="查看预警规则与记录",
        module="energy",
        resource="alert",
        action="read",
        description="查看预警规则和预警记录列表",
    ),
    PermissionDef(
        code="energy:alert:create",
        name="新增预警规则",
        module="energy",
        resource="alert",
        action="create",
        description="新增能耗预警规则",
    ),
    PermissionDef(
        code="energy:alert:update",
        name="编辑预警规则与处理记录",
        module="energy",
        resource="alert",
        action="update",
        description="编辑预警规则和处理预警记录",
    ),
    PermissionDef(
        code="energy:alert:delete",
        name="删除预警规则",
        module="energy",
        resource="alert",
        action="delete",
        description="删除能耗预警规则",
    ),

    # ── 车间预警配置 ──
    PermissionDef(
        code="energy:workshop_config:read",
        name="查看车间预警配置",
        module="energy",
        resource="workshop_config",
        action="read",
        description="查看车间预警配置列表和详情",
    ),
    PermissionDef(
        code="energy:workshop_config:create",
        name="新增车间预警配置",
        module="energy",
        resource="workshop_config",
        action="create",
        description="新增车间预警配置",
    ),
    PermissionDef(
        code="energy:workshop_config:update",
        name="编辑车间预警配置",
        module="energy",
        resource="workshop_config",
        action="update",
        description="编辑车间预警配置",
    ),
    PermissionDef(
        code="energy:workshop_config:delete",
        name="删除车间预警配置",
        module="energy",
        resource="workshop_config",
        action="delete",
        description="删除车间预警配置",
    ),
]
