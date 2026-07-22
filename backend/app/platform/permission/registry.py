"""权限注册表：自动发现各模块声明的权限，启动时同步到数据库。

各模块在自己的 `permissions.py` 中声明权限列表，格式：

    from app.platform.permission.registry import PermissionDef

    PERMISSIONS: list[PermissionDef] = [
        PermissionDef("module:resource:action", "名称", "module", "resource", "action"),
        ...
    ]

本模块会在启动时自动扫描所有已注册模块的 `permissions.py`，汇总权限并同步到数据库。
"""

import importlib
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.permission.models import Permission
from app.shared.module_registry import BUSINESS_MODULES

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PermissionDef:
    """权限定义。各模块在 permissions.py 中使用此类型声明权限。"""

    code: str
    name: str
    module: str
    resource: str
    action: str
    description: str = ""


# ── 平台级权限（不属于任何业务模块） ──

_PLATFORM_PERMISSIONS: list[PermissionDef] = [
    PermissionDef("permission:role:manage", "管理角色", "permission", "role", "manage"),
    PermissionDef(
        "permission:user:assign", "分配用户角色", "permission", "user", "assign"
    ),
    PermissionDef("permission:user:view", "查看用户权限", "permission", "user", "view"),
]


def _discover_permissions() -> list[PermissionDef]:
    """自动扫描所有业务模块的 permissions.py，收集权限定义。"""
    all_permissions: list[PermissionDef] = list(_PLATFORM_PERMISSIONS)

    for module_def in BUSINESS_MODULES:
        module_path = f"app.modules.{module_def.code}.permissions"
        try:
            mod = importlib.import_module(module_path)
            module_perms = getattr(mod, "PERMISSIONS", [])
            if module_perms:
                all_permissions.extend(module_perms)
                logger.debug(
                    "Discovered %d permissions from %s",
                    len(module_perms),
                    module_def.code,
                )
        except ModuleNotFoundError:
            # 模块尚未声明 permissions.py，跳过
            pass

    return all_permissions


# 全局权限注册表（启动时填充）
PERMISSION_REGISTRY: list[PermissionDef] = []


def get_permissions_by_module() -> dict[str, list[PermissionDef]]:
    """按模块分组返回权限列表。"""
    result: dict[str, list[PermissionDef]] = {}
    for p in PERMISSION_REGISTRY:
        result.setdefault(p.module, []).append(p)
    return result


async def sync_permissions(db: AsyncSession) -> None:
    """将代码声明的权限同步到数据库。

    - 新增的权限：INSERT
    - 已有的权限：更新 name/description（如果变化）
    - 已软删除但重新声明的权限：恢复（is_deleted=False）
    - 代码中移除的权限：软删除（is_deleted=True）
    """
    global PERMISSION_REGISTRY
    PERMISSION_REGISTRY = _discover_permissions()

    # 查询所有权限（包括软删除的），按 code 唯一匹配
    stmt = select(Permission)
    result = await db.execute(stmt)
    existing: dict[str, Permission] = {p.code: p for p in result.scalars()}

    registry_codes = {p.code for p in PERMISSION_REGISTRY}

    # 新增或更新
    for pdef in PERMISSION_REGISTRY:
        if pdef.code in existing:
            perm = existing[pdef.code]
            changed = False
            if perm.name != pdef.name:
                perm.name = pdef.name
                changed = True
            if perm.module != pdef.module:
                perm.module = pdef.module
                changed = True
            if perm.resource != pdef.resource:
                perm.resource = pdef.resource
                changed = True
            if perm.action != pdef.action:
                perm.action = pdef.action
                changed = True
            if perm.description != pdef.description:
                perm.description = pdef.description
                changed = True
            if perm.is_deleted:
                perm.is_deleted = False
                changed = True
            if changed:
                await db.flush()
        else:
            new_perm = Permission(
                code=pdef.code,
                name=pdef.name,
                module=pdef.module,
                resource=pdef.resource,
                action=pdef.action,
                description=pdef.description or None,
                is_system=False,
            )
            db.add(new_perm)
            await db.flush()

    # 软删除代码中已移除的权限（仅对未删除的记录操作）
    for code, perm in existing.items():
        if code not in registry_codes and not perm.is_system and not perm.is_deleted:
            perm.is_deleted = True
    await db.flush()
