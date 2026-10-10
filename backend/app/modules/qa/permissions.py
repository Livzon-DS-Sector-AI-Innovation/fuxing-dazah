"""QA 模块权限声明。

读取需显式授权（与 meter 一致：授 ``qa:*:read`` 模块通配读码即可访问
台账/检索/文件预览），写入和审计权限各自独立。
"""

from app.platform.permission.registry import PermissionDef

PERMISSIONS: list[PermissionDef] = [
    PermissionDef("qa:*:read", "读取 QA 模块数据", "qa", "*", "read"),
    PermissionDef("qa:master:create", "创建 QA 主数据", "qa", "master", "create"),
    PermissionDef("qa:master:update", "更新 QA 主数据", "qa", "master", "update"),
    PermissionDef("qa:master:deactivate", "停用/启用 QA 主数据", "qa", "master", "deactivate"),
    PermissionDef("qa:document:create", "创建 QA 文件台账", "qa", "document", "create"),
    PermissionDef("qa:document:update", "更新 QA 文件台账", "qa", "document", "update"),
    PermissionDef("qa:document:deactivate", "停用/启用 QA 文件台账", "qa", "document", "deactivate"),
    PermissionDef("qa:version:create", "登记 QA 文件版本", "qa", "version", "create"),
    PermissionDef("qa:version:make_current", "设置 QA 当前版本", "qa", "version", "make_current"),
    PermissionDef("qa:version:disable", "停用 QA 文件版本", "qa", "version", "disable"),
    PermissionDef("qa:relation:manage", "维护 QA 文件关联", "qa", "relation", "manage"),
    PermissionDef("qa:config:manage", "维护 QA 文件类型", "qa", "config", "manage"),
    PermissionDef("qa:audit:read", "查看 QA 审计日志", "qa", "audit", "read"),
]

