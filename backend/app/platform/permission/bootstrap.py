"""权限系统启动引导。

在应用 lifespan 中调用，完成：
1. 同步权限定义到数据库
2. 确保 super_admin 角色存在并关联所有权限
3. 将配置的管理员工号绑定 super_admin 角色
"""

import asyncio
import logging

from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.platform.identity.models import User as IdentityUser
from app.platform.permission.cache import invalidate_all_caches
from app.platform.permission.models import Role
from app.platform.permission.registry import PERMISSION_REGISTRY, sync_permissions
from app.platform.permission.repository import PermissionRepository

logger = logging.getLogger(__name__)


async def bootstrap_permissions(db: AsyncSession, settings: Settings) -> None:
    """权限系统启动引导，在应用 lifespan 中调用。"""
    await sync_permissions(db)

    perm_repo = PermissionRepository()
    admin_role = await perm_repo.get_role_by_code(db, "super_admin")
    if not admin_role:
        admin_role = Role(
            code="super_admin",
            name="超级管理员",
            description="系统内置超级管理员，拥有所有权限",
            data_scope="all",
            is_system=True,
        )
        admin_role = await perm_repo.create_role(db, admin_role)

    all_perms = await perm_repo.list_permissions(db)
    all_perm_ids = [p.id for p in all_perms]
    await perm_repo.set_role_permissions(db, admin_role.id, all_perm_ids)

    for emp_no in settings.ADMIN_EMPLOYEE_NOS:
        stmt = sa_select(IdentityUser).where(
            IdentityUser.employee_no == emp_no,
            IdentityUser.is_deleted == False,  # noqa: E712
        )
        result = await db.execute(stmt)
        admin_user = result.scalar_one_or_none()
        if admin_user:
            await perm_repo.assign_role_to_user(
                db, admin_user.id, admin_role.id,
            )
        else:
            logger.warning(
                "Admin employee_no=%s not found, skipping", emp_no,
            )

    await db.commit()
    # 权限定义可能刚新增（例如 system:feedback:manage），角色权限已重算。
    # 清掉旧的用户权限缓存，避免前端 /me 已显示新权限、后端门禁仍按旧缓存 403。
    try:
        # Redis 不可达时不阻塞启动；最坏情况下旧缓存 5 分钟后自然过期。
        await asyncio.wait_for(invalidate_all_caches(), timeout=5)
    except Exception:
        logger.warning("Permission cache invalidation failed", exc_info=True)
    logger.info(
        "Permission bootstrap: synced %d permissions, admin role ready",
        len(PERMISSION_REGISTRY),
    )
