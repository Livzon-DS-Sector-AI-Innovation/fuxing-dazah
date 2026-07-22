"""安全模块权限声明。"""

from app.platform.permission.registry import PermissionDef

PERMISSIONS: list[PermissionDef] = [
    PermissionDef("safety:hazard:read", "查看隐患台账", "safety", "hazard", "read"),
]
