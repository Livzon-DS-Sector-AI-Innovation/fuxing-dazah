import logging
from typing import Annotated

import jwt
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.platform.identity.models import User
from app.platform.identity.repository import UserRepository
from app.platform.identity.token_blacklist import is_token_revoked

logger = logging.getLogger(__name__)

_user_repo = UserRepository()


async def _has_manage_permission(db: AsyncSession, user: User) -> bool:
    """是否拥有管理员权限（permission:role:manage，运行时以角色为准）。

    局部导入避免与 permission.deps 的循环依赖。
    """
    from app.platform.permission.deps import get_user_permissions

    perms = await get_user_permissions(str(user.id), db)
    return "permission:role:manage" in perms


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User | None:
    # ── 1. 正常解析 auth_token ──
    auth = request.headers.get("Authorization", "")
    token: str | None = None
    if auth.startswith("Bearer "):
        token = auth.removeprefix("Bearer ")
    else:
        cookie_token = request.cookies.get("auth_token")
        if cookie_token:
            token = cookie_token

    if not token:
        return None
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=["HS256"]
        )
    except jwt.InvalidTokenError:
        return None

    # 已登出吊销的 token 视为未登录（无 jti 的历史 token 跳过检查）
    jti = payload.get("jti")
    if jti and await is_token_revoked(str(jti)):
        return None

    open_id: str | None = payload.get("open_id")
    if not open_id:
        return None

    real_user = await _user_repo.get_by_feishu_open_id(db, open_id)
    if real_user is None:
        return None

    # ── 2. 检测 impersonate_token ──
    imp_token = request.cookies.get("impersonate_token")
    if not imp_token:
        return real_user

    try:
        imp_payload = jwt.decode(
            imp_token, settings.SECRET_KEY, algorithms=["HS256"]
        )
    except jwt.InvalidTokenError:
        # 无效或过期，忽略，返回真实用户
        return real_user

    imp_jti = imp_payload.get("jti")
    if imp_jti and await is_token_revoked(str(imp_jti)):
        return real_user

    # ── 3. 验证代理合法性 ──
    impersonated_by = imp_payload.get("impersonated_by")
    target_user_id = imp_payload.get("sub")

    if not impersonated_by or not target_user_id:
        return real_user

    # 验证 impersonated_by 匹配当前真实用户
    if impersonated_by != str(real_user.id):
        return real_user

    # 验证真实用户是管理员（以角色为准，被撤权后代理立即失效）
    if not await _has_manage_permission(db, real_user):
        return real_user

    # 查询目标用户
    from uuid import UUID
    try:
        target_uuid = UUID(target_user_id)
    except (ValueError, AttributeError):
        return real_user

    target_user = await _user_repo.get_by_id(db, target_uuid)
    if target_user is None:
        return real_user

    # 目标用户不能是管理员（同以角色为准）
    if await _has_manage_permission(db, target_user):
        return real_user

    # ── 4. 切换到目标用户上下文 ──
    target_user._impersonated_by = real_user.id  # type: ignore[attr-defined]
    logger.info(
        "Impersonation active: admin=%s(%s) -> target=%s(%s)",
        real_user.name, real_user.id, target_user.name, target_user.id,
    )
    return target_user


CurrentUser = Annotated[User | None, Depends(get_current_user)]
