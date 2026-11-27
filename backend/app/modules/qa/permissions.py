"""QA 模块权限声明。

约定：
- 权限码固定三段 ``qa:<resource>:<action>``，不使用 ``*``。
- ``qa:all:read`` 是模块全域读码：在所有域读门禁中显式列出，不是自动通配。
- 各域读门禁 = ``qa:all:read`` OR 域读码 OR 该域写码（写权限隐含读）。
"""

from app.platform.permission.registry import PermissionDef

PERMISSIONS: list[PermissionDef] = [
    # ── 知识库：质量主数据 / 批准文件台账 / 版本 / 关联 / 检索 / 预览 ──
    PermissionDef(
        "qa:all:read",
        "读取 QA 业务数据（主数据/文件/偏差/CAPA/PQR/COA，不含操作日志）",
        "qa",
        "all",
        "read",
    ),
    PermissionDef("qa:master:create", "创建 QA 主数据", "qa", "master", "create"),
    PermissionDef("qa:master:update", "更新 QA 主数据", "qa", "master", "update"),
    PermissionDef("qa:master:manage", "停用/启用 QA 主数据", "qa", "master", "manage"),
    PermissionDef("qa:document:create", "创建 QA 文件台账", "qa", "document", "create"),
    PermissionDef("qa:document:update", "更新 QA 文件台账", "qa", "document", "update"),
    PermissionDef(
        "qa:document:manage", "停用/启用 QA 文件台账", "qa", "document", "manage"
    ),
    PermissionDef("qa:version:create", "登记 QA 文件版本", "qa", "version", "create"),
    PermissionDef(
        "qa:version:set_current", "设置 QA 当前版本", "qa", "version", "set_current"
    ),
    PermissionDef("qa:version:manage", "停用/启用 QA 文件版本", "qa", "version", "manage"),
    PermissionDef(
        "qa:relation:manage", "维护 QA 文件关联（可读知识库）", "qa", "relation", "manage"
    ),
    PermissionDef(
        "qa:config:manage", "维护 QA 文件类型（可读知识库）", "qa", "config", "manage"
    ),
    PermissionDef("qa:audit:read", "查看 QA 操作日志", "qa", "audit", "read"),
    # ── 偏差管理 / CAPA ──
    PermissionDef("qa:deviation:read", "查看偏差台账", "qa", "deviation", "read"),
    PermissionDef("qa:deviation:create", "登记偏差", "qa", "deviation", "create"),
    PermissionDef("qa:deviation:update", "编辑与推进偏差", "qa", "deviation", "update"),
    PermissionDef("qa:capa:read", "查看 CAPA 台账", "qa", "capa", "read"),
    PermissionDef("qa:capa:create", "发起 CAPA", "qa", "capa", "create"),
    PermissionDef("qa:capa:update", "编辑与推进 CAPA", "qa", "capa", "update"),
    # ── 年度产品审核（PQR）──
    PermissionDef("qa:apr:read", "查看 PQR 数据与汇总", "qa", "apr", "read"),
    PermissionDef("qa:apr:manage", "配置 PQR 产品与模板", "qa", "apr", "manage"),
    PermissionDef("qa:apr:enter", "录入 PQR 批次数据", "qa", "apr", "enter"),
    PermissionDef("qa:apr:export", "导出 PQR 汇总表", "qa", "apr", "export"),
    PermissionDef("qa:apr:lock", "锁定/解锁 PQR 年度", "qa", "apr", "lock"),
    # ── COA 客户标准与出具登记 ──
    PermissionDef("qa:coa:read", "查看 COA 标准与出具登记", "qa", "coa", "read"),
    PermissionDef("qa:coa:manage", "配置 COA 产品与客户标准", "qa", "coa", "manage"),
    PermissionDef("qa:coa:issue", "COA 出具登记（含导入登记）", "qa", "coa", "issue"),
]
