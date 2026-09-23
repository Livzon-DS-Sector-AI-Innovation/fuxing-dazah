"""QA 模块权限声明。

读取权限按需求对所有已登录用户开放，因此这里只注册写入和审计权限。
"""

from app.platform.permission.registry import PermissionDef

PERMISSIONS: list[PermissionDef] = [
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

