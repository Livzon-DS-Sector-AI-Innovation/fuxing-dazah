"""生产模块权限声明。"""

from app.platform.permission.registry import PermissionDef

PERMISSIONS: list[PermissionDef] = [
    PermissionDef(
        "production:process:manage", "管理产品工艺", "production", "process", "manage"
    ),
    PermissionDef(
        "production:batch:submit", "提交批次执行", "production", "batch", "submit"
    ),
    PermissionDef(
        "production:batch:read", "查看生产批次", "production", "batch", "read"
    ),
]
