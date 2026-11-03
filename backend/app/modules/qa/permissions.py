"""QA 模块权限声明。

读取需显式授权（与 meter 一致：授 ``qa:*:read`` 模块通配读码即可访问
台账/检索/文件预览），写入和审计权限各自独立。
"""

from app.platform.permission.registry import PermissionDef

PERMISSIONS: list[PermissionDef] = [
    PermissionDef("qa:*:read", "读取 QA 模块数据", "qa", "*", "read"),
    PermissionDef("qa:master:create", "创建 QA 主数据", "qa", "master", "create"),
    PermissionDef("qa:master:update", "更新 QA 主数据", "qa", "master", "update"),
    PermissionDef(
        "qa:master:deactivate", "停用/启用 QA 主数据", "qa", "master", "deactivate"
    ),
    PermissionDef("qa:document:create", "创建 QA 文件台账", "qa", "document", "create"),
    PermissionDef("qa:document:update", "更新 QA 文件台账", "qa", "document", "update"),
    PermissionDef(
        "qa:document:deactivate",
        "停用/启用 QA 文件台账",
        "qa",
        "document",
        "deactivate",
    ),
    PermissionDef("qa:version:create", "登记 QA 文件版本", "qa", "version", "create"),
    PermissionDef(
        "qa:version:make_current", "设置 QA 当前版本", "qa", "version", "make_current"
    ),
    PermissionDef("qa:version:disable", "停用 QA 文件版本", "qa", "version", "disable"),
    PermissionDef("qa:relation:manage", "维护 QA 文件关联", "qa", "relation", "manage"),
    PermissionDef("qa:config:manage", "维护 QA 文件类型", "qa", "config", "manage"),
    PermissionDef("qa:audit:read", "查看 QA 审计日志", "qa", "audit", "read"),
    # ── 偏差管理 / CAPA ──
    # 偏差读取单独成码：发生部门人员可只授偏差可见而不开放知识库；
    # 模块通配读码 qa:*:read 同样放行偏差/CAPA 读取。
    PermissionDef("qa:deviation:read", "查看偏差台账", "qa", "deviation", "read"),
    PermissionDef("qa:deviation:create", "登记偏差", "qa", "deviation", "create"),
    PermissionDef("qa:deviation:update", "编辑与推进偏差", "qa", "deviation", "update"),
    PermissionDef("qa:capa:read", "查看 CAPA 台账", "qa", "capa", "read"),
    PermissionDef("qa:capa:create", "发起 CAPA", "qa", "capa", "create"),
    PermissionDef("qa:capa:update", "编辑与推进 CAPA", "qa", "capa", "update"),
]
