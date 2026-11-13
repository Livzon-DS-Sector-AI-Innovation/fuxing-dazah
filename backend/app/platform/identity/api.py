import asyncio
import datetime
import logging
import secrets
from typing import Any

import jwt
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.exceptions import ForbiddenException, NotFoundException
from app.core.response import error_response, success_response
from app.platform.identity.deps import CurrentUser
from app.platform.identity.repository import DepartmentRepository, UserRepository
from app.platform.identity.schemas import (
    DepartmentResponse,
    DepartmentTreeNode,
    ImpersonateStartRequest,
    ImpersonateStartResponse,
    ImpersonateStatusResponse,
    ImpersonateUserInfo,
    PersonnelItem,
    PersonnelListResponse,
    UserResponse,
)
from app.platform.identity.service import IdentityService
from app.platform.integrations.feishu.client import FeishuClient
from app.platform.permission.deps import RequireAdmin, RequireUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["身份认证"])
user_router = APIRouter(tags=["用户信息"])
dept_router = APIRouter(prefix="/departments", tags=["组织架构"])
personnel_router = APIRouter(prefix="/personnel", tags=["人员名单"])
sync_router = APIRouter(prefix="/sync", tags=["飞书同步"])


def get_feishu_client(
    settings: Settings = Depends(get_settings),
) -> FeishuClient:
    return FeishuClient(settings)


def get_identity_service(
    settings: Settings = Depends(get_settings),
    feishu_client: FeishuClient = Depends(get_feishu_client),
) -> IdentityService:
    return IdentityService(
        settings=settings,
        feishu_client=feishu_client,
        user_repo=UserRepository(),
    )


# ── SSO ─────────────────────────────────────────────────────────────


@router.get("/login", summary="飞书 SSO 登录")
async def sso_login(
    service: IdentityService = Depends(get_identity_service),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Redirect to Feishu OAuth authorize page."""
    state_payload = {
        "nonce": secrets.token_urlsafe(32),
        "iat": datetime.datetime.now(tz=datetime.UTC),
        "exp": datetime.datetime.now(tz=datetime.UTC)
        + datetime.timedelta(minutes=5),
    }
    state = jwt.encode(state_payload, settings.SECRET_KEY, algorithm="HS256")
    url = service.build_login_url(state)
    return RedirectResponse(url, status_code=302)


@router.get("/callback", summary="飞书 SSO 回调")
async def sso_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
    service: IdentityService = Depends(get_identity_service),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Handle Feishu OAuth callback: exchange code, upsert user, issue JWT."""
    try:
        jwt.decode(state, settings.SECRET_KEY, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return RedirectResponse(
            f"{settings.FRONTEND_URL}/login?error=invalid_state",
            status_code=302,
        )

    try:
        token = await service.handle_callback(db, code)
    except Exception as exc:
        import logging

        logger = logging.getLogger(__name__)
        logger.exception("Feishu callback failed")
        return RedirectResponse(
            f"{settings.FRONTEND_URL}/login?error=auth_failed&detail={exc}",
            status_code=302,
        )

    return RedirectResponse(
        f"{settings.FRONTEND_URL}/auth/callback?token={token}",
        status_code=302,
    )


@user_router.get("/me", summary="获取当前用户信息")
async def get_current_user_info(
    user: CurrentUser = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return the current authenticated user's profile with permissions."""
    if user is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="未登录")

    from app.platform.permission.repository import PermissionRepository
    from app.shared.module_registry import MODULES_BY_CODE

    repo = PermissionRepository()
    perm_codes = await repo.get_user_permission_codes(db, user.id)

    # 批量查询角色编码（1 次查询替代 N 次）
    user_roles = await repo.get_user_roles(db, user.id)
    role_ids = [ur.role_id for ur in user_roles]
    roles = await repo.get_roles_by_ids(db, role_ids)
    role_codes = [r.code for r in roles]

    # 批量查询数据范围（3 次查询替代 O(modules × roles) 次）
    data_scopes = await repo.get_user_all_data_scopes(
        db, user.id, list(MODULES_BY_CODE),
    )

    return {
        **UserResponse.model_validate(user).model_dump(mode="json"),
        "permissions": sorted(perm_codes),
        "roles": role_codes,
        "data_scopes": data_scopes,
    }


# ── Departments ─────────────────────────────────────────────────────


def _build_department_tree(
    depts: list[Any], parent_id: str | None = None,
) -> list[DepartmentTreeNode]:
    """递归构建部门树。"""
    result: list[DepartmentTreeNode] = []
    for d in depts:
        if d.parent_feishu_department_id == parent_id or (
            parent_id is None and not d.parent_feishu_department_id
        ):
            node = DepartmentTreeNode(
                id=d.id,
                feishu_department_id=d.feishu_department_id,
                name=d.name,
                member_count=d.member_count,
                leader_user_id=d.leader_user_id,
                order=d.order,
                children=_build_department_tree(
                    depts, d.feishu_department_id,
                ),
            )
            result.append(node)
    return result


@dept_router.get("", summary="获取部门列表 / 组织架构树")
async def list_departments(
    tree: bool = Query(False, description="是否返回树形结构"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """获取所有部门。传 ?tree=true 返回层级组织架构树。"""
    repo = DepartmentRepository()
    depts = await repo.list_all(db)

    if tree:
        nodes = _build_department_tree(depts, parent_id=None)
        return success_response(data=[n.model_dump() for n in nodes])

    return success_response(
        data=[DepartmentResponse.model_validate(d).model_dump() for d in depts],
    )


@dept_router.get("/{dept_id}", summary="获取部门详情")
async def get_department(
    dept_id: str,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """按 open_department_id 获取单个部门详情。"""
    repo = DepartmentRepository()
    dept = await repo.get_by_feishu_id(db, dept_id)
    if dept is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="部门不存在")
    return success_response(data=DepartmentResponse.model_validate(dept).model_dump())


# ── Personnel ───────────────────────────────────────────────────────


@personnel_router.get(
    "/by-feishu/{feishu_user_id}",
    summary="根据飞书 user_id 查询用户信息（无需鉴权）",
)
async def get_personnel_by_feishu_user_id(
    feishu_user_id: str,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """通过飞书 user_id（union_id）精确查询用户姓名、工号、部门、岗位、手机号。"""
    repo = UserRepository()
    user = await repo.get_by_feishu_user_id(db, feishu_user_id)
    if user is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="用户不存在")
    return success_response(data=PersonnelItem.model_validate(user).model_dump())


@personnel_router.get("", summary="获取人员名单")
async def list_personnel(
    department_id: str | None = Query(None, description="按部门 ID 筛选"),
    keyword: str | None = Query(None, description="按姓名搜索"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """分页获取所有人员名单，支持按部门和姓名筛选。"""
    repo = UserRepository()
    users, total = await repo.list_all(
        db,
        department_id=department_id,
        keyword=keyword,
        offset=offset,
        limit=limit,
    )

    items = [PersonnelItem.model_validate(u) for u in users]
    resp = PersonnelListResponse(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
    )
    return success_response(data=resp.model_dump())


# ── Sync ────────────────────────────────────────────────────────────


@sync_router.post("/departments", summary="触发飞书组织架构同步（异步）")
async def trigger_sync_departments(
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """POST 触发一次飞书组织架构同步，后台执行不阻塞，立即返回。"""
    root_id = settings.FEISHU_SYNC_ROOT_DEPT_ID
    if not root_id:
        return JSONResponse(
            status_code=400,
            content={"message": "未配置 FEISHU_SYNC_ROOT_DEPT_ID"},
        )

    from app.platform.integrations.feishu.sync import sync_departments

    asyncio.create_task(sync_departments(root_id))
    logger.info("Department sync triggered for root=%s", root_id)
    return success_response(
        data={"message": "组织架构同步已触发", "root_dept_id": root_id},
    )


@sync_router.post("/members", summary="触发飞书成员同步（异步）")
async def trigger_sync_members(
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """POST 触发一次飞书成员同步，后台执行不阻塞，立即返回。"""
    target_id = settings.FEISHU_SYNC_MEMBER_DEPT_ID
    if not target_id:
        return JSONResponse(
            status_code=400,
            content={"message": "未配置 FEISHU_SYNC_MEMBER_DEPT_ID"},
        )

    from app.platform.integrations.feishu.sync import sync_members

    asyncio.create_task(sync_members(target_id))
    logger.info("Member sync triggered for target=%s", target_id)
    return success_response(
        data={"message": "成员同步已触发", "target_dept_id": target_id},
    )


# -- Impersonation --
impersonation_router = APIRouter(prefix="/impersonate", tags=["用户代理"])


@impersonation_router.post("/start", summary="开始代理用户身份")
async def start_impersonate(
    body: ImpersonateStartRequest,
    request: Request,
    admin: RequireAdmin,
    db: AsyncSession = Depends(get_db),
    service: IdentityService = Depends(get_identity_service),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    # 防嵌套代理
    existing = request.cookies.get("impersonate_token")
    if existing:
        imp_payload = service.decode_impersonate_jwt(existing)
        if imp_payload is not None:
            return error_response(
                message="已有活跃的代理会话，请先退出",
                status_code=403,
            )

    # 查询目标用户
    user_repo = UserRepository()
    target = await user_repo.get_by_id(db, body.target_user_id)
    if target is None:
        raise NotFoundException("用户", str(body.target_user_id))

    # 不能代理管理员
    if target.employee_no in settings.ADMIN_EMPLOYEE_NOS:
        raise ForbiddenException("不能代理其他管理员")

    # 生成代理 token
    token = service.generate_impersonate_jwt(target, admin)

    exp = datetime.datetime.now(tz=datetime.UTC) + datetime.timedelta(
        seconds=IdentityService.IMPERSONATE_EXPIRE_SECONDS,
    )

    resp = success_response(
        data=ImpersonateStartResponse(
            target_user_id=target.id,
            target_user_name=target.name,
            target_department=target.department or "",
            target_position=target.position or "",
            token=token,
            expires_at=exp,
        ).model_dump(mode="json"),
        message="代理会话已创建",
    )

    # 设置 httpOnly cookie
    resp.set_cookie(
        key="impersonate_token",
        value=token,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
        max_age=IdentityService.IMPERSONATE_EXPIRE_SECONDS,
    )
    return resp


@impersonation_router.post("/stop", summary="退出代理模式")
async def stop_impersonate(
    user: RequireUser,
) -> JSONResponse:
    resp = success_response(message="已退出代理模式")
    resp.delete_cookie("impersonate_token", path="/")
    return resp


def _not_impersonating() -> JSONResponse:
    return success_response(
        data=ImpersonateStatusResponse(is_impersonating=False).model_dump(mode="json"),
    )


@impersonation_router.get("/status", summary="查询代理状态")
async def impersonation_status(
    request: Request,
    user: RequireUser,
    db: AsyncSession = Depends(get_db),
    service: IdentityService = Depends(get_identity_service),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    imp_token = request.cookies.get("impersonate_token")
    if not imp_token:
        return _not_impersonating()

    payload = service.decode_impersonate_jwt(imp_token)
    if payload is None:
        return _not_impersonating()

    impersonated_by = payload.get("impersonated_by")
    target_user_id = payload.get("sub")
    if not impersonated_by or not target_user_id:
        return _not_impersonating()

    from uuid import UUID
    user_repo = UserRepository()

    try:
        admin = await user_repo.get_by_id(db, UUID(impersonated_by))
        target = await user_repo.get_by_id(db, UUID(target_user_id))
    except (ValueError, AttributeError):
        return _not_impersonating()

    if admin is None or target is None:
        return _not_impersonating()

    # 验证 JWT 中的管理员确实是管理员
    if admin.employee_no not in settings.ADMIN_EMPLOYEE_NOS:
        return _not_impersonating()

    exp_ts = payload.get("exp")
    expires_at = (
        datetime.datetime.fromtimestamp(exp_ts, tz=datetime.UTC)
        if exp_ts else None
    )

    return success_response(
        data=ImpersonateStatusResponse(
            is_impersonating=True,
            real_user=ImpersonateUserInfo(
                id=admin.id,
                name=admin.name,
                department=admin.department or "",
                position=admin.position or "",
            ),
            target_user=ImpersonateUserInfo(
                id=target.id,
                name=target.name,
                department=target.department or "",
                position=target.position or "",
            ),
            expires_at=expires_at,
        ).model_dump(mode="json"),
    )
