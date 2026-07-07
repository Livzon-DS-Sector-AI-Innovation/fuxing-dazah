"""质量管理模块权限声明。"""

from app.platform.permission.registry import PermissionDef

PERMISSIONS: list[PermissionDef] = [
    # ── 液相计算表解析 ──
    PermissionDef("quality:lc:read", "查看液相解析", "quality", "lc", "read"),
    PermissionDef("quality:lc:upload", "上传液相计算表", "quality", "lc", "upload"),
    # ── 报告生成 ──
    PermissionDef("quality:report:read", "查看报告单", "quality", "report", "read"),
    PermissionDef("quality:report:generate", "生成报告单", "quality", "report", "generate"),
    # ── 质量检验 ──
    PermissionDef("quality:inspection:read", "查看质量检验", "quality", "inspection", "read"),
    PermissionDef("quality:inspection:create", "新增检验记录", "quality", "inspection", "create"),
    PermissionDef("quality:inspection:update", "编辑检验记录", "quality", "inspection", "update"),
    # ── 偏差管理 ──
    PermissionDef("quality:deviation:read", "查看偏差", "quality", "deviation", "read"),
    PermissionDef("quality:deviation:create", "新增偏差", "quality", "deviation", "create"),
    # ── CAPA ──
    PermissionDef("quality:capa:read", "查看CAPA", "quality", "capa", "read"),
    PermissionDef("quality:capa:create", "新增CAPA", "quality", "capa", "create"),
    # ── 变更控制 ──
    PermissionDef("quality:change:read", "查看变更", "quality", "change", "read"),
    PermissionDef("quality:change:create", "新增变更", "quality", "change", "create"),
]
